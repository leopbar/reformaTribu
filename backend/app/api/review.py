"""Revisão humana dos itens: aprovar, editar, responder, rejeitar, desfazer, lote e reprocessar."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.audits import _carregar_auditoria
from app.core.audit_trail import Acao, registrar
from app.core.deps import Principal, SessionDep, exigir
from app.core.errors import Conflito, NaoEncontrado
from app.core.rbac import Perm
from app.llm import catalogo
from app.models import Audit, AuditItem
from app.models.enums import StatusAuditoria, StatusItem, StatusRevisao
from app.review import service
from app.worker.celery_app import celery_app

router = APIRouter(tags=["revisão"])
Revisar = Annotated[Principal, Depends(exigir(Perm.REVISAR))]


class DecisaoOut(BaseModel):
    item_id: uuid.UUID
    revisao_status: str
    status: str
    codigo_sugerido: str | None
    tipo_codigo: str | None
    cst: str | None
    cclasstrib: str | None
    dispositivo_legal: str | None
    perguntas: list[dict[str, Any]]
    motivos: list[str]
    review_id: uuid.UUID | None = None
    # A mesma decisão aplicada na hora aos itens iguais da auditoria (ADR 0029): desfeita pelo lote.
    lote_id: uuid.UUID | None = None
    iguais: int = 0
    mensagem: str


def _out(i: AuditItem, mensagem: str, review_id: uuid.UUID | None = None) -> DecisaoOut:
    return DecisaoOut(
        item_id=i.id,
        revisao_status=i.revisao_status,
        status=i.status,
        codigo_sugerido=i.final_codigo or i.codigo_sugerido,
        tipo_codigo=i.final_tipo_codigo or i.tipo_codigo_sugerido,
        cst=i.final_cst or i.cst_sugerido,
        cclasstrib=i.final_cclasstrib or i.cclasstrib_sugerido,
        dispositivo_legal=i.final_dispositivo or i.dispositivo_legal,
        perguntas=i.perguntas or [],
        motivos=i.motivos or [],
        review_id=review_id,
        mensagem=mensagem,
    )


async def _item(session: Any, principal: Principal, item_id: uuid.UUID) -> AuditItem:
    i = await session.get(AuditItem, item_id)
    if i is None:
        raise NaoEncontrado("Item não encontrado.")
    await _carregar_auditoria(session, principal, i.audit_id)
    return i  # type: ignore[no-any-return]


def _revisor(p: Principal) -> service.Revisor:
    return service.Revisor(user_id=p.user_id, email=p.email)


class ComentarioIn(BaseModel):
    comentario: str | None = Field(None, max_length=2000)


@router.post("/itens/{item_id}/aprovar", response_model=DecisaoOut)
async def aprovar(item_id: uuid.UUID, dados: ComentarioIn, principal: Revisar, session: SessionDep) -> DecisaoOut:
    """Aprova o item e, na mesma auditoria, os itens pendentes que pedem a mesma decisão (ADR 0029)."""
    await _item(session, principal, item_id)
    r, lote_id, iguais = await session.run_sync(
        lambda s: service.aprovar_e_aplicar_aos_iguais(s, item_id, _revisor(principal), dados.comentario)
    )
    i = await _item(session, principal, item_id)
    await registrar(
        session,
        principal,
        Acao.APROVACAO,
        entidade="item",
        entidade_id=item_id,
        detalhes={
            "codigo": i.final_codigo,
            "cclasstrib": i.final_cclasstrib,
            **({"iguais": iguais, "lote_id": str(lote_id)} if lote_id else {}),
        },
    )
    if iguais:
        await _contadores(i.audit_id, i.org_id, session)
    msg = "Aprovado" + (f" · a mesma decisão valeu para {iguais} item(ns) iguais" if iguais else "")
    out = _out(i, msg, r.id)
    out.lote_id, out.iguais = lote_id, iguais
    return out


async def _contadores(audit_id: uuid.UUID, org_id: uuid.UUID, session: Any) -> None:
    await session.commit()
    from app.audits.processing import atualizar_contadores

    await run_in_threadpool(atualizar_contadores, audit_id, org_id)


class EdicaoIn(BaseModel):
    tipo_codigo: str | None = Field(None, pattern="^(ncm|nbs)$")
    codigo: str | None = Field(None, pattern=r"^\d{8,9}$")
    respostas: dict[str, str] = Field(default_factory=dict)
    cst: str | None = Field(None, pattern=r"^\d{3}$")
    cclasstrib: str | None = Field(None, pattern=r"^\d{6}$")
    comentario: str | None = Field(None, max_length=2000)
    aprovar: bool = False


@router.post("/itens/{item_id}/editar", response_model=DecisaoOut)
async def editar(item_id: uuid.UUID, dados: EdicaoIn, principal: Revisar, session: SessionDep) -> DecisaoOut:
    await _item(session, principal, item_id)

    def _f(s: Session) -> tuple[AuditItem, bool]:
        return service.editar(
            s,
            item_id,
            _revisor(principal),
            tipo_codigo=dados.tipo_codigo,
            codigo=dados.codigo,
            respostas=dados.respostas or None,
            cst=dados.cst,
            cclasstrib=dados.cclasstrib,
            comentario=dados.comentario,
            aprovar_em_seguida=dados.aprovar,
        )

    i, reprocessar_item = await session.run_sync(_f)
    if reprocessar_item:
        a = await session.get(Audit, i.audit_id)
        assert a is not None
        if a.status == StatusAuditoria.CONCLUIDA:
            a.status = StatusAuditoria.PROCESSANDO
        a.modo = "tempo_real"
        await session.commit()
        celery_app.send_task(
            "auditoria.processar_itens", args=[str(a.id), str(a.org_id), [str(item_id)]], queue="pipeline"
        )
    await registrar(
        session,
        principal,
        Acao.EDICAO,
        entidade="item",
        entidade_id=item_id,
        detalhes={
            "codigo": dados.codigo,
            "respostas": dados.respostas,
            "cclasstrib": dados.cclasstrib,
            "aprovado": dados.aprovar,
        },
    )
    msg = (
        "Código corrigido: o item será reanalisado"
        if reprocessar_item
        else ("Aprovado" if dados.aprovar else "Alteração salva")
    )
    return _out(i, msg)


class RejeicaoIn(BaseModel):
    comentario: str = Field(min_length=3, max_length=2000)


@router.post("/itens/{item_id}/rejeitar", response_model=DecisaoOut)
async def rejeitar(item_id: uuid.UUID, dados: RejeicaoIn, principal: Revisar, session: SessionDep) -> DecisaoOut:
    await _item(session, principal, item_id)
    r = await session.run_sync(lambda s: service.rejeitar(s, item_id, _revisor(principal), dados.comentario))
    await registrar(session, principal, Acao.REJEICAO, entidade="item", entidade_id=item_id)
    return _out(await _item(session, principal, item_id), "Rejeitado", r.id)


@router.post("/itens/{item_id}/desfazer", response_model=DecisaoOut)
async def desfazer(item_id: uuid.UUID, principal: Revisar, session: SessionDep) -> DecisaoOut:
    await _item(session, principal, item_id)
    r = await session.run_sync(lambda s: service.desfazer(s, item_id, _revisor(principal)))
    await registrar(session, principal, Acao.DESFAZER, entidade="item", entidade_id=item_id)
    return _out(await _item(session, principal, item_id), "Decisão desfeita", r.id)


@router.post("/itens/{item_id}/reprocessar", response_model=DecisaoOut)
async def reprocessar(item_id: uuid.UUID, principal: Revisar, session: SessionDep) -> DecisaoOut:
    i = await _item(session, principal, item_id)
    a = await session.get(Audit, i.audit_id)
    if i.revisao_status == StatusRevisao.APROVADO and not i.aprovado_automaticamente:
        raise Conflito("Desfaça a aprovação antes de reprocessar o item.")
    if i.revisao_status == StatusRevisao.APROVADO:
        i.revisao_status = StatusRevisao.PENDENTE
    if a is None or a.status not in (StatusAuditoria.CONCLUIDA, StatusAuditoria.PROCESSANDO):
        raise Conflito("Só é possível reprocessar itens de auditorias em andamento ou concluídas.")
    i.tentativa += 1
    i.status, i.etapa, i.motivos, i.perguntas = StatusItem.PENDENTE, None, [], []
    i.aprovado_automaticamente = False
    if a.status == StatusAuditoria.CONCLUIDA:
        # Auditoria encerrada: a reanálise usa os modelos escolhidos hoje em "Modelos de IA".
        agentes = await run_in_threadpool(catalogo.agentes_configurados)
        a.configuracao = {
            **(a.configuracao or {}),
            "modelos": {k: v["modelo"] for k, v in agentes.items()},
            "esforcos": {k: v["esforco"] for k, v in agentes.items()},
        }
        a.status = StatusAuditoria.PROCESSANDO
    # Reprocessamentos individuais usam sempre a API em tempo real.
    a.modo = "tempo_real"
    await registrar(
        session,
        principal,
        Acao.ITEM_REPROCESSADO,
        entidade="item",
        entidade_id=item_id,
        detalhes={"tentativa": i.tentativa},
    )
    await session.commit()
    celery_app.send_task("auditoria.processar_itens", args=[str(a.id), str(a.org_id), [str(item_id)]], queue="pipeline")
    return _out(i, "Reprocessamento iniciado")


class ReprocessarLoteIn(BaseModel):
    item_ids: list[uuid.UUID] = Field(min_length=1, max_length=5000)
    confirmar: bool = False  # False = só prévia (quantos itens e custo estimado)


class ReprocessarLoteOut(BaseModel):
    reprocessaveis: int
    mantidos_aprovados: int
    em_andamento: int
    custo_estimado_usd: float
    enviado: bool
    mensagem: str


@router.post("/auditorias/{audit_id}/reprocessar-lote", response_model=ReprocessarLoteOut)
async def reprocessar_lote(
    audit_id: uuid.UUID, dados: ReprocessarLoteIn, principal: Revisar, session: SessionDep
) -> ReprocessarLoteOut:
    """Reanalisa vários itens de uma vez (os da lista filtrada), com os modelos escolhidos hoje.

    Itens decididos por uma pessoa (aprovados ou rejeitados) e itens ainda em processamento ficam de fora."""
    from sqlalchemy import select

    from app.audits.processing import enfileirar_itens
    from app.ingest import estimate

    a = await _carregar_auditoria(session, principal, audit_id)
    if a.status not in (StatusAuditoria.CONCLUIDA, StatusAuditoria.PROCESSANDO):
        raise Conflito("Só é possível reanalisar itens de auditorias em andamento ou concluídas.")
    itens = list(
        await session.scalars(
            select(AuditItem).where(
                AuditItem.audit_id == audit_id, AuditItem.id.in_(dados.item_ids), AuditItem.ignorado.is_(False)
            )
        )
    )
    decididos = [
        i
        for i in itens
        if i.revisao_status == StatusRevisao.REJEITADO
        or (i.revisao_status == StatusRevisao.APROVADO and not i.aprovado_automaticamente)
    ]
    rodando = [i for i in itens if i.status in (StatusItem.PENDENTE, StatusItem.PROCESSANDO)]
    fora = {i.id for i in decididos} | {i.id for i in rodando}
    alvo = [i for i in itens if i.id not in fora]
    sem_codigo = sum(1 for i in alvo if not (i.identidade or {}).get("codigo"))
    previsao = {"itens_com_ia": len(alvo), "familias_novas": 0, "sem_codigo_valido": sem_codigo}
    est = await run_in_threadpool(lambda: estimate.estimar(previsao, 0.4, lote=False))
    custo = float(est["custo_usd_estimado"])
    resumo = f"{len(alvo)} item(ns) para reanalisar"
    if decididos:
        resumo += f"; {len(decididos)} decidido(s) por pessoas ficam como estão"
    if rodando:
        resumo += f"; {len(rodando)} já em processamento"
    if not dados.confirmar or not alvo:
        return ReprocessarLoteOut(
            reprocessaveis=len(alvo),
            mantidos_aprovados=len(decididos),
            em_andamento=len(rodando),
            custo_estimado_usd=custo,
            enviado=False,
            mensagem=resumo + ".",
        )
    for i in alvo:
        if i.revisao_status == StatusRevisao.APROVADO:
            i.revisao_status = StatusRevisao.PENDENTE
        i.tentativa += 1
        i.status, i.etapa, i.motivos, i.perguntas = StatusItem.PENDENTE, None, [], []
        i.aprovado_automaticamente = False
    if a.status == StatusAuditoria.CONCLUIDA:
        agentes = await run_in_threadpool(catalogo.agentes_configurados)
        a.configuracao = {
            **(a.configuracao or {}),
            "modelos": {k: v["modelo"] for k, v in agentes.items()},
            "esforcos": {k: v["esforco"] for k, v in agentes.items()},
        }
        a.status = StatusAuditoria.PROCESSANDO
    a.modo = "tempo_real"
    await registrar(
        session,
        principal,
        Acao.ITEM_REPROCESSADO,
        entidade="auditoria",
        entidade_id=audit_id,
        detalhes={"itens": len(alvo), "custo_estimado_usd": custo},
    )
    await session.commit()
    enfileirar_itens(a.id, a.org_id, [i.id for i in alvo])
    return ReprocessarLoteOut(
        reprocessaveis=len(alvo),
        mantidos_aprovados=len(decididos),
        em_andamento=len(rodando),
        custo_estimado_usd=custo,
        enviado=True,
        mensagem=f"Reanálise iniciada: {resumo}.",
    )


# ================================================================================== lote ==
class LoteIn(BaseModel):
    status: list[str] | None = None
    confianca: list[str] | None = None
    motivos_excluir: list[str] | None = None
    item_ids: list[uuid.UUID] | None = None
    comentario: str | None = Field(None, max_length=2000)
    confirmar: bool = False
    total_esperado: int | None = None


class LoteOut(BaseModel):
    total: int
    aprovados: int
    lote_id: uuid.UUID | None
    amostra: list[dict[str, Any]]
    mensagem: str


@router.post("/auditorias/{audit_id}/aprovar-lote", response_model=LoteOut)
async def aprovar_lote(audit_id: uuid.UUID, dados: LoteIn, principal: Revisar, session: SessionDep) -> LoteOut:
    await _carregar_auditoria(session, principal, audit_id)
    filtro = service.FiltroLote(
        status=dados.status,
        confianca=dados.confianca,
        motivos_excluir=dados.motivos_excluir,
        item_ids=dados.item_ids,
    )
    itens = await session.run_sync(lambda s: service.itens_do_lote(s, audit_id, filtro))
    amostra = [
        {
            "linha": i.linha,
            "descricao": i.descricao,
            "codigo": i.codigo_sugerido,
            "cclasstrib": i.cclasstrib_sugerido,
            "confianca": i.confianca_global,
        }
        for i in itens[:10]
    ]
    if not dados.confirmar:
        return LoteOut(
            total=len(itens),
            aprovados=0,
            lote_id=None,
            amostra=amostra,
            mensagem=f"{len(itens)} itens serão aprovados. Confirme para continuar.",
        )
    if dados.total_esperado is not None and dados.total_esperado != len(itens):
        raise Conflito("A seleção mudou desde a confirmação. Revise a quantidade e confirme novamente.")
    lote_id, n = await session.run_sync(
        lambda s: service.aprovar_lote(s, audit_id, _revisor(principal), filtro, dados.comentario)
    )
    await registrar(
        session,
        principal,
        Acao.APROVACAO_LOTE,
        entidade="auditoria",
        entidade_id=audit_id,
        detalhes={
            "lote_id": str(lote_id),
            "itens": n,
            "filtro": dados.model_dump(mode="json", exclude={"comentario", "confirmar", "item_ids"}),
        },
    )
    return LoteOut(total=len(itens), aprovados=n, lote_id=lote_id, amostra=amostra, mensagem=f"{n} itens aprovados")


# ======================================================================= revisão por grupo (ADR 0029) ==
class GrupoRevisaoOut(BaseModel):
    chave: str
    status: str
    tipo_codigo: str | None
    codigo: str | None
    codigo_formatado: str | None
    descricao_oficial: str | None
    cst: str | None
    cclasstrib: str | None
    imposto_seletivo: str | None
    motivo: str
    itens: int
    item_ids: list[uuid.UUID]
    amostra: list[str]


@router.get("/auditorias/{audit_id}/revisao/grupos", response_model=list[GrupoRevisaoOut])
async def grupos_revisao(audit_id: uuid.UUID, principal: Revisar, session: SessionDep) -> list[GrupoRevisaoOut]:
    """Itens pendentes de revisão agrupados pela decisão que pedem: uma decisão resolve o grupo inteiro."""
    await _carregar_auditoria(session, principal, audit_id)
    grupos = await session.run_sync(lambda s: service.grupos_de_revisao(s, audit_id))
    return [GrupoRevisaoOut(**{**g.__dict__, "itens": len(g.item_ids)}) for g in grupos]


class AjusteCadastroOut(BaseModel):
    item_id: uuid.UUID
    linha: int
    descricao: str
    tipo_codigo: str
    erp: str | None
    erp_formatado: str | None
    sugerido: str | None
    sugerido_formatado: str | None
    alternativas: list[str]
    cclasstrib: str | None
    texto: str
    status: str | None
    revisao_status: str


@router.get("/auditorias/{audit_id}/ajustes-cadastro", response_model=list[AjusteCadastroOut])
async def ajustes_cadastro(
    audit_id: uuid.UUID, principal: Revisar, session: SessionDep, status: str | None = "pendente"
) -> list[AjusteCadastroOut]:
    """NCM/NBS a confirmar no cadastro sem mudar o IBS/CBS (ADR 0029). `status=todos` lista também os decididos."""
    from sqlalchemy import select

    from app.core.codes import formatar_codigo

    await _carregar_auditoria(session, principal, audit_id)
    q = select(AuditItem).where(
        AuditItem.audit_id == audit_id, AuditItem.ignorado.is_(False), AuditItem.ajuste_cadastro_status.is_not(None)
    )
    if status and status != "todos":
        q = q.where(AuditItem.ajuste_cadastro_status == status)
    saida = []
    for i in await session.scalars(q.order_by(AuditItem.linha)):
        a = i.ajuste_cadastro or {}
        tipo = a.get("tipo_codigo") or "ncm"
        saida.append(
            AjusteCadastroOut(
                item_id=i.id,
                linha=i.linha,
                descricao=i.descricao,
                tipo_codigo=tipo,
                erp=a.get("erp"),
                erp_formatado=formatar_codigo(tipo, a["erp"]) if a.get("erp") else None,
                sugerido=a.get("sugerido"),
                sugerido_formatado=formatar_codigo(tipo, a["sugerido"]) if a.get("sugerido") else None,
                alternativas=[formatar_codigo(tipo, c) for c in a.get("alternativas") or []],
                cclasstrib=i.final_cclasstrib or i.cclasstrib_sugerido,
                texto=a.get("texto") or "",
                status=i.ajuste_cadastro_status,
                revisao_status=i.revisao_status,
            )
        )
    return saida


class AjusteCadastroIn(BaseModel):
    item_ids: list[uuid.UUID] = Field(min_length=1, max_length=50000)
    acao: str = Field(pattern="^(aceitar|manter|reabrir)$")
    comentario: str | None = Field(None, max_length=2000)


class AjusteCadastroResultado(BaseModel):
    alterados: int
    mensagem: str


@router.post("/auditorias/{audit_id}/ajustes-cadastro", response_model=AjusteCadastroResultado)
async def decidir_ajustes_cadastro(
    audit_id: uuid.UUID, dados: AjusteCadastroIn, principal: Revisar, session: SessionDep
) -> AjusteCadastroResultado:
    """Aceita o código sugerido, mantém o do ERP ou reabre a sugestão, para vários itens de uma vez."""
    a = await _carregar_auditoria(session, principal, audit_id)
    n = await session.run_sync(
        lambda s: service.decidir_ajustes_cadastro(
            s, audit_id, dados.item_ids, dados.acao, _revisor(principal), dados.comentario
        )
    )
    await registrar(
        session,
        principal,
        Acao.EDICAO,
        entidade="auditoria",
        entidade_id=audit_id,
        detalhes={"ajustes_cadastro": dados.acao, "itens": n},
    )
    await _contadores(audit_id, a.org_id, session)
    rotulo = {"aceitar": "sugestão aceita", "manter": "NCM do ERP mantido", "reabrir": "reaberto"}[dados.acao]
    return AjusteCadastroResultado(alterados=n, mensagem=f"{n} item(ns): {rotulo}.")


# ========================================================== reaplicar as regras atuais (sem IA) ==
class ReaplicarIn(BaseModel):
    reanalisar_falhas: bool = False  # itens que esbarraram na plataforma de IA voltam para a fila


class ReaplicarOut(BaseModel):
    reaplicados: int
    mantidos: int
    falhas_de_ia: int
    enviados_para_reanalise: int
    em_segundo_plano: bool
    mensagem: str


LIMITE_REAPLICAR_IMEDIATO = 400


@router.post("/auditorias/{audit_id}/reaplicar", response_model=ReaplicarOut)
async def reaplicar(audit_id: uuid.UUID, dados: ReaplicarIn, principal: Revisar, session: SessionDep) -> ReaplicarOut:
    """Refaz a decisão dos itens com as regras atuais, a partir das respostas da IA já gravadas (ADR 0029).
    Não chama a IA nem gera custo; decisões de pessoas ficam como estão."""
    from sqlalchemy import select

    from app.audits.processing import enfileirar_itens
    from app.evals.replay import falha_de_infraestrutura

    a = await _carregar_auditoria(session, principal, audit_id)
    if a.status not in (StatusAuditoria.CONCLUIDA, StatusAuditoria.PAUSADA_IA):
        raise Conflito("Só é possível reaplicar as regras em auditorias concluídas.")
    ids = list(
        await session.scalars(select(AuditItem.id).where(AuditItem.audit_id == audit_id, AuditItem.ignorado.is_(False)))
    )
    if len(ids) > LIMITE_REAPLICAR_IMEDIATO:
        await session.commit()
        celery_app.send_task(
            "analise.reaplicar_auditoria",
            args=[str(audit_id), str(a.org_id), dados.reanalisar_falhas],
            queue="pipeline",
        )
        return ReaplicarOut(
            reaplicados=0,
            mantidos=0,
            falhas_de_ia=0,
            enviados_para_reanalise=0,
            em_segundo_plano=True,
            mensagem=f"{len(ids)} itens serão reavaliados em segundo plano com as regras atuais (sem IA).",
        )

    def _f(s: Any) -> tuple[int, int, list[uuid.UUID]]:
        from app.analise.aplicacao import reaplicar_item

        feitos = mantidos = 0
        falhas: list[uuid.UUID] = []
        for item in s.scalars(select(AuditItem).where(AuditItem.id.in_(ids))):
            if falha_de_infraestrutura(s, item) and item.revisao_status != StatusRevisao.APROVADO:
                falhas.append(item.id)
                continue
            r = reaplicar_item(s, item)
            if r == "reaplicado":
                feitos += 1
            elif r == "reanalisar":
                falhas.append(item.id)  # parecer refeito: precisa levantar os fatos de novo (IA)
            else:
                mantidos += 1
        return feitos, mantidos, falhas

    feitos, mantidos, falhas = await session.run_sync(_f)
    enviados = 0
    if dados.reanalisar_falhas and falhas:
        for i in await session.scalars(select(AuditItem).where(AuditItem.id.in_(falhas))):
            i.tentativa += 1
            i.status, i.etapa, i.motivos, i.perguntas = StatusItem.PENDENTE, None, [], []
            i.aprovado_automaticamente = False
            if i.revisao_status == StatusRevisao.APROVADO:
                i.revisao_status = StatusRevisao.PENDENTE
        a.status, a.modo = StatusAuditoria.PROCESSANDO, "tempo_real"
        enviados = len(falhas)
    await registrar(
        session,
        principal,
        Acao.ITEM_REPROCESSADO,
        entidade="auditoria",
        entidade_id=audit_id,
        detalhes={"reaplicar_regras": feitos, "falhas_de_ia": len(falhas), "reanalise": enviados},
    )
    await _contadores(audit_id, a.org_id, session)
    if enviados:
        enfileirar_itens(a.id, a.org_id, falhas)
    msg = f"{feitos} item(ns) reavaliados com as regras atuais, sem IA."
    if mantidos:
        msg += f" {mantidos} ficaram como estavam (decisão de pessoa que as regras não confirmam, ou sem análise)."
    if falhas:
        msg += f" {len(falhas)} precisam da IA (falha da plataforma ou parecer refeito) e " + (
            "voltaram para a fila." if enviados else "podem ser reanalisados agora."
        )
    return ReaplicarOut(
        reaplicados=feitos,
        mantidos=mantidos,
        falhas_de_ia=len(falhas),
        enviados_para_reanalise=enviados,
        em_segundo_plano=False,
        mensagem=msg,
    )


@router.post("/auditorias/{audit_id}/lotes/{lote_id}/desfazer", response_model=LoteOut)
async def desfazer_lote(audit_id: uuid.UUID, lote_id: uuid.UUID, principal: Revisar, session: SessionDep) -> LoteOut:
    await _carregar_auditoria(session, principal, audit_id)
    n = await session.run_sync(lambda s: service.desfazer_lote(s, audit_id, lote_id, _revisor(principal)))
    await registrar(
        session,
        principal,
        Acao.DESFAZER,
        entidade="auditoria",
        entidade_id=audit_id,
        detalhes={"lote_id": str(lote_id), "itens": n},
    )
    return LoteOut(total=n, aprovados=0, lote_id=lote_id, amostra=[], mensagem=f"Aprovação desfeita em {n} itens")
