"""Revisão humana: aprovar, editar (com recálculo do enquadramento), responder perguntas, rejeitar,
desfazer e aprovar em lote. Toda decisão gera um registro imutável em item_reviews e alimenta a
memória aprovada da empresa."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, select, true, update
from sqlalchemy.orm import Session

from app.core.errors import Conflito, NaoEncontrado
from app.ingest.cleaning import hash_descricao
from app.models import (
    ApprovedMemory,
    Audit,
    AuditItem,
    CClassTribCode,
    Company,
    ItemReview,
    RefSnapshot,
)
from app.models.enums import AcaoRevisao, StatusItem, StatusRevisao
from app.reference.search import obter_no
from app.rules.engine import ConjuntoRegras
from app.rules.engine import enquadrar as aplicar_regras


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


def _salvar_memoria(session: Session, item: AuditItem, audit: Audit, review: ItemReview, revisor: Revisor) -> None:
    if not item.final_codigo or not item.final_tipo_codigo:
        return
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
            tipo_codigo=item.final_tipo_codigo,
            codigo=item.final_codigo,
            cst=item.final_cst,
            cclasstrib=item.final_cclasstrib,
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
    if item.revisao_status == StatusRevisao.APROVADO:
        raise Conflito("Este item já foi aprovado.")
    if item.status in (StatusItem.PENDENTE, StatusItem.PROCESSANDO):
        raise Conflito("O item ainda está em processamento.")
    if not item.codigo_sugerido or not item.cclasstrib_sugerido or item.perguntas:
        raise Conflito(
            "Não há classificação completa para aprovar.",
            acao="Responda às perguntas pendentes ou edite o código e o enquadramento antes de aprovar.",
        )
    antes = foto(item)
    agora = datetime.now(UTC)
    item.revisao_status = StatusRevisao.APROVADO
    item.final_tipo_codigo, item.final_codigo = item.tipo_codigo_sugerido, item.codigo_sugerido
    item.final_cst, item.final_cclasstrib = item.cst_sugerido, item.cclasstrib_sugerido
    item.final_regra_id, item.final_dispositivo = item.regra_id, item.dispositivo_legal
    item.revisado_por, item.revisado_em = revisor.user_id, agora
    review = _registrar(session, item, AcaoRevisao.APROVAR, antes, revisor, comentario, lote_id)
    _salvar_memoria(session, item, audit, review, revisor)
    return review


def aprovar(session: Session, item_id: uuid.UUID, revisor: Revisor, comentario: str | None = None) -> ItemReview:
    item, audit = _carregar(session, item_id)
    return _aprovar_um(session, item, audit, revisor, comentario)


def _conjunto(session: Session, audit: Audit) -> tuple[ConjuntoRegras, RefSnapshot]:
    snap = session.get(RefSnapshot, audit.snapshot_id)
    if snap is None:
        raise Conflito("A auditoria não tem snapshot da base de referência.")
    return ConjuntoRegras.carregar(session, snap.regras_aprovadas, snap.regras_pendentes), snap


def recalcular_enquadramento(session: Session, item: AuditItem, audit: Audit) -> None:
    conjunto, _ = _conjunto(session, audit)
    empresa = session.get(Company, item.company_id)
    assert empresa is not None
    r = aplicar_regras(
        conjunto,
        item.tipo_codigo_sugerido or "ncm",
        item.codigo_sugerido or "",
        f"{item.descricao} {item.descricao_normalizada or ''}",
        {
            "item": item.atributos or {},
            "empresa": {
                "regime_tributario": empresa.regime_tributario,
                "uf": empresa.uf,
                "cnae": empresa.cnae,
                **(empresa.atributos or {}),
            },
            "operacao": audit.contexto_operacao or {},
        },
        audit.data_referencia,
    )
    item.cst_sugerido, item.cclasstrib_sugerido = r.cst, r.cclasstrib
    item.regra_id = r.regra.id if r.regra else None
    item.tipo_tratamento, item.dispositivo_legal = r.tipo_tratamento, r.dispositivo
    item.perguntas = [p.como_dict() for p in r.perguntas]
    item.regras_consideradas = r.consideradas
    item.imposto_seletivo = r.imposto_seletivo
    item.motivos = list(
        dict.fromkeys([m for m in item.motivos or [] if m not in _MOTIVOS_DO_ENQUADRAMENTO] + list(r.motivos))
    )


_MOTIVOS_DO_ENQUADRAMENTO = {
    "CONDICAO_LEGAL_NAO_VERIFICAVEL",
    "EXCECAO_LEGAL_POSSIVEL",
    "REGRA_PENDENTE_DE_REVISAO",
    "MULTIPLAS_REGRAS_APLICAVEIS",
    "SUJEITO_A_IMPOSTO_SELETIVO",
    "CASO_CONTROVERSO",
    "BASE_REFERENCIA_INCOMPLETA",
}


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
) -> AuditItem:
    item, audit = _carregar(session, item_id)
    if item.revisao_status == StatusRevisao.APROVADO:
        raise Conflito("Item já aprovado. Desfaça a aprovação antes de editar.")
    antes = foto(item)
    _, snap = _conjunto(session, audit)
    if codigo is not None:
        tipo = tipo_codigo or item.tipo_codigo_sugerido or "ncm"
        versao = snap.versoes.get(tipo)
        no = obter_no(session, tipo, uuid.UUID(versao), codigo) if versao else None
        if no is None:
            raise Conflito(f"O código {codigo} não existe na tabela {tipo.upper()} usada nesta auditoria.")
        if not no["folha"]:
            raise Conflito("Escolha um código completo (último nível da hierarquia).")
        item.tipo_codigo_sugerido, item.codigo_sugerido = tipo, codigo
    if respostas:
        atributos = dict(item.atributos or {})
        for k, v in respostas.items():
            atributos[k] = str(v).strip().lower()
        item.atributos = atributos
    if codigo is not None or respostas:
        recalcular_enquadramento(session, item, audit)
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
        item.dispositivo_legal = f"Definido manualmente pelo revisor ({revisor.email}): {comentario}"
        item.perguntas = []
    _registrar(
        session, item, AcaoRevisao.EDITAR if (codigo or cst) else AcaoRevisao.RESPONDER, antes, revisor, comentario
    )
    if aprovar_em_seguida:
        _aprovar_um(session, item, audit, revisor, comentario)
    return item


def rejeitar(session: Session, item_id: uuid.UUID, revisor: Revisor, comentario: str) -> ItemReview:
    item, _ = _carregar(session, item_id)
    if item.revisao_status == StatusRevisao.APROVADO:
        raise Conflito("Item já aprovado. Desfaça a aprovação antes de rejeitar.")
    antes = foto(item)
    item.revisao_status = StatusRevisao.REJEITADO
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
    confianca_min: float | None = None
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
        AuditItem.status.in_([StatusItem.CONFIRMADO, StatusItem.CORRIGIDO, StatusItem.ANALISE_HUMANA]),
    )
    if f.status:
        q = q.where(AuditItem.status.in_(f.status))
    if f.confianca_min is not None:
        q = q.where(AuditItem.confianca >= Decimal(str(f.confianca_min)))
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
