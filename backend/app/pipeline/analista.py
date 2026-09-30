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

from app.analise import aplicacao, evidencias, investigacao
from app.analise import fatos as fatos_mod
from app.analise.avaliacao import avaliar
from app.analise.identidade import consolidar
from app.core.redis import redis_sync
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
    trava = redis_sync().lock(f"trava:tese:{ctx.org_id}:{chave}", timeout=900, blocking_timeout=900)
    trava.acquire()
    try:
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
        except gateway.ChaveAPIAusente:
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
    finally:
        try:
            trava.release()
        except Exception:  # noqa: S110
            pass


# -------------------------------------------------------------------------- levantar fatos --
def levantar_fatos(state: ItemState, runtime: Rt) -> dict[str, Any]:
    """Fatos do item explícitos na descrição ou no ERP (modelo leve). Inferência não vira fato."""
    ctx = runtime.context
    if not state.tese_id or state.fatos_levantados:
        return {"fatos_levantados": True}
    _etapa(ctx, state.item_id, "levantar_fatos")
    with sync_tenant_session(ctx.tenant) as s:
        tese = s.get(TaxThesis, uuid.UUID(state.tese_id))
        item = s.get(AuditItem, uuid.UUID(state.item_id))
        assert tese is not None and item is not None
        empresa = s.get(Company, item.company_id)
        assert empresa is not None
        familia = fatos_mod.grupo_familia(state.tipo_codigo_final or "ncm", state.codigo_final or "")
        conhecidos = fatos_mod.resolver(
            s, empresa, item_chave=item.codigo_interno, categoria=item.categoria, familia=familia
        )
        pedidos = [
            f
            for f in investigacao.fatos_item_necessarios(tese.resultado)
            if fatos_mod.chave(f["fato"]) not in conhecidos
        ]
        erp = {"categoria": item.categoria, "unidade": item.unidade}
        dados_item = {
            "descricao_original": remover_marca(item.descricao, item.marca),
            "descricao_normalizada": state.descricao_normalizada,
            **{k: v for k, v in erp.items() if v},
        }
        pacote = (tese.evidencias or {}).get("pacote") or {}
        identidade_item = {
            "codigo": state.codigo_final,
            "descricao_oficial": (pacote.get("codigo") or {}).get("descricao_oficial"),
        }
        org_id, company_id, codigo_interno = item.org_id, item.company_id, item.codigo_interno
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
            "fatos", ctx.modelo_fatos, prompt.rotulo, {"t": state.tese_id, "i": dados_item, "p": pedidos}
        ),
        org_id=ctx.org_id,
        audit_id=ctx.audit_id,
        item_id=uuid.UUID(state.item_id),
        max_tokens=3000,
    )
    try:
        res = _executar(req, ctx)
    except gateway.ChaveAPIAusente:
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
        item.erro = state.falha_ia or state.tese_falha or (state.arvore or {}).get("erro")
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
