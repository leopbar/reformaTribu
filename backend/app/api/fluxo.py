"""Fluxo dos agentes: o caminho de cada item pelas caixas e a visão geral da auditoria (ao vivo)."""

from __future__ import annotations

import math
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select, text
from starlette.concurrency import run_in_threadpool

from app.analise import caminho
from app.analise.avaliacao import DIMENSOES
from app.api.audits import _carregar_auditoria
from app.core.codes import formatar_codigo
from app.core.deps import Principal, SessionDep, exigir
from app.core.errors import NaoEncontrado
from app.core.rbac import Perm
from app.llm import catalogo as catalogo_ia
from app.models import AuditItem, CompanyFact, ItemCandidate, LlmCall, TaxThesis, UploadedFile
from app.models.enums import EscopoFato, OrigemFato

router = APIRouter(tags=["fluxo dos agentes"])
Ver = Annotated[Principal, Depends(exigir(Perm.VER))]
ROTULO_DIM = dict(DIMENSOES)


class PassoOut(BaseModel):
    caixa: str
    situacao: str
    resumo: str
    detalhes: list[dict[str, str]]
    ia: dict[str, Any] | None
    proximo: str | None


class CaminhoOut(BaseModel):
    item_id: str
    status: str
    em_andamento: bool
    caixa_atual: str | None
    passos: list[PassoOut]
    custo_usd: float


def _chamada(c: LlmCall, item_id: uuid.UUID, *, compartilhada: bool = False) -> dict[str, Any]:
    reaproveitada = not compartilhada and c.item_id != item_id
    return {
        "modelo": c.modelo,
        "custo_usd": 0.0 if reaproveitada else float(c.custo_usd or 0),
        "custo_original_usd": float(c.custo_usd or 0),
        "tokens_entrada": c.tokens_entrada,
        "tokens_saida": c.tokens_saida,
        "reaproveitada": reaproveitada,
        "compartilhada": compartilhada,
        "status": c.status,
    }


def _estado_checkpoint(item_id: uuid.UUID, tentativa: int) -> dict[str, Any] | None:
    """Estado parcial do grafo de um item em processamento (o item só é gravado no fim)."""
    try:
        from app.pipeline.graph import grafo
        from app.pipeline.runner import thread_id

        st = grafo().get_state({"configurable": {"thread_id": thread_id(item_id, tentativa)}})
    except Exception:
        return None
    valores = getattr(st, "values", None)
    if not valores:
        return None
    return valores.model_dump() if hasattr(valores, "model_dump") else dict(valores)


def _uuid(v: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(v)) if v else None
    except ValueError:
        return None


