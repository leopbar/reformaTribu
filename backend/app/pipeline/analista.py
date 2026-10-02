"""Nós do analista fiscal: investigação jurídica por família, fatos do item e conclusão.

Vêm depois da identificação (normalizar → validar → memória → candidatos → julgamento → segundo parecer).
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import delete, func, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.analise import aplicacao, evidencias, investigacao, operacao
from app.analise import fatos as fatos_mod
from app.analise.avaliacao import avaliar
from app.analise.dossie import rotulo_segmento
from app.analise.identidade import consolidar
from app.core.redis import trava_viva
from app.db.session import sync_tenant_session
from app.embeddings import client as embeddings
from app.events import bus
from app.llm import gateway
from app.llm.prompts import carregar
from app.llm.schemas import SCHEMA_FATOS_ITEM, SCHEMA_INVESTIGACAO, AtributosExtraidos, FatosItem, Investigacao
from app.models import Audit, AuditItem, Company, ItemCandidate, LlmCall, TaxThesis
from app.models.enums import EscopoFato, OrigemFato
from app.pipeline.nodes import Rt, _add, _etapa, _executar, chave_conteudo
from app.pipeline.normalize import remover_marca
from app.pipeline.reasons import Motivo
from app.pipeline.state import ItemState
from app.reference.search import obter_no

log = structlog.get_logger()


# ---------------------------------------------------------------- identidade consolidada --
def _mesclar_atributos(a: dict[str, str], b: dict[str, str] | None) -> dict[str, str]:
    """Atributos divergentes entre as análises viram 'desconhecido' (postura conservadora)."""
    if not b:
        return a
    saida = dict(a)
    for k, v in b.items():
        saida[k] = "desconhecido" if (k in saida and saida[k] != v) else v
    return saida


def codigo_escolhido(state: ItemState) -> tuple[str | None, str | None, dict[str, str]]:
    """(tipo_codigo, código, atributos) a partir da memória, do julgamento ou do segundo parecer."""
    if state.memoria or state.confirmado_sem_ia:
        return state.tipo_codigo_final, state.codigo_final, dict(state.atributos)
    j = state.julgamento if state.julgamento_valido else None
    if state.arvore and state.arvore.get("codigo"):
        # Código sugerido pela busca guiada na árvore oficial (o julgamento não tinha encontrado um).
        atributos = AtributosExtraidos.model_validate(j["atributos_extraidos"]).como_dict() if j else {}
        return state.arvore["tipo_codigo"], state.arvore["codigo"], atributos
    if state.arvore is not None and (erp := codigo_erp_valido(state)):
        # A busca guiada também não achou nada: o NCM do ERP fica como referência (não confirmado),
        # para o item não ficar sem código nem sem análise da lei.
        return erp[0], erp[1], {}
    esc = state.escalonamento if state.escalonamento_valido else None
    fonte = esc or j
    if fonte is None:
        return None, None, {}
    codigo = fonte.get("codigo_sugerido")
    tipo = next((c["tipo_codigo"] for c in state.candidatos if c["codigo"] == codigo), None)
    atributos = AtributosExtraidos.model_validate(j["atributos_extraidos"]).como_dict() if j else {}
    if esc:
        atributos = _mesclar_atributos(
            atributos, AtributosExtraidos.model_validate(esc["atributos_extraidos"]).como_dict()
        )
    return tipo, codigo, atributos


def codigo_erp_valido(state: ItemState) -> tuple[str, str] | None:
    """(tipo, código) do cadastro, se ele existe na tabela oficial, é completo e vale na data."""
    atual = (state.estrutura or {}).get("codigo_atual") or {}
    if atual.get("codigo") and atual.get("existe") and atual.get("folha") and atual.get("vigente", True):
        return str(atual.get("tipo") or "ncm"), str(atual["codigo"])
    return None


def estado_do_registro(session: Any, item: AuditItem) -> ItemState:
    """Reconstrói o estado do grafo a partir do que a análise gravou no item (respostas da IA, busca,
    árvore). Serve para refazer a identidade e a avaliação com as regras atuais SEM chamar a IA."""
    from app.analise.aplicacao import MOTIVOS_DA_AVALIACAO
    from app.models import ApprovedMemory

    idt = item.identidade or {}
    est = dict(item.estrutura or {})
    j = item.julgamento or None
    esc = item.escalonamento or None
    candidatos = [
        {
            "tipo_codigo": c.tipo_codigo,
            "codigo": c.codigo,
            "descricao_completa": c.descricao_completa,
            "posicao": c.posicao,
            "rank_semantico": c.rank_semantico,
            "rank_textual": c.rank_textual,
            "score": float(c.score or 0),
            "codigo_atual": c.codigo_atual,
        }
        for c in session.scalars(
            select(ItemCandidate).where(ItemCandidate.item_id == item.id).order_by(ItemCandidate.posicao)
        )
    ]
    if idt.get("corrigido_pela_lei"):
        for c in candidatos:
            if c["codigo"] == idt.get("codigo"):
                c["citado_na_lei"] = idt["corrigido_pela_lei"]
    memoria = None
    if item.origem == "memoria_aprovada" and item.memory_id:
        m = session.get(ApprovedMemory, item.memory_id)
        if m is not None:
            memoria = {
                "id": str(m.id),
                "tipo_codigo": m.tipo_codigo,
                "codigo": m.codigo,
                "descricao_completa": idt.get("descricao_oficial"),
            }
    sem_ia = bool(idt.get("sem_ia"))
    gatilhos = list(est.get("gatilhos_escalonamento") or [])
    falha_tese = item.erro if (item.erro or "").startswith("A investigação jurídica falhou") else None
    return ItemState(
        item_id=str(item.id),
        audit_id=str(item.audit_id),
        org_id=str(item.org_id),
        tentativa=item.tentativa,
        descricao=item.descricao,
        descricao_normalizada=item.descricao_normalizada or item.descricao,
        tipo=item.tipo or "desconhecido",
        estrutura=est,
        motivos=[m for m in item.motivos or [] if m not in MOTIVOS_DA_AVALIACAO],
        base_incompleta="BASE_REFERENCIA_INCOMPLETA" in (item.motivos or []),
        memoria=memoria,
        candidatos=candidatos,
        confirmado_sem_ia=sem_ia,
        posicao_confirmacao=next((c["posicao"] for c in candidatos if c["codigo_atual"]), 1) if sem_ia else None,
        julgamento=j,
        julgamento_valido=bool(j) and not (j or {}).get("_descartado"),
        precisa_escalar=bool(gatilhos),
        gatilhos_escalonamento=gatilhos,
        escalonamento=esc,
        escalonamento_valido=bool(esc) and not (esc or {}).get("_descartado"),
        arvore=idt.get("arvore"),
        tipo_codigo_final=idt.get("tipo_codigo") if (memoria or sem_ia) else None,
        codigo_final=idt.get("codigo") if (memoria or sem_ia) else None,
        tese_id=str(item.thesis_id) if item.thesis_id else None,
        tese_falha=falha_tese,
    )


def identidade(state: ItemState) -> dict[str, Any]:
    tipo, codigo, _ = codigo_escolhido(state)
    return consolidar(
        descricao_normalizada=state.descricao_normalizada,
        tipo=state.tipo,
        estrutura=state.estrutura,
        memoria=state.memoria,
        julgamento=state.julgamento,
        julgamento_valido=state.julgamento_valido,
        escalonamento=state.escalonamento,
        escalonamento_valido=state.escalonamento_valido,
        escalonado=state.precisa_escalar and not state.memoria,
        codigo_final=codigo,
        tipo_codigo_final=tipo,
        candidatos=state.candidatos,
        motivos=state.motivos,
        confirmado_sem_ia=state.posicao_confirmacao if state.confirmado_sem_ia else None,
        arvore=state.arvore,
    )


# ------------------------------------------------------------------------------ investigar --
def investigar(state: ItemState, runtime: Rt) -> dict[str, Any]:
    """Tese jurídica da família (código + cenário + dossiê + data): feita uma vez e reaproveitada."""
    ctx = runtime.context
    _etapa(ctx, state.item_id, "investigar")
    tipo, codigo, atributos = codigo_escolhido(state)
    saida: dict[str, Any] = {"tipo_codigo_final": tipo, "codigo_final": codigo, "atributos": atributos}
    if not codigo or not tipo or ctx.snapshot_id is None:
        return {**saida, "tese_id": None}
    prompt = carregar("investigar_enquadramento", ctx.prompts.get("investigar_enquadramento"))
    # O material jurídico é montado antes da busca da tese: a chave é o conteúdo dele (sem custo de IA).
    versao_cod = ctx.versao(tipo)
    with sync_tenant_session(ctx.tenant) as s:
        no = obter_no(s, tipo, versao_cod, codigo) if versao_cod else None
    consulta = " ".join(((no or {}).get("descricao_completa") or "").split(" › ")[-3:])
    emb = None
    if ctx.completude.get("embeddings_normas") and consulta:
        try:
            emb = embeddings.embed([consulta])[0]
        except embeddings.EmbeddingsIndisponivel:
            emb = None
    with sync_tenant_session(ctx.tenant) as s:
        ev = evidencias.montar(
            s,
            tipo_codigo=tipo,
            codigo=codigo,
            data_referencia=ctx.data_referencia,
            versoes=ctx.versoes,
            versoes_normas=ctx.versoes_normas,
            regras_ids=[str(r.id) for r in [*ctx.regras.aprovadas, *ctx.regras.pendentes]],
            fatos_empresa=ctx.dossie,
            embedding=emb,
        )

    def chave_de(pacote: dict[str, Any], dossie: dict[str, str]) -> str:
        return investigacao.chave_familia(
            company_id="",  # a tese vale para toda a organização (mesmo dossiê → mesma tese)
            tipo_codigo=tipo,
            codigo=codigo,
            cenario=ctx.cenario,
            data_referencia=ctx.data_referencia,
            evidencias=investigacao.impressao_evidencias(pacote),
            dossie=dossie,
        )

    chave = chave_de(ev.pacote, ctx.dossie)

    def existente() -> str | None:
        with sync_tenant_session(ctx.tenant) as s:
            t = s.scalar(select(TaxThesis).where(TaxThesis.chave == chave, TaxThesis.status == "concluida"))
            if t is not None:
                return str(t.id)
            # Teses gravadas com outra forma de chave: compara pelo material que elas guardaram.
            for t in s.scalars(
                select(TaxThesis).where(
                    TaxThesis.status == "concluida",
                    TaxThesis.tipo_codigo == tipo,
                    TaxThesis.codigo == codigo,
                    TaxThesis.cenario == ctx.cenario,
                    TaxThesis.data_referencia == ctx.data_referencia,
                )
            ):
                pacote = (t.evidencias or {}).get("pacote")
                if pacote and chave_de(pacote, t.fatos_empresa or {}) == chave:
                    return str(t.id)
            return None

    if (tid := existente()) is not None:
        return {**saida, "tese_id": tid}
    # Um worker por família de cada vez: os demais esperam e reaproveitam a tese.
    with trava_viva(f"trava:tese:{ctx.org_id}:{chave}", espera_s=900):
        if (tid := existente()) is not None:
            return {**saida, "tese_id": tid}
        req = gateway.RequisicaoLLM(
            no="investigar_enquadramento",
            modelo=ctx.modelo_investigacao,
            prompt=prompt,
            conteudo_usuario=investigacao.conteudo(ev, ctx.dossie, ctx.cenario),
            schema=SCHEMA_INVESTIGACAO,
            validador=Investigacao,
            esforco=ctx.esforco_investigacao,
            chave_idempotencia=f"tese:{chave}",
            org_id=ctx.org_id,
            audit_id=ctx.audit_id,
            item_id=None,
            max_tokens=16000,
        )
        try:
            res = _executar(req, ctx)
        except (gateway.ChaveAPIAusente, gateway.IAIndisponivel):
            raise
        except gateway.FalhaIA as e:
            return {**saida, "tese_id": None, "tese_falha": f"A investigação jurídica falhou: {e}"}
        resultado, validacao = investigacao.validar(res.dados, ev)
        with sync_tenant_session(ctx.tenant) as s:
            tid_novo = s.execute(
                pg_insert(TaxThesis)
                .values(
                    id=uuid.uuid4(),
                    org_id=ctx.org_id,
                    company_id=ctx.company_id,
                    audit_id=ctx.audit_id,
                    chave=chave,
                    tipo_codigo=tipo,
                    codigo=codigo,
                    cenario=ctx.cenario,
                    data_referencia=ctx.data_referencia,
                    snapshot_id=ctx.snapshot_id,
                    status="concluida",
                    evidencias={
                        "pacote": ev.pacote,
                        "refs": ev.refs,
                        "cclasstrib": ev.cclasstrib,
                        "correlacionados": sorted(ev.correlacionados),
                        "precedentes": ev.precedentes,
                        "alertas": ev.alertas,
                    },
                    resultado=resultado,
                    validacao=validacao,
                    fatos_empresa=ctx.dossie,
                    llm_call_id=res.call_id,
                    modelo=res.modelo,
                    prompt_versao=res.prompt_versao,
                )
                .on_conflict_do_update(constraint="uq_tax_theses_org_chave", set_={"status": "concluida"})
                .returning(TaxThesis.id)
            ).scalar_one()
        return {**saida, "tese_id": str(tid_novo), "llm_calls": [*state.llm_calls, str(res.call_id)]}


# -------------------------------------------------------------------------- levantar fatos --
def levantar_fatos(state: ItemState, runtime: Rt) -> dict[str, Any]:
    """Fatos do item explícitos na descrição ou no ERP (modelo leve). Inferência não vira fato.

    Pede os fatos da tese da família (se houver) e os dos regimes da operação ativos para a empresa
    (ADR 0026), que valem mesmo para itens sem NCM definido."""
    ctx = runtime.context
    if state.fatos_levantados:
        return {"fatos_levantados": True}
    with sync_tenant_session(ctx.tenant) as s:
        tese = s.get(TaxThesis, uuid.UUID(state.tese_id)) if state.tese_id else None
        item = s.get(AuditItem, uuid.UUID(state.item_id))
        assert item is not None
        empresa = s.get(Company, item.company_id)
        assert empresa is not None
        familia = (
            fatos_mod.grupo_familia(state.tipo_codigo_final or "ncm", state.codigo_final)
            if state.codigo_final
            else None
        )
        conhecidos = fatos_mod.resolver(
            s, empresa, item_chave=item.codigo_interno, categoria=item.categoria, familia=familia
        )
        valores = {k: f.como_dict() for k, f in conhecidos.items()}
        regimes = operacao.regimes_da_empresa(valores).regimes
        implicitos = operacao.fatos_implicitos(regimes, valores, state.tipo_codigo_final, state.codigo_final)
        candidatos = [
            *operacao.fatos_necessarios(regimes),
            *(investigacao.fatos_item_necessarios(tese.resultado) if tese is not None else []),
        ]
        pedidos: list[dict[str, Any]] = []
        for f in candidatos:
            k = fatos_mod.chave(f["fato"])
            if k not in conhecidos and k not in implicitos and all(fatos_mod.chave(p["fato"]) != k for p in pedidos):
                pedidos.append(f)
        erp = {"categoria": item.categoria, "unidade": item.unidade, "tipo_no_erp": item.tipo_informado}
        dados_item = {
            "descricao_original": remover_marca(item.descricao, item.marca),
            "descricao_normalizada": state.descricao_normalizada,
            **{k: v for k, v in erp.items() if v},
        }
        pacote = ((tese.evidencias if tese is not None else None) or {}).get("pacote") or {}
        identidade_item = {
            "codigo": state.codigo_final,
            "descricao_oficial": (pacote.get("codigo") or {}).get("descricao_oficial"),
        }
        # O tipo de estabelecimento ajuda a ler a descrição ("ESPRESSO" num restaurante é bebida feita ali).
        estabelecimento: dict[str, str | None] = {
            "segmento": rotulo_segmento(empresa.segmento),
            **{
                k: valores[k]["valor"]
                for k in ("fornece_refeicoes", "produz_alimentos", "manipula_medicamentos")
                if k in valores
            },
        }
        org_id, company_id, codigo_interno = item.org_id, item.company_id, item.codigo_interno
    if not pedidos:
        return {"fatos_levantados": True}
    _etapa(ctx, state.item_id, "levantar_fatos")
    if not pedidos:
        return {"fatos_levantados": True}
    prompt = carregar("extrair_fatos", ctx.prompts.get("extrair_fatos"))
    req = gateway.RequisicaoLLM(
        no="extrair_fatos",
        modelo=ctx.modelo_fatos,
        prompt=prompt,
        conteudo_usuario={
            "item": dados_item,
            "identidade": identidade_item,
            "estabelecimento": estabelecimento,
            "fatos_pedidos": [
                {
                    "fato": f["fato"],
                    "pergunta": f["pergunta"],
                    "opcoes": f["opcoes"],
                    "como_identificar": f.get("como_identificar_na_descricao", ""),
                }
                for f in pedidos
            ],
        },
        schema=SCHEMA_FATOS_ITEM,
        validador=FatosItem,
        esforco="low",
        chave_idempotencia=chave_conteudo(
            "fatos",
            ctx.modelo_fatos,
            prompt.rotulo,
            {"t": state.tese_id, "i": dados_item, "p": pedidos, "e": estabelecimento},
        ),
        org_id=ctx.org_id,
        audit_id=ctx.audit_id,
        item_id=uuid.UUID(state.item_id),
        max_tokens=3000,
    )
    try:
        res = _executar(req, ctx)
    except (gateway.ChaveAPIAusente, gateway.IAIndisponivel):
        raise
    except gateway.FalhaIA as e:  # sem os fatos, as perguntas simplesmente ficam abertas
        log.warning("levantar_fatos_falhou", erro=str(e))
        return {"fatos_levantados": True}
    validos = {fatos_mod.chave(f["fato"]): f for f in pedidos}
    sugestoes: dict[str, dict[str, str]] = {}
    with sync_tenant_session(ctx.tenant) as s:
        for f in res.dados["fatos"]:
            k = fatos_mod.chave(f["fato"])
            v = fatos_mod.valor(f["valor"])
            if k not in validos or v == fatos_mod.DESCONHECIDO:
                continue
            opcoes = {fatos_mod.valor(o) for o in validos[k].get("opcoes") or []}
            if opcoes and v not in opcoes:
                continue
            if f["base"] == "explicito" and f.get("evidencia"):
                fatos_mod.registrar(
                    s,
                    org_id=org_id,
                    company_id=company_id,
                    escopo=EscopoFato.ITEM,
                    item_chave=codigo_interno,
                    atributo=k,
                    valor_=v,
                    origem=OrigemFato.DESCRICAO,
                    evidencia=f["evidencia"][:500],
                    audit_id=ctx.audit_id,
                )
            elif f["base"] == "inferencia":
                sugestoes[k] = {"valor": v, "evidencia": (f.get("evidencia") or "")[:300]}
        item = s.get(AuditItem, uuid.UUID(state.item_id))
        assert item is not None
        item.estrutura = {**(item.estrutura or {}), "sugestoes_fatos": sugestoes}
    return {"fatos_levantados": True, "llm_calls": [*state.llm_calls, str(res.call_id)]}


# ------------------------------------------------------------------------------- concluir --
def concluir(state: ItemState, runtime: Rt) -> dict[str, Any]:
    """Avalia a tese com os fatos do item e grava o perfil tributário, as perguntas e o registro."""
    ctx = runtime.context
    idt = identidade(state)
    tipo, codigo, atributos = codigo_escolhido(state)
    motivos = list(state.motivos)
    with sync_tenant_session(ctx.tenant) as s:
        item = s.get(AuditItem, uuid.UUID(state.item_id))
        audit = s.get(Audit, uuid.UUID(state.audit_id))
        assert item is not None and audit is not None
        if item.duplicado_de is not None:
            motivos = _add(motivos, Motivo.ITEM_DUPLICADO)
        item.descricao_normalizada = state.descricao_normalizada
        item.tipo = state.tipo
        item.identidade = idt
        item.atributos = atributos
        item.julgamento = state.julgamento or {}
        item.escalonamento = state.escalonamento or {}
        item.origem = "memoria_aprovada" if state.memoria else "pipeline"
        item.memory_id = uuid.UUID(state.memoria["id"]) if state.memoria else None
        conf = idt.get("confianca_modelo")
        item.confianca = Decimal(str(conf)) if conf is not None else None
        item.estrutura = {
            **(item.estrutura or {}),
            **(state.estrutura or {}),
            "expansoes": state.expansoes,
            "busca": state.busca,
            "gatilhos_escalonamento": state.gatilhos_escalonamento,
        }
        item.erro = state.tese_falha or (state.arvore or {}).get("erro") or (state.falha_ia if not codigo else None)
        tese = s.get(TaxThesis, uuid.UUID(state.tese_id)) if state.tese_id else None
        entrada = aplicacao.entrada(
            s, item, audit, tese, tese_falha=state.tese_falha, base_incompleta=state.base_incompleta
        )
        av = avaliar(entrada)
        aplicacao.aplicar(s, item, audit, av, tese, motivos_identidade=motivos)
        custo = s.scalar(select(func.coalesce(func.sum(LlmCall.custo_usd), 0)).where(LlmCall.item_id == item.id))
        item.custo_usd = Decimal(str(custo or 0))
        s.execute(delete(ItemCandidate).where(ItemCandidate.item_id == item.id))
        if state.candidatos:
            s.execute(
                insert(ItemCandidate),
                [
                    {
                        "org_id": ctx.org_id,
                        "item_id": item.id,
                        "tipo_codigo": c["tipo_codigo"],
                        "codigo": c["codigo"],
                        "descricao_completa": c["descricao_completa"],
                        "posicao": c.get("posicao") or 99,
                        "rank_semantico": c.get("rank_semantico"),
                        "rank_textual": c.get("rank_textual"),
                        "score": Decimal(str(c.get("score") or 0)),
                        "codigo_atual": bool(c.get("codigo_atual")),
                    }
                    for c in state.candidatos
                ],
            )
        status = item.status
    bus.publicar(ctx.audit_id, "item", {"item_id": state.item_id, "status": status})
    return {"status": status, "concluido": True, "tipo_codigo_final": tipo, "codigo_final": codigo}
