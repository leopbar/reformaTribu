"""Revisão humana dos itens: aprovar, editar, responder, rejeitar, desfazer, lote e reprocessar."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.audits import _carregar_auditoria
from app.core.audit_trail import Acao, registrar
from app.core.deps import Principal, SessionDep, exigir
from app.core.errors import Conflito, NaoEncontrado
from app.core.rbac import Perm
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
    await _item(session, principal, item_id)
    r = await session.run_sync(lambda s: service.aprovar(s, item_id, _revisor(principal), dados.comentario))
    i = await _item(session, principal, item_id)
    await registrar(
        session,
        principal,
        Acao.APROVACAO,
        entidade="item",
        entidade_id=item_id,
        detalhes={"codigo": i.final_codigo, "cclasstrib": i.final_cclasstrib},
    )
    return _out(i, "Aprovado", r.id)


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