@router.get("/itens/{item_id}/caminho", response_model=CaminhoOut)
async def caminho_item(item_id: uuid.UUID, principal: Ver, session: SessionDep) -> CaminhoOut:
    """Por quais agentes o item passou, quais pulou e o que cada um fez (ao vivo durante o processamento)."""
    i = await session.get(AuditItem, item_id)
    if i is None:
        raise NaoEncontrado("Item não encontrado.")
    a = await _carregar_auditoria(session, principal, i.audit_id)
    em_andamento = i.status not in caminho.STATUS_FINAIS
    estado = await run_in_threadpool(_estado_checkpoint, i.id, i.tentativa) if em_andamento else None

    # Chamadas de IA: as deste item, as reaproveitadas de itens idênticos e a do parecer da família.
    chamadas: dict[str, dict[str, Any]] = {}
    for c in await session.scalars(select(LlmCall).where(LlmCall.item_id == i.id).order_by(LlmCall.created_at)):
        cx = caminho.NO_CAIXA.get(c.no)
        if cx and cx in chamadas and cx == "navegador":
            # A busca guiada faz uma chamada por nível da árvore: soma o custo.
            atual = chamadas[cx]
            nova = _chamada(c, i.id)
            atual["custo_usd"] = round(float(atual["custo_usd"]) + float(nova["custo_usd"]), 6)
            atual["custo_original_usd"] = round(
                float(atual["custo_original_usd"]) + float(nova["custo_original_usd"]), 6
            )
        elif cx:
            chamadas[cx] = _chamada(c, i.id)
    fonte: dict[str, Any] = estado or {}
    julg = (fonte.get("julgamento") if estado else i.julgamento) or {}
    esc = (fonte.get("escalonamento") if estado else i.escalonamento) or {}
    for cx, parecer in (("identificador", julg), ("segundo_parecer", esc)):
        cid = _uuid(parecer.get("_call_id"))
        if cid and cx not in chamadas:
            outra = await session.get(LlmCall, cid)
            if outra is not None:
                chamadas[cx] = _chamada(outra, i.id)

    tese_id = _uuid(fonte.get("tese_id")) if estado else i.thesis_id
    tese_out: dict[str, Any] | None = None
    if tese_id:
        t = await session.get(TaxThesis, tese_id)
        if t is not None:
            itens_familia = await session.scalar(
                select(func.count())
                .select_from(AuditItem)
                .where(AuditItem.audit_id == i.audit_id, AuditItem.thesis_id == t.id)
            )
            res = t.resultado or {}
            tese_out = {
                "codigo": formatar_codigo(t.tipo_codigo, t.codigo),
                "entendimento": res.get("entendimento"),
                "hipoteses": res.get("hipoteses", []),
                "fatos_necessarios": res.get("fatos_necessarios", []),
                "reaproveitada": t.audit_id != i.audit_id,
                "itens_familia": int(itens_familia or 1),
            }
            if t.llm_call_id:
                da_tese = await session.get(LlmCall, t.llm_call_id)
                if da_tese is not None:
                    info = _chamada(da_tese, i.id, compartilhada=True)
                    if tese_out["reaproveitada"]:
                        info["custo_usd"] = 0.0
                        info["reaproveitada"] = True
                    else:
                        # O custo do parecer é dividido entre os itens da família nesta auditoria.
                        info["custo_usd"] = round(info["custo_original_usd"] / max(1, tese_out["itens_familia"]), 6)
                    chamadas["jurista"] = info

    if estado:
        cands = fonte.get("candidatos") or []
        conhecidos = bool(fonte.get("busca"))
    else:
        rows = await session.scalars(select(ItemCandidate).where(ItemCandidate.item_id == i.id))
        cands = [
            {
                "tipo_codigo": c.tipo_codigo,
                "codigo": c.codigo,
                "descricao_completa": c.descricao_completa,
                "posicao": c.posicao,
                "rank_semantico": c.rank_semantico,
                "rank_textual": c.rank_textual,
                "codigo_atual": c.codigo_atual,
            }
            for c in rows
        ]
        conhecidos = True

    fatos_lidos = [
        {"atributo": f.atributo, "valor": f.valor, "evidencia": f.evidencia}
        for f in await session.scalars(
            select(CompanyFact).where(
                CompanyFact.company_id == i.company_id,
                CompanyFact.escopo == EscopoFato.ITEM,
                CompanyFact.item_chave == i.codigo_interno,
                CompanyFact.origem == OrigemFato.DESCRICAO,
                CompanyFact.audit_id == i.audit_id,
            )
        )
    ]
    lidos = {f["atributo"] for f in fatos_lidos}
    estrutura = (fonte.get("estrutura") if estado else i.estrutura) or {}
    etapa = i.etapa or ""
    reg = caminho.Registro(
        descricao=i.descricao,
        status=i.status,
        data_referencia=a.data_referencia.strftime("%d/%m/%Y"),
        marca=i.marca,
        descricao_normalizada=(fonte.get("descricao_normalizada") if estado else i.descricao_normalizada) or None,
        expansoes=(fonte.get("expansoes") if estado else estrutura.get("expansoes")) or [],
        tipo=(fonte.get("tipo") if estado else i.tipo),
        estrutura=estrutura,
        motivos=list((fonte.get("motivos") if estado else i.motivos) or []),
        base_incompleta=bool(fonte.get("base_incompleta"))
        if estado
        else "BASE_REFERENCIA_INCOMPLETA" in (i.motivos or []),
        memoria=fonte.get("memoria")
        if estado
        else (
            {
                "codigo": (i.identidade or {}).get("codigo"),
                "tipo_codigo": (i.identidade or {}).get("tipo_codigo"),
                "descricao_completa": (i.identidade or {}).get("descricao_oficial"),
            }
            if i.origem == "memoria_aprovada"
            else None
        ),
        confirmado_sem_ia=bool(fonte.get("confirmado_sem_ia")) if estado else bool((i.identidade or {}).get("sem_ia")),
        candidatos=cands,
        candidatos_conhecidos=conhecidos,
        julgamento=julg or None,
        julgamento_valido=fonte.get("julgamento_valido") if estado and julg else None,
        gatilhos=list(
            (fonte.get("gatilhos_escalonamento") if estado else estrutura.get("gatilhos_escalonamento")) or []
        ),
        escalonamento=esc or None,
        identidade=i.identidade or {},
        arvore=(fonte.get("arvore") if estado else (i.identidade or {}).get("arvore")),
        tese=tese_out,
        tese_falha=fonte.get("tese_falha")
        if estado
        else (i.erro if i.erro and "investigação jurídica" in i.erro else None),
        fatos_lidos=fatos_lidos,
        sugestoes=estrutura.get("sugestoes_fatos") or {},
        fatos_conhecidos=[f for f in (i.fatos_usados or []) if f.get("atributo") not in lidos],
        hipotese=i.hipotese,
        cclasstrib=i.final_cclasstrib or i.cclasstrib_sugerido,
        cst=i.final_cst or i.cst_sugerido,
        conclusao=i.conclusao,
        dimensoes={k: {**v, "rotulo": ROTULO_DIM.get(k, k)} for k, v in (i.dimensoes or {}).items()},
        perguntas=i.perguntas or [],
        aprovado_automaticamente=i.aprovado_automaticamente,
        erro=i.erro,
        caixa_atual=caminho.ETAPA_CAIXA.get(etapa) if em_andamento else None,
        aguardando_lote=em_andamento and etapa == "aguardando_lote",
        chamadas=chamadas,
    )
    if reg.aguardando_lote:
        # Parado à espera do lote: a caixa é a última cuja chamada foi enfileirada.
        pendente = next(
            (cx for cx in ("leitor", "jurista", "segundo_parecer", "identificador") if cx in chamadas),
            "identificador",
        )
        reg.caixa_atual = pendente
    passos = caminho.montar(reg)
    return CaminhoOut(
        item_id=str(i.id),
        status=i.status,
        em_andamento=em_andamento,
        caixa_atual=reg.caixa_atual,
        passos=[PassoOut(**p.como_dict()) for p in passos],
        custo_usd=round(sum(float((p.ia or {}).get("custo_usd") or 0) for p in passos), 6),
    )


