"""Nós do grafo de auditoria. Cada nó devolve apenas os campos do estado que alterou."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

import orjson
import structlog
from langgraph.runtime import Runtime
from langgraph.types import interrupt
from sqlalchemy import or_, select

from app.core.codes import formatar_codigo
from app.db.session import sync_tenant_session
from app.embeddings import client as embeddings
from app.ingest.cleaning import hash_descricao
from app.llm import gateway
from app.llm.prompts import carregar
from app.llm.schemas import (
    SCHEMA_ABREVIACOES,
    SCHEMA_ESCALONAMENTO,
    SCHEMA_JULGAMENTO,
    Escalonamento,
    ExpansaoAbreviacoes,
    Julgamento,
)
from app.models import ApprovedMemory, AuditItem, CClassTribCode, LlmCall
from app.models.enums import StatusItem
from app.pipeline.context import Contexto
from app.pipeline.normalize import inferir_tipo, normalizar_descricao, remover_marca, tokens_desconhecidos
from app.pipeline.reasons import Motivo
from app.pipeline.state import ItemState
from app.reference.search import buscar_candidatos, obter_no

log = structlog.get_logger()

Rt = Runtime[Contexto]


def _etapa(ctx: Contexto, item_id: str, etapa: str) -> None:
    with sync_tenant_session(ctx.tenant) as s:
        item = s.get(AuditItem, uuid.UUID(item_id))
        if item is not None:
            item.etapa = etapa
            if item.status == StatusItem.PENDENTE:
                item.status = StatusItem.PROCESSANDO


def _add(motivos: list[str], *novos: str) -> list[str]:
    return list(dict.fromkeys([*motivos, *novos]))


def chave_conteudo(no: str, modelo: str, prompt: str, conteudo: dict[str, Any]) -> str:
    """Chave de idempotência pelo CONTEÚDO: itens idênticos reutilizam a mesma resposta (sem novo custo)."""
    h = hashlib.sha256(orjson.dumps(conteudo, option=orjson.OPT_SORT_KEYS)).hexdigest()[:32]
    return f"{no}:{modelo}:{prompt}:{h}"


# ----------------------------------------------------------------------------- normalizar --
def normalizar(state: ItemState, runtime: Rt) -> dict[str, Any]:
    ctx = runtime.context
    _etapa(ctx, state.item_id, "normalizar")
    with sync_tenant_session(ctx.tenant) as s:
        item = s.get(AuditItem, uuid.UUID(state.item_id))
        assert item is not None
        descricao, tipo_inf, ncm, nbs, marca = item.descricao, item.tipo, item.ncm, item.nbs, item.marca
    normalizada, expansoes = normalizar_descricao(remover_marca(descricao, marca), ctx.abreviacoes)
    desconhecidos = tokens_desconhecidos(normalizada)
    if ctx.usar_modelo_leve and ctx.modo == "tempo_real" and len(desconhecidos) >= 2:
        prompt = carregar("expandir_abreviacoes")
        req = gateway.RequisicaoLLM(
            no="expandir_abreviacoes",
            modelo=ctx.modelo_leve,
            prompt=prompt,
            conteudo_usuario={"descricao": descricao, "pre_normalizada": normalizada},
            schema=SCHEMA_ABREVIACOES,
            validador=ExpansaoAbreviacoes,
            esforco="low",
            chave_idempotencia=f"item:{state.item_id}:t{state.tentativa}:abrev:{prompt.rotulo}",
            org_id=ctx.org_id,
            audit_id=ctx.audit_id,
            item_id=uuid.UUID(state.item_id),
            max_tokens=1500,
        )
        try:
            res = gateway.chamar_tempo_real(req)
            normalizada = res.dados["descricao_expandida"].strip().lower() or normalizada
            expansoes += [{**e, "origem": "modelo_leve"} for e in res.dados.get("expansoes", [])]
        except gateway.FalhaIA as e:  # a expansão é só um auxílio à busca
            log.warning("modelo_leve_falhou", erro=str(e))
    tipo = inferir_tipo(tipo_inf, ncm, nbs, normalizada)
    return {"descricao": descricao, "descricao_normalizada": normalizada, "expansoes": expansoes, "tipo": tipo}


# ---------------------------------------------------------------------- validar_estrutura --
def validar_estrutura(state: ItemState, runtime: Rt) -> dict[str, Any]:
    ctx = runtime.context
    _etapa(ctx, state.item_id, "validar_estrutura")
    motivos = list(state.motivos)
    estrutura: dict[str, Any] = {}
    base_incompleta = False
    with sync_tenant_session(ctx.tenant) as s:
        item = s.get(AuditItem, uuid.UUID(state.item_id))
        assert item is not None
        ncm, nbs, cst_atual, cct_atual = item.ncm, item.nbs, item.cst_atual, item.cclasstrib_atual
        problemas = {p["codigo"] for p in item.problemas or []}
        v_ncm, v_nbs, v_cct = ctx.versao("ncm"), ctx.versao("nbs"), ctx.versao("cclasstrib")

        if (state.tipo == "produto" and v_ncm is None) or (state.tipo == "servico" and v_nbs is None):
            base_incompleta = True
        if state.tipo == "desconhecido" and v_ncm is None and v_nbs is None:
            base_incompleta = True
        # O analista precisa da tabela cClassTrib e do texto legal; regras aprovadas não são pré-requisito.
        if v_cct is None or ctx.versao("lc214") is None:
            base_incompleta = True
        if base_incompleta:
            motivos = _add(motivos, Motivo.BASE_REFERENCIA_INCOMPLETA)

        atual: dict[str, Any] | None = None
        if ncm and v_ncm is not None:
            if len(ncm) == 8:
                no = obter_no(s, "ncm", v_ncm, ncm)
                atual = {
                    "tipo": "ncm",
                    "codigo": ncm,
                    "existe": no is not None,
                    "folha": bool(no and no["folha"]),
                    "descricao_completa": no["descricao_completa"] if no else None,
                    "vigente": bool(
                        no
                        and (no["data_fim"] is None or no["data_fim"] >= ctx.data_referencia)
                        and (no["data_inicio"] is None or no["data_inicio"] <= ctx.data_referencia)
                    ),
                }
                if no is None:
                    motivos = _add(motivos, Motivo.NCM_INEXISTENTE)
                elif not atual["vigente"]:
                    motivos = _add(motivos, Motivo.NCM_NAO_VIGENTE)
            elif len(ncm) == 7:
                motivos = _add(motivos, Motivo.NCM_ZERO_A_ESQUERDA_SUSPEITO)
                provavel = "0" + ncm
                no = obter_no(s, "ncm", v_ncm, provavel)
                atual = {
                    "tipo": "ncm",
                    "codigo": ncm,
                    "existe": False,
                    "folha": False,
                    "vigente": False,
                    "descricao_completa": None,
                    "provavel": provavel if no else None,
                    "descricao_provavel": no["descricao_completa"] if no else None,
                }
            else:
                motivos = _add(motivos, Motivo.NCM_NIVEL_INCOMPLETO)
                no = obter_no(s, "ncm", v_ncm, ncm)
                atual = {
                    "tipo": "ncm",
                    "codigo": ncm,
                    "existe": no is not None,
                    "folha": False,
                    "vigente": False,
                    "descricao_completa": no["descricao_completa"] if no else None,
                }
        elif nbs and v_nbs is not None:
            no = obter_no(s, "nbs", v_nbs, nbs)
            atual = {
                "tipo": "nbs",
                "codigo": nbs,
                "existe": no is not None,
                "folha": bool(no and no["folha"]),
                "vigente": no is not None,
                "descricao_completa": no["descricao_completa"] if no else None,
            }
            if no is None:
                motivos = _add(motivos, Motivo.NBS_INEXISTENTE)
            elif not no["folha"]:
                motivos = _add(motivos, Motivo.NBS_NIVEL_INCOMPLETO)
        if not ncm and not nbs:
            motivos = _add(motivos, Motivo.CODIGO_AUSENTE)
        estrutura["codigo_atual"] = atual
        estrutura["descricao_curta"] = "DESCRICAO_CURTA" in problemas
        if (cst_atual or cct_atual) and v_cct is not None:
            validos = {
                c
                for c in s.scalars(
                    select(CClassTribCode.codigo).where(
                        CClassTribCode.version_id == v_cct, CClassTribCode.codigo == (cct_atual or "")
                    )
                )
            }
            estrutura["cclasstrib_atual_existe"] = bool(cct_atual and cct_atual in validos)
    return {"estrutura": estrutura, "motivos": motivos, "base_incompleta": base_incompleta}


# ------------------------------------------------------------------------- buscar_memoria --
def buscar_memoria(state: ItemState, runtime: Rt) -> dict[str, Any]:
    ctx = runtime.context
    _etapa(ctx, state.item_id, "buscar_memoria")
    with sync_tenant_session(ctx.tenant) as s:
        item = s.get(AuditItem, uuid.UUID(state.item_id))
        assert item is not None
        h = hash_descricao(state.descricao_normalizada)
        filtros = [ApprovedMemory.descricao_hash == h]
        if item.gtin:
            filtros.append(ApprovedMemory.gtin == item.gtin)
        mems = list(
            s.scalars(
                select(ApprovedMemory)
                .where(ApprovedMemory.company_id == ctx.company_id, ApprovedMemory.ativo.is_(True), or_(*filtros))
                .order_by(ApprovedMemory.created_at.desc())
                .limit(5)
            )
        )
        # GTIN só vale se a descrição também bater (evita GTIN reaproveitado para outro produto).
        mem = next((m for m in mems if m.descricao_hash == h), None)
        if mem is None:
            return {"memoria": None}
        versao = ctx.versao(mem.tipo_codigo)
        no = obter_no(s, mem.tipo_codigo, versao, mem.codigo) if versao else None
        if no is None or not no["folha"]:
            return {"memoria": None}
        dados = {
            "id": str(mem.id),
            "codigo": mem.codigo,
            "tipo_codigo": mem.tipo_codigo,
            "cst": mem.cst,
            "cclasstrib": mem.cclasstrib,
            "atributos": mem.atributos or {},
            "descricao_completa": no["descricao_completa"],
            "aprovado_em": mem.created_at.isoformat(),
        }
    return {
        "memoria": dados,
        "codigo_final": dados["codigo"],
        "tipo_codigo_final": dados["tipo_codigo"],
        "atributos": {k: str(v) for k, v in dados["atributos"].items()},
    }


# ------------------------------------------------------------------ recuperar_candidatos --
def recuperar_candidatos(state: ItemState, runtime: Rt) -> dict[str, Any]:
    ctx = runtime.context
    _etapa(ctx, state.item_id, "recuperar_candidatos")
    consultas: list[tuple[str, uuid.UUID]] = []
    for tipo, fonte in (("produto", "ncm"), ("servico", "nbs")):
        v = ctx.versao(fonte)
        if v is not None and state.tipo in (tipo, "desconhecido"):
            consultas.append((fonte, v))
    semantica = all(ctx.completude.get(f"embeddings_{f}", False) for f, _ in consultas)
    embedding = embeddings.embed([state.descricao_normalizada])[0] if semantica else None
    with sync_tenant_session(ctx.tenant) as s:
        cands, info = buscar_candidatos(s, consultas, state.descricao_normalizada, embedding, k=15)
        lista = [c.como_dict() for c in cands]
        atual = (state.estrutura or {}).get("codigo_atual") or {}
        for chave in ("codigo", "provavel"):
            cod = atual.get(chave)
            if not cod or any(c["codigo"] == cod for c in lista):
                continue
            v = ctx.versao(atual["tipo"])
            no = obter_no(s, atual["tipo"], v, cod) if v else None
            if no and no["folha"]:
                lista.append(
                    {
                        "tipo_codigo": atual["tipo"],
                        "codigo": cod,
                        "descricao_completa": no["descricao_completa"],
                        "rank_semantico": None,
                        "rank_textual": None,
                        "score": 0.0,
                        "posicao": None,
                        "codigo_atual": True,
                    }
                )
        # O cadastro antigo é evidência da posição: os códigos vigentes da mesma posição (4 dígitos) do NCM
        # informado entram como candidatos, exista ou não o código (ex.: feijão cadastrado como "preto"
        # quando é "comum"). A busca por significado nem sempre os traz.
        cod_atual = atual.get("provavel") or atual.get("codigo") or ""
        if atual.get("tipo") == "ncm" and len(cod_atual) >= 4:
            v = ctx.versao("ncm")
            if v is not None:
                from sqlalchemy import text as sql

                for r in s.execute(
                    sql(
                        "SELECT codigo, descricao_completa FROM ncm_nodes WHERE version_id = :v AND folha "
                        "AND codigo LIKE :p ORDER BY (codigo LIKE :p6) DESC, codigo LIMIT 12"
                    ),
                    {"v": v, "p": cod_atual[:4] + "%", "p6": cod_atual[:6] + "%"},
                ):
                    if all(c["codigo"] != r.codigo for c in lista):
                        lista.append(
                            {
                                "tipo_codigo": "ncm",
                                "codigo": r.codigo,
                                "descricao_completa": r.descricao_completa,
                                "rank_semantico": None,
                                "rank_textual": None,
                                "score": 0.0,
                                "posicao": None,
                                "codigo_atual": False,
                            }
                        )
    for c in lista:
        c.setdefault("codigo_atual", c["codigo"] in (atual.get("codigo"), atual.get("provavel")))
    info["semantica"] = embedding is not None
    motivos = list(state.motivos)
    if not lista:
        motivos = _add(motivos, Motivo.NENHUM_CANDIDATO_ADEQUADO)
    saida: dict[str, Any] = {"candidatos": lista, "busca": info, "motivos": motivos}
    confirmado = _confirmacao_sem_ia(state, atual, lista)
    if confirmado is not None:
        saida.update(confirmado)
    return saida


def _confirmacao_sem_ia(state: ItemState, atual: dict[str, Any], lista: list[dict[str, Any]]) -> dict[str, Any] | None:
    """O NCM/NBS informado existe, está vigente e é o que a busca na tabela oficial aponta como mais
    provável para a descrição: fica confirmado sem chamar a IA. Qualquer dúvida segue para a IA."""
    cod = atual.get("codigo")
    if not cod or not (atual.get("existe") and atual.get("folha") and atual.get("vigente", True)):
        return None
    if (state.estrutura or {}).get("descricao_curta"):
        return None
    c = next((x for x in lista if x["codigo"] == cod), None)
    if c is None or not c.get("posicao"):
        return None
    pos, sem, txt = c["posicao"], c.get("rank_semantico"), c.get("rank_textual")
    # Os dois sinais independentes (significado e palavras) precisam apontar o código informado como o
    # primeiro. Basta um deles divergir (ex.: "sabonete LÍQUIDO" com NCM de sabonete em barra) para ir à IA.
    if not (pos == 1 and sem == 1 and txt == 1):
        return None
    return {
        "confirmado_sem_ia": True,
        "tipo_codigo_final": atual["tipo"],
        "codigo_final": cod,
        "posicao_confirmacao": pos,
    }


# --------------------------------------------------------------------- julgamento por IA --
def _atributos_para_extrair(ctx: Contexto, candidatos: list[dict[str, Any]]) -> list[dict[str, str]]:
    vistos: dict[str, dict[str, str]] = {}
    for c in candidatos:
        for r in ctx.regras.que_abrangem(c["tipo_codigo"], c["codigo"]):
            for cond in r.condicoes:
                if cond.get("fonte", "item") == "item" and cond["atributo"] not in vistos:
                    vistos[cond["atributo"]] = {"atributo": cond["atributo"], "pergunta": cond.get("pergunta", "")}
    return list(vistos.values())


def _conteudo(state: ItemState, ctx: Contexto) -> dict[str, Any]:
    with sync_tenant_session(ctx.tenant) as s:
        item = s.get(AuditItem, uuid.UUID(state.item_id))
        assert item is not None
        adicionais = {k: v for k, v in {"unidade": item.unidade, "categoria": item.categoria}.items() if v}
        marca = item.marca
    atual = (state.estrutura or {}).get("codigo_atual")
    codigo_atual: dict[str, Any] | None = None
    if atual:
        codigo_atual = {
            "tipo": atual["tipo"],
            "codigo": atual["codigo"],
            "codigo_formatado": formatar_codigo(atual["tipo"], atual["codigo"]),
            "existe_na_tabela_vigente": atual.get("existe", False),
            "descricao_oficial": atual.get("descricao_completa"),
        }
        if atual.get("provavel"):
            codigo_atual["observacao"] = (
                f"O código informado tem 7 dígitos; o provável código completo é {atual['provavel']} "
                f"({atual.get('descricao_provavel')}). Trate-o como o código atual."
            )
    return {
        "item": {
            "descricao_original": remover_marca(state.descricao, marca),
            "descricao_normalizada": state.descricao_normalizada,
            "tipo_inferido": state.tipo,
            "informacoes_adicionais": adicionais,
        },
        "codigo_atual": codigo_atual,
        "candidatos": [
            {
                "codigo": c["codigo"],
                "tipo": c["tipo_codigo"],
                "codigo_formatado": formatar_codigo(c["tipo_codigo"], c["codigo"]),
                "descricao_oficial": c["descricao_completa"],
            }
            for c in state.candidatos
        ],
        "atributos_para_extrair": _atributos_para_extrair(ctx, state.candidatos),
    }


def _executar(req: gateway.RequisicaoLLM, ctx: Contexto) -> gateway.ResultadoLLM:
    """Tempo real: chama a API. Lote: enfileira e interrompe o grafo até o resultado chegar.

    A chave é pelo conteúdo: uma trava garante que itens idênticos façam uma única chamada."""
    from app.core.redis import redis_sync

    trava = redis_sync().lock(f"trava:llm:{req.chave_idempotencia}", timeout=600, blocking_timeout=600)
    trava.acquire()
    try:
        # Lote só existe para modelos com Batch API (Anthropic); os demais saem em tempo real.
        if ctx.modo != "lote" or not gateway.suporta_lote(req.modelo):
            return gateway.chamar_tempo_real(req)
        existente = gateway.resultado_existente(req)
        if isinstance(existente, gateway.ResultadoLLM):
            return existente
        if isinstance(existente, LlmCall) and existente.status == "falhou":
            raise gateway.FalhaIA(existente.erro or "A requisição em lote falhou.")
        gateway.enfileirar_lote(req)
    finally:
        try:
            trava.release()
        except Exception:  # noqa: S110
            pass
    interrupt({"aguardando": "lote", "chave": req.chave_idempotencia})
    # Retomado pela tarefa coletora: o resultado já está gravado.
    existente = gateway.resultado_existente(req)
    if isinstance(existente, gateway.ResultadoLLM):
        return existente
    raise gateway.FalhaIA("O resultado do lote não foi encontrado para esta requisição.")


def _validar_codigo(dados: dict[str, Any], candidatos: list[dict[str, Any]]) -> tuple[bool, str | None]:
    cod = dados.get("codigo_sugerido")
    if cod is None:
        return (bool(dados.get("nenhum_candidato_serve")), None)
    if not any(c["codigo"] == cod for c in candidatos):
        return False, f"O modelo sugeriu {cod}, que não está na lista de candidatos."
    return True, None


def julgar_coerencia(state: ItemState, runtime: Rt) -> dict[str, Any]:
    ctx = runtime.context
    _etapa(ctx, state.item_id, "julgar_coerencia")
    prompt = carregar("julgar_coerencia", ctx.prompts.get("julgar_coerencia"))
    conteudo = _conteudo(state, ctx)
    req = gateway.RequisicaoLLM(
        no="julgar_coerencia",
        modelo=ctx.modelo_principal,
        prompt=prompt,
        conteudo_usuario=conteudo,
        schema=SCHEMA_JULGAMENTO,
        validador=Julgamento,
        esforco=ctx.esforco_principal,
        chave_idempotencia=chave_conteudo("julgar", ctx.modelo_principal, prompt.rotulo, conteudo),
        org_id=ctx.org_id,
        audit_id=ctx.audit_id,
        item_id=uuid.UUID(state.item_id),
    )
    motivos = list(state.motivos)
    try:
        res = _executar(req, ctx)
    except gateway.ChaveAPIAusente:
        raise
    except gateway.FalhaIA as e:
        return {"falha_ia": str(e), "julgamento_valido": False, "motivos": _add(motivos, Motivo.FALHA_NA_ANALISE_IA)}
    valido, erro = _validar_codigo(res.dados, state.candidatos)
    dados = {**res.dados, "_modelo": res.modelo, "_prompt": res.prompt_versao, "_call_id": str(res.call_id)}
    if not valido:
        dados["_descartado"] = erro
        return {
            "julgamento": dados,
            "julgamento_valido": False,
            "llm_calls": [*state.llm_calls, str(res.call_id)],
            "motivos": _add(motivos, Motivo.CODIGO_SUGERIDO_INVALIDO),
        }

    gatilhos: list[str] = []
    atual = (state.estrutura or {}).get("codigo_atual") or {}
    if res.dados["confianca"] < ctx.limiar_escalonamento:
        gatilhos.append("baixa_confianca")
    if res.dados.get("ncm_atual_coerente") is False:
        gatilhos.append("codigo_atual_incoerente")
    codigo_atual_ok = atual.get("existe") and atual.get("folha")
    if not codigo_atual_ok:
        gatilhos.append("sem_codigo_atual_valido")
    sug = res.dados.get("codigo_sugerido")
    if sug is not None:
        pos = next((c.get("posicao") for c in state.candidatos if c["codigo"] == sug), None)
        # A IA escolheu um código que a busca mal considerou: só aí vale um segundo parecer.
        if (pos is None or pos > 10) and res.dados["confianca"] < 0.95:
            gatilhos.append("divergencia_busca_julgamento")
    if res.dados.get("sinais_de_duvida") and res.dados["confianca"] < 0.85:
        gatilhos.append("sinais_de_duvida")
    return {
        "julgamento": dados,
        "julgamento_valido": True,
        "precisa_escalar": bool(gatilhos),
        "gatilhos_escalonamento": gatilhos,
        "llm_calls": [*state.llm_calls, str(res.call_id)],
    }


def escalar(state: ItemState, runtime: Rt) -> dict[str, Any]:
    ctx = runtime.context
    _etapa(ctx, state.item_id, "escalar")
    prompt = carregar("escalar", ctx.prompts.get("escalar"))
    conteudo = _conteudo(state, ctx)
    anterior = {k: v for k, v in (state.julgamento or {}).items() if not k.startswith("_")}
    conteudo["analise_anterior"] = anterior
    conteudo["motivos_do_escalonamento"] = state.gatilhos_escalonamento
    req = gateway.RequisicaoLLM(
        no="escalar",
        modelo=ctx.modelo_escalonamento,
        prompt=prompt,
        conteudo_usuario=conteudo,
        schema=SCHEMA_ESCALONAMENTO,
        validador=Escalonamento,
        esforco=ctx.esforco_escalonamento,
        chave_idempotencia=chave_conteudo("escalar", ctx.modelo_escalonamento, prompt.rotulo, conteudo),
        org_id=ctx.org_id,
        audit_id=ctx.audit_id,
        item_id=uuid.UUID(state.item_id),
        max_tokens=12000,
    )
    motivos = list(state.motivos)
    try:
        res = _executar(req, ctx)
    except gateway.ChaveAPIAusente:
        raise
    except gateway.FalhaIA as e:
        return {"falha_ia": str(e), "escalonamento_valido": False, "motivos": _add(motivos, Motivo.FALHA_NA_ANALISE_IA)}
    valido, erro = _validar_codigo(res.dados, state.candidatos)
    dados = {**res.dados, "_modelo": res.modelo, "_prompt": res.prompt_versao, "_call_id": str(res.call_id)}
    if not valido:
        dados["_descartado"] = erro
        return {
            "escalonamento": dados,
            "escalonamento_valido": False,
            "llm_calls": [*state.llm_calls, str(res.call_id)],
            "motivos": _add(motivos, Motivo.CODIGO_SUGERIDO_INVALIDO),
        }
    return {"escalonamento": dados, "escalonamento_valido": True, "llm_calls": [*state.llm_calls, str(res.call_id)]}
