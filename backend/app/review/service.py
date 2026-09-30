"""Revisão humana: aprovar, corrigir o código, informar fatos, definir o enquadramento manualmente,
rejeitar, desfazer e aprovar em lote. Toda decisão gera um registro imutável em item_reviews, versiona
o perfil tributário e alimenta a memória aprovada da empresa."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, select, true, update
from sqlalchemy.orm import Session

from app.analise import aplicacao
from app.analise import fatos as fatos_mod
from app.core.errors import Conflito, NaoEncontrado
from app.ingest.cleaning import hash_descricao
from app.models import ApprovedMemory, Audit, AuditItem, CClassTribCode, ItemReview, RefSnapshot
from app.models.enums import (
    STATUS_REVISAVEIS,
    AcaoRevisao,
    EscopoFato,
    OrigemFato,
    StatusItem,
    StatusRevisao,
)
from app.reference.search import obter_no


@dataclass(frozen=True)
class Revisor:
    user_id: uuid.UUID
    email: str


CAMPOS_FOTO = (
    "status",
    "motivos",
    "perguntas",
    "tipo_codigo_sugerido",
    "codigo_sugerido",
    "cst_sugerido",
    "cclasstrib_sugerido",
    "regra_id",
    "tipo_tratamento",
    "dispositivo_legal",
    "atributos",
    "revisao_status",
    "final_tipo_codigo",
    "final_codigo",
    "final_cst",
    "final_cclasstrib",
    "final_regra_id",
    "final_dispositivo",
    "revisado_por",
    "revisado_em",
    "imposto_seletivo",
    "regras_consideradas",
    "hipotese",
    "conclusao",
    "nivel_revisao",
    "confianca_global",
    "aprovado_automaticamente",
    "is_situacao",
)


def foto(item: AuditItem) -> dict[str, Any]:
    d: dict[str, Any] = {}
    for c in CAMPOS_FOTO:
        v = getattr(item, c)
        if isinstance(v, uuid.UUID):
            v = str(v)
        elif isinstance(v, datetime):
            v = v.isoformat()
        elif isinstance(v, Decimal):
            v = float(v)
        d[c] = v
    return d


def restaurar(item: AuditItem, d: dict[str, Any]) -> None:
    for c in CAMPOS_FOTO:
        if c not in d:
            continue
        v = d[c]
        if c in ("regra_id", "final_regra_id", "revisado_por") and v:
            v = uuid.UUID(v)
        if c == "revisado_em" and v:
            v = datetime.fromisoformat(v)
        setattr(item, c, v)


def _carregar(session: Session, item_id: uuid.UUID) -> tuple[AuditItem, Audit]:
    item = session.get(AuditItem, item_id)
    if item is None:
        raise NaoEncontrado("Item não encontrado.")
    audit = session.get(Audit, item.audit_id)
    assert audit is not None
    return item, audit


def _registrar(
    session: Session,
    item: AuditItem,
    acao: str,
    antes: dict[str, Any],
    revisor: Revisor,
    comentario: str | None = None,
    lote_id: uuid.UUID | None = None,
    desfaz: uuid.UUID | None = None,
) -> ItemReview:
    r = ItemReview(
        org_id=item.org_id,
        audit_id=item.audit_id,
        item_id=item.id,
        acao=acao,
        antes=antes,
        depois=foto(item),
        comentario=comentario,
        lote_id=lote_id,
        desfaz_review_id=desfaz,
        user_id=revisor.user_id,
        user_email=revisor.email,
    )
    session.add(r)
    session.flush()
    return r


def _memoria(
    session: Session,
    item: AuditItem,
    audit: Audit,
    review: ItemReview,
    revisor: Revisor,
    *,
    tipo_codigo: str,
    codigo: str,
    cst: str | None,
    cclasstrib: str | None,
) -> None:
    h = hash_descricao(item.descricao_normalizada or item.descricao)
    session.execute(
        update(ApprovedMemory)
        .where(
            ApprovedMemory.company_id == item.company_id,
            ApprovedMemory.descricao_hash == h,
            ApprovedMemory.ativo.is_(True),
        )
        .values(ativo=False)
    )
    session.add(
        ApprovedMemory(
            org_id=item.org_id,
            company_id=item.company_id,
            gtin=item.gtin,
            descricao_normalizada=item.descricao_normalizada or item.descricao,
            descricao_hash=h,
            tipo_codigo=tipo_codigo,
            codigo=codigo,
            cst=cst,
            cclasstrib=cclasstrib,
            atributos=item.atributos or {},
            review_id=review.id,
            audit_id=audit.id,
            snapshot_id=audit.snapshot_id,
            aprovado_por=revisor.user_id,
        )
    )


def _aprovar_um(
    session: Session,
    item: AuditItem,
    audit: Audit,
    revisor: Revisor,
    comentario: str | None,
    lote_id: uuid.UUID | None = None,
) -> ItemReview:
    if item.revisao_status == StatusRevisao.APROVADO and not item.aprovado_automaticamente:
        raise Conflito("Este item já foi aprovado.")
    if item.status not in STATUS_REVISAVEIS:
        raise Conflito("O item ainda está em processamento ou terminou com erro.")
    if not item.codigo_sugerido or not item.cclasstrib_sugerido or item.perguntas:
        raise Conflito(
            "Não há classificação completa para aprovar.",
            acao="Responda às perguntas pendentes ou corrija o código e o enquadramento antes de aprovar.",
        )
    antes = foto(item)
    item.revisao_status = StatusRevisao.APROVADO
    item.aprovado_automaticamente = False
    item.final_tipo_codigo, item.final_codigo = item.tipo_codigo_sugerido, item.codigo_sugerido
    item.final_cst, item.final_cclasstrib = item.cst_sugerido, item.cclasstrib_sugerido
    item.final_regra_id, item.final_dispositivo = item.regra_id, item.dispositivo_legal
    item.revisado_por, item.revisado_em = revisor.user_id, datetime.now(UTC)
    review = _registrar(session, item, AcaoRevisao.APROVAR, antes, revisor, comentario, lote_id)
    _memoria(
        session,
        item,
        audit,
        review,
        revisor,
        tipo_codigo=item.final_tipo_codigo or "ncm",
        codigo=item.final_codigo or "",
        cst=item.final_cst,
        cclasstrib=item.final_cclasstrib,
    )
    aplicacao.versionar_perfil(
        session, item, audit, registro={"revisao": review.id.hex, "revisor": revisor.email}, motivo="aprovado"
    )
    return review


def aprovar(session: Session, item_id: uuid.UUID, revisor: Revisor, comentario: str | None = None) -> ItemReview:
    item, audit = _carregar(session, item_id)
    return _aprovar_um(session, item, audit, revisor, comentario)


def editar(
    session: Session,
    item_id: uuid.UUID,
    revisor: Revisor,
    *,
    tipo_codigo: str | None = None,
    codigo: str | None = None,
    respostas: dict[str, str] | None = None,
    cst: str | None = None,
    cclasstrib: str | None = None,
    comentario: str | None = None,
    aprovar_em_seguida: bool = False,
) -> tuple[AuditItem, bool]:
    """Devolve (item, precisa_reprocessar). Trocar o código exige nova investigação da família."""
    item, audit = _carregar(session, item_id)
    if item.revisao_status == StatusRevisao.APROVADO and not item.aprovado_automaticamente:
        raise Conflito("Item já aprovado. Desfaça a aprovação antes de editar.")
    antes = foto(item)
    snap = session.get(RefSnapshot, audit.snapshot_id) if audit.snapshot_id else None
    if snap is None:
        raise Conflito("A auditoria não tem snapshot da base de referência.")
    reprocessar = False
    acao = AcaoRevisao.RESPONDER
    if codigo is not None:
        tipo = tipo_codigo or item.tipo_codigo_sugerido or "ncm"
        versao = snap.versoes.get(tipo)
        no = obter_no(session, tipo, uuid.UUID(versao), codigo) if versao else None
        if no is None:
            raise Conflito(f"O código {codigo} não existe na tabela {tipo.upper()} usada nesta auditoria.")
        if not no["folha"]:
            raise Conflito("Escolha um código completo (último nível da hierarquia).")
        review = _registrar(session, item, AcaoRevisao.EDITAR, antes, revisor, comentario)
        # A identidade definida pelo revisor vira memória da empresa; o item é reanalisado com ela.
        _memoria(session, item, audit, review, revisor, tipo_codigo=tipo, codigo=codigo, cst=None, cclasstrib=None)
        item.revisao_status = StatusRevisao.PENDENTE
        item.aprovado_automaticamente = False
        item.tentativa += 1
        item.status, item.etapa, item.perguntas = StatusItem.PENDENTE, None, []
        return item, True
    if respostas:
        for k, v in respostas.items():
            fatos_mod.registrar(
                session,
                org_id=item.org_id,
                company_id=item.company_id,
                escopo=EscopoFato.ITEM,
                item_chave=item.codigo_interno,
                atributo=k,
                valor_=v,
                origem=OrigemFato.USUARIO,
                evidencia=f"Informado na revisão do item{': ' + comentario if comentario else ''}",
                autor_id=revisor.user_id,
                autor_email=revisor.email,
                audit_id=audit.id,
            )
        aplicacao.reavaliar(session, item.id, f"fato informado por {revisor.email}")
    if cst or cclasstrib:
        if not (cst and cclasstrib and comentario):
            raise Conflito("Para definir CST e cClassTrib manualmente, informe os dois e uma justificativa.")
        versao_cct = snap.versoes.get("cclasstrib")
        c = (
            session.scalar(
                select(CClassTribCode).where(
                    CClassTribCode.version_id == uuid.UUID(versao_cct), CClassTribCode.codigo == cclasstrib
                )
            )
            if versao_cct
            else None
        )
        if c is None or c.cst != cst:
            raise Conflito("CST/cClassTrib inexistente na tabela oficial ou incompatíveis entre si.")
        item.cst_sugerido, item.cclasstrib_sugerido, item.regra_id = cst, cclasstrib, None
        item.perc_red_ibs, item.perc_red_cbs = c.perc_red_ibs, c.perc_red_cbs
        item.hipotese = "manual"
        item.conclusao = f"Enquadramento definido pelo revisor ({revisor.email}): {comentario}"
        item.dispositivo_legal = f"Definido manualmente pelo revisor ({revisor.email}): {comentario}"
        item.perguntas = []
        acao = AcaoRevisao.EDITAR
        aplicacao.versionar_perfil(
            session, item, audit, registro={"manual": True, "revisor": revisor.email}, motivo="definido pelo revisor"
        )
    _registrar(session, item, acao, antes, revisor, comentario)
    if aprovar_em_seguida:
        _aprovar_um(session, item, audit, revisor, comentario)
    return item, reprocessar


def rejeitar(session: Session, item_id: uuid.UUID, revisor: Revisor, comentario: str) -> ItemReview:
    item, _ = _carregar(session, item_id)
    if item.revisao_status == StatusRevisao.APROVADO and not item.aprovado_automaticamente:
        raise Conflito("Item já aprovado. Desfaça a aprovação antes de rejeitar.")
    antes = foto(item)
    item.revisao_status = StatusRevisao.REJEITADO
    item.aprovado_automaticamente = False
    item.revisado_por, item.revisado_em = revisor.user_id, datetime.now(UTC)
    return _registrar(session, item, AcaoRevisao.REJEITAR, antes, revisor, comentario)


def desfazer(session: Session, item_id: uuid.UUID, revisor: Revisor) -> ItemReview:
    item, _ = _carregar(session, item_id)
    desfeitas = set(
        session.scalars(
            select(ItemReview.desfaz_review_id).where(
                ItemReview.item_id == item_id, ItemReview.desfaz_review_id.is_not(None)
            )
        )
    )
    ultima = session.scalar(
        select(ItemReview)
        .where(
            ItemReview.item_id == item_id,
            ItemReview.acao != AcaoRevisao.DESFAZER,
            ItemReview.id.notin_(desfeitas) if desfeitas else true(),
        )
        .order_by(ItemReview.created_at.desc())
        .limit(1)
    )
    if ultima is None:
        raise Conflito("Não há decisão a desfazer neste item.")
    antes = foto(item)
    restaurar(item, ultima.antes)
    session.execute(update(ApprovedMemory).where(ApprovedMemory.review_id == ultima.id).values(ativo=False))
    return _registrar(session, item, AcaoRevisao.DESFAZER, antes, revisor, None, desfaz=ultima.id)


@dataclass
class FiltroLote:
    status: list[str] | None = None
    confianca: list[str] | None = None  # confiança global aceita (alta, media)
    motivos_excluir: list[str] | None = None
    item_ids: list[uuid.UUID] | None = None
    somente_sem_perguntas: bool = True


def itens_do_lote(session: Session, audit_id: uuid.UUID, f: FiltroLote) -> list[AuditItem]:
    q = select(AuditItem).where(
        AuditItem.audit_id == audit_id,
        AuditItem.ignorado.is_(False),
        AuditItem.revisao_status == StatusRevisao.PENDENTE,
        AuditItem.codigo_sugerido.is_not(None),
        AuditItem.cclasstrib_sugerido.is_not(None),
        AuditItem.status.in_(list(STATUS_REVISAVEIS)),
    )
    if f.status:
        q = q.where(AuditItem.status.in_(f.status))
    if f.confianca:
        q = q.where(AuditItem.confianca_global.in_(f.confianca))
    if f.item_ids:
        q = q.where(AuditItem.id.in_(f.item_ids))
    itens = list(session.scalars(q.order_by(AuditItem.linha)))
    excl = set(f.motivos_excluir or [])
    return [i for i in itens if not (excl & set(i.motivos or [])) and not (f.somente_sem_perguntas and i.perguntas)]


def aprovar_lote(
    session: Session, audit_id: uuid.UUID, revisor: Revisor, f: FiltroLote, comentario: str | None = None
) -> tuple[uuid.UUID, int]:
    audit = session.get(Audit, audit_id)
    if audit is None:
        raise NaoEncontrado("Auditoria não encontrada.")
    lote_id = uuid.uuid4()
    n = 0
    for item in itens_do_lote(session, audit_id, f):
        _aprovar_um(session, item, audit, revisor, comentario or "Aprovação em lote", lote_id)
        n += 1
    return lote_id, n


def desfazer_lote(session: Session, audit_id: uuid.UUID, lote_id: uuid.UUID, revisor: Revisor) -> int:
    revisoes = list(
        session.scalars(
            select(ItemReview).where(
                and_(
                    ItemReview.audit_id == audit_id,
                    ItemReview.lote_id == lote_id,
                    ItemReview.acao == AcaoRevisao.APROVAR,
                )
            )
        )
    )
    n = 0
    for r in revisoes:
        item = session.get(AuditItem, r.item_id)
        if item is None or item.revisao_status != StatusRevisao.APROVADO:
            continue
        antes = foto(item)
        restaurar(item, r.antes)
        session.execute(update(ApprovedMemory).where(ApprovedMemory.review_id == r.id).values(ativo=False))
        _registrar(session, item, AcaoRevisao.DESFAZER, antes, revisor, "Desfazer aprovação em lote", desfaz=r.id)
        n += 1
    return n