# ====================================================================== visão geral ==
class CaixaResumo(BaseModel):
    passaram: int = 0
    agora: int = 0
    custo_usd: float = 0.0
    chamadas: int = 0
    destaques: list[dict[str, str]] = []


class FluxoOut(BaseModel):
    status: str
    modo: str | None
    ao_vivo: bool
    total: int
    concluidos: int
    custo_usd: float
    caixas: dict[str, CaixaResumo]
    resultados: dict[str, int]
    # Caixa → nome do modelo de IA usado nesta auditoria (ou o atual, se ainda não começou).
    modelos: dict[str, str] = {}


CAIXA_AGENTE = {
    "arrumador": ("abreviacoes", ""),
    "identificador": ("identificador", "modelo_principal"),
    "segundo_parecer": ("segundo_parecer", "modelo_escalonamento"),
    "navegador": ("navegador", "modelo_principal"),
    "jurista": ("jurista", "modelo_investigacao"),
    "leitor": ("leitor_fatos", "modelo_fatos"),
}


def _modelos_da_auditoria(conf: dict[str, Any]) -> dict[str, str]:
    atuais = catalogo_ia.agentes_configurados()
    infos = catalogo_ia.modelos()
    congelados = conf.get("modelos") or {}
    saida = {}
    for caixa, (agente, legado) in CAIXA_AGENTE.items():
        m = congelados.get(agente) or (conf.get(legado) if legado else None) or atuais[agente]["modelo"]
        saida[caixa] = infos[m].nome if m in infos else m
    return saida


def _n(v: Any) -> str:
    return f"{int(v or 0):,}".replace(",", ".")


@router.get("/auditorias/{audit_id}/fluxo", response_model=FluxoOut)
async def fluxo_auditoria(audit_id: uuid.UUID, principal: Ver, session: SessionDep) -> FluxoOut:
    """Quantos itens passaram por cada agente, quantos estão lá agora e quanto cada um custou."""
    a = await _carregar_auditoria(session, principal, audit_id)
    p = {"a": audit_id}
    s = (
        (
            await session.execute(
                text(
                    """
SELECT
  count(*) FILTER (WHERE NOT ignorado) AS total,
  count(*) FILTER (WHERE ignorado) AS ignorados,
  count(*) FILTER (WHERE NOT ignorado AND status NOT IN ('pendente','processando')) AS concluidos,
  count(*) FILTER (WHERE 'BASE_REFERENCIA_INCOMPLETA' = ANY(motivos)) AS base_incompleta,
  count(*) FILTER (WHERE origem = 'memoria_aprovada') AS memoria,
  count(*) FILTER (WHERE identidade->>'sem_ia' = 'true') AS sem_ia,
  count(*) FILTER (WHERE julgamento <> '{}'::jsonb) AS identificados,
  count(*) FILTER (WHERE escalonamento <> '{}'::jsonb) AS escalados,
  count(*) FILTER (WHERE thesis_id IS NOT NULL) AS com_tese,
  count(*) FILTER (WHERE jsonb_array_length(perguntas) > 0) AS com_perguntas,
  count(*) FILTER (WHERE identidade->>'situacao' = 'confirmado') AS confirmados,
  count(*) FILTER (WHERE identidade->>'situacao' = 'corrigido') AS corrigidos,
  count(*) FILTER (WHERE identidade->>'situacao' = 'sugerido') AS sugeridos,
  count(*) FILTER (WHERE identidade->>'situacao' = 'indefinido') AS indefinidos,
  count(*) FILTER (WHERE coalesce(estrutura->'sugestoes_fatos', '{}'::jsonb) <> '{}'::jsonb) AS com_sugestoes,
  count(*) FILTER (WHERE aprovado_automaticamente) AS auto,
  count(*) FILTER (WHERE identidade ? 'arvore') AS navegados,
  count(*) FILTER (WHERE identidade->'arvore'->>'codigo' IS NOT NULL) AS navegados_com_codigo,
  count(*) FILTER (WHERE coalesce(estrutura->'codigo_atual', 'null'::jsonb) = 'null'::jsonb) AS sem_codigo_erp,
  count(*) FILTER (WHERE estrutura->'codigo_atual'->>'existe' = 'false') AS codigo_erp_inexistente
FROM audit_items WHERE audit_id = :a
"""
                ),
                p,
            )
        )
        .mappings()
        .one()
    )
    teses = (
        (
            await session.execute(
                text(
                    "SELECT count(DISTINCT t.id) FILTER (WHERE t.audit_id = :a) AS novas, "
                    "count(DISTINCT t.id) FILTER (WHERE t.audit_id IS DISTINCT FROM :a) AS reaproveitadas "
                    "FROM audit_items i JOIN tax_theses t ON t.id = i.thesis_id WHERE i.audit_id = :a"
                ),
                p,
            )
        )
        .mappings()
        .one()
    )
    reuso_ident = await session.scalar(
        text(
            "SELECT count(*) FROM audit_items i JOIN llm_calls c ON c.id::text = i.julgamento->>'_call_id' "
            "WHERE i.audit_id = :a AND c.item_id IS DISTINCT FROM i.id"
        ),
        p,
    )
    custos = {
        r.no: (float(r.custo), int(r.n))
        for r in await session.execute(
            text(
                "SELECT no, coalesce(sum(custo_usd),0) AS custo, count(*) AS n "
                "FROM llm_calls WHERE audit_id = :a GROUP BY no"
            ),
            p,
        )
    }
    gatilhos = {
        r.g: int(r.n)
        for r in await session.execute(
            text(
                "SELECT g, count(*) AS n FROM audit_items, "
                "jsonb_array_elements_text(coalesce(estrutura->'gatilhos_escalonamento','[]'::jsonb)) g "
                "WHERE audit_id = :a GROUP BY g ORDER BY 2 DESC"
            ),
            p,
        )
    }
    fatos_lidos = await session.scalar(
        text("SELECT count(*) FROM company_facts WHERE audit_id = :a AND origem = 'descricao'"), p
    )
    pend = (
        (
            await session.execute(
                text(
                    "SELECT count(*) FILTER (WHERE status = 'aberta') AS abertas, "
                    "count(*) FILTER (WHERE status <> 'aberta') AS respondidas FROM pendencias WHERE audit_id = :a"
                ),
                p,
            )
        )
        .mappings()
        .one()
    )
    arquivo = await session.get(UploadedFile, a.file_id) if a.file_id else None

    # Contagens frescas (os contadores da auditoria só são recalculados em alguns momentos).
    por_status: dict[str, int] = {}
    por_etapa: dict[str, int] = {}
    for r in await session.execute(
        text(
            "SELECT status, coalesce(nullif(etapa, ''), 'na_fila') AS etapa, count(*) AS n FROM audit_items "
            "WHERE audit_id = :a AND NOT ignorado GROUP BY 1, 2"
        ),
        p,
    ):
        por_status[r.status] = por_status.get(r.status, 0) + int(r.n)
        if r.status in ("pendente", "processando"):
            por_etapa[r.etapa] = por_etapa.get(r.etapa, 0) + int(r.n)
    agora: dict[str, int] = {}
    for etapa, n in por_etapa.items():
        cx = caminho.ETAPA_CAIXA.get(etapa) or ("distribuidor" if etapa in ("na_fila", "") else etapa)
        agora[cx] = agora.get(cx, 0) + int(n)
    ao_vivo = a.status in ("processando", "aguardando_lote")

    def custo(*nos: str) -> tuple[float, int]:
        return (round(sum(custos.get(n, (0, 0))[0] for n in nos), 6), sum(custos.get(n, (0, 0))[1] for n in nos))

    total, concl = int(s["total"]), int(s["concluidos"])
    probs = a.problemas_resumo or {}
    est = (a.estimativa or {}).get(a.modo or "tempo_real") or {}
    caixas: dict[str, CaixaResumo] = {}

    caixas["recepcionista"] = CaixaResumo(
        passaram=int(probs.get("total_linhas") or total),
        destaques=[
            {"rotulo": "Arquivo", "valor": arquivo.nome_original if arquivo else "—"},
            {"rotulo": "Linhas lidas", "valor": _n(probs.get("total_linhas") or total)},
            {"rotulo": "Colunas ligadas", "valor": _n(sum(1 for v in (a.mapeamento or {}).values() if v))},
        ],
    )
    top = sorted((probs.get("por_problema") or {}).items(), key=lambda kv: -kv[1])[:4]
    caixas["conferente"] = CaixaResumo(
        passaram=int(probs.get("total_linhas") or total),
        destaques=[
            {"rotulo": "Itens válidos", "valor": _n(probs.get("itens_validos"))},
            {"rotulo": "Com algum problema", "valor": _n(probs.get("com_problemas"))},
            {"rotulo": "Ignorados", "valor": _n(s["ignorados"])},
            *({"rotulo": (probs.get("descricoes") or {}).get(k, k), "valor": _n(v)} for k, v in top),
        ],
    )
    caixas["orcamentista"] = CaixaResumo(
        passaram=total,
        destaques=[
            {"rotulo": "Custo estimado", "valor": f"US$ {float(est.get('custo_usd_estimado') or 0):.2f}"},
            {"rotulo": "Famílias previstas", "valor": _n(est.get("familias_estimadas"))},
            {"rotulo": "Já na memória", "valor": _n(probs.get("provaveis_da_memoria"))},
        ],
    )
    caixas["voce"] = CaixaResumo(
        passaram=total,
        destaques=[
            {"rotulo": "Modo escolhido", "valor": "Em lote" if a.modo == "lote" else "Tempo real"},
            {"rotulo": "Iniciada em", "valor": a.iniciado_em.strftime("%d/%m/%Y %H:%M") if a.iniciado_em else "—"},
        ],
    )
    caixas["distribuidor"] = CaixaResumo(
        passaram=total,
        agora=agora.get("distribuidor", 0),
        destaques=[
            {"rotulo": "Pacotes de 10 itens", "valor": _n(math.ceil(total / 10))},
            {"rotulo": "Na fila agora", "valor": _n(agora.get("distribuidor", 0))},
        ],
    )
    c_arr = custo("expandir_abreviacoes")
    caixas["arrumador"] = CaixaResumo(
        passaram=concl,
        agora=agora.get("arrumador", 0),
        custo_usd=c_arr[0],
        chamadas=c_arr[1],
        destaques=[{"rotulo": "Pediram ajuda à IA para abreviações", "valor": _n(c_arr[1])}],
    )
    caixas["fiscal"] = CaixaResumo(
        passaram=concl,
        agora=agora.get("fiscal", 0),
        destaques=[
            {"rotulo": "Sem NCM no ERP", "valor": _n(s["sem_codigo_erp"])},
            {"rotulo": "NCM do ERP inexistente", "valor": _n(s["codigo_erp_inexistente"])},
            {"rotulo": "Base oficial incompleta", "valor": _n(s["base_incompleta"])},
        ],
    )
    arquivista = concl - int(s["base_incompleta"])
    caixas["arquivista"] = CaixaResumo(
        passaram=arquivista,
        agora=agora.get("arquivista", 0),
        destaques=[
            {"rotulo": "Achou no caderno (pula a identificação)", "valor": _n(s["memoria"])},
            {"rotulo": "Não achou", "valor": _n(arquivista - int(s["memoria"]))},
        ],
    )
    pesq = arquivista - int(s["memoria"])
    caixas["pesquisador"] = CaixaResumo(
        passaram=pesq,
        agora=agora.get("pesquisador", 0),
        destaques=[
            {"rotulo": "Atalho: confirmados sem IA", "valor": _n(s["sem_ia"])},
            {
                "rotulo": "Sem nenhuma alternativa",
                "valor": _n(max(0, pesq - int(s["sem_ia"]) - int(s["identificados"]))),
            },
        ],
    )
    c_id = custo("julgar_coerencia")
    caixas["identificador"] = CaixaResumo(
        passaram=int(s["identificados"]),
        agora=agora.get("identificador", 0),
        custo_usd=c_id[0],
        chamadas=c_id[1],
        destaques=[
            {"rotulo": "NCM do ERP confirmado", "valor": _n(s["confirmados"])},
            {"rotulo": "NCM corrigido", "valor": _n(s["corrigidos"])},
            {"rotulo": "NCM sugerido (ERP sem código)", "valor": _n(s["sugeridos"])},
            {"rotulo": "Não conseguiu identificar", "valor": _n(s["indefinidos"])},
            {"rotulo": "Respostas reaproveitadas (sem custo)", "valor": _n(reuso_ident)},
        ],
    )
    c_esc = custo("escalar")
    caixas["segundo_parecer"] = CaixaResumo(
        passaram=int(s["escalados"]),
        agora=agora.get("segundo_parecer", 0),
        custo_usd=c_esc[0],
        chamadas=c_esc[1],
        destaques=[{"rotulo": f"Alarme: {caminho.ALARMES.get(g, g)}", "valor": _n(n)} for g, n in gatilhos.items()],
    )
    c_nav = custo("navegar_arvore")
    caixas["navegador"] = CaixaResumo(
        passaram=int(s["navegados"]),
        agora=agora.get("navegador", 0),
        custo_usd=c_nav[0],
        chamadas=c_nav[1],
        destaques=[
            {"rotulo": "Acharam um NCM sugerido na tabela", "valor": _n(s["navegados_com_codigo"])},
            {"rotulo": "Ficaram sem código", "valor": _n(int(s["navegados"]) - int(s["navegados_com_codigo"]))},
        ],
    )
    c_jur = custo("investigar_enquadramento")
    caixas["jurista"] = CaixaResumo(
        passaram=int(s["com_tese"]),
        agora=agora.get("jurista", 0),
        custo_usd=c_jur[0],
        chamadas=c_jur[1],
        destaques=[
            {"rotulo": "Famílias estudadas agora", "valor": _n(teses["novas"])},
            {"rotulo": "Pareceres reaproveitados (sem custo)", "valor": _n(teses["reaproveitadas"])},
        ],
    )
    c_lei = custo("extrair_fatos")
    caixas["leitor"] = CaixaResumo(
        passaram=int(s["com_tese"]),
        agora=agora.get("leitor", 0),
        custo_usd=c_lei[0],
        chamadas=c_lei[1],
        destaques=[
            {"rotulo": "Chamaram a IA", "valor": _n(c_lei[1])},
            {"rotulo": "Fatos lidos na descrição", "valor": _n(fatos_lidos)},
            {"rotulo": "Itens com palpites (só sugestão)", "valor": _n(s["com_sugestoes"])},
        ],
    )
    caixas["juiz"] = CaixaResumo(
        passaram=concl,
        destaques=[
            {"rotulo": "Aprovados automaticamente", "valor": _n(s["auto"])},
            *(
                {"rotulo": caminho.ROTULO_STATUS.get(k, k), "valor": _n(v)}
                for k, v in por_status.items()
                if k in caminho.STATUS_FINAIS
            ),
        ],
    )
    caixas["secretario"] = CaixaResumo(
        passaram=int(s["com_perguntas"]),
        destaques=[
            {"rotulo": "Perguntas abertas", "valor": _n(pend["abertas"])},
            {"rotulo": "Perguntas respondidas", "valor": _n(pend["respondidas"])},
            {"rotulo": "Itens esperando resposta", "valor": _n(s["com_perguntas"])},
        ],
    )
    if agora.get("aguardando_lote"):
        caixas["distribuidor"].destaques.append(
            {"rotulo": "Esperando o lote da IA", "valor": _n(agora["aguardando_lote"])}
        )
    return FluxoOut(
        status=a.status,
        modo=a.modo,
        ao_vivo=ao_vivo,
        total=total,
        concluidos=concl,
        custo_usd=float(a.custo_usd or 0),
        caixas=caixas,
        resultados={k: int(v) for k, v in por_status.items()},
        modelos=await run_in_threadpool(_modelos_da_auditoria, a.configuracao or {}),
    )
