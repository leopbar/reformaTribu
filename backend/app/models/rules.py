"""Regras declarativas dos anexos da LC 214/2025."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Boolean, Date, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at, updated_at, uuid_pk


class LegalRule(Base):
    __tablename__ = "legal_rules"
    __table_args__ = (
        UniqueConstraint("slug", "versao", name="uq_legal_rules_slug_versao"),
        Index("ix_legal_rules_status", "status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    slug: Mapped[str] = mapped_column(String(120))
    versao: Mapped[int] = mapped_column(Integer, default=1)
    anexo: Mapped[str | None] = mapped_column(String(10))
    item: Mapped[str | None] = mapped_column(String(20))
    titulo_anexo: Mapped[str | None] = mapped_column(Text)
    descricao_legal: Mapped[str] = mapped_column(Text)
    dispositivo_legal: Mapped[str] = mapped_column(Text)
    tipo_tratamento: Mapped[str] = mapped_column(String(30))
    tipo_codigo: Mapped[str | None] = mapped_column(String(3))  # ncm | nbs | None (regra padrão)
    # {"codigos": [{"codigo": "34011190", "nivel": "item"}], "universal": false}
    abrangencia: Mapped[dict[str, Any]] = mapped_column(default=dict)
    # [{"codigo": "030611", "nivel": "subposicao"} | {"descricao": "lagostas"}]
    excecoes: Mapped[list[Any]] = mapped_column(default=list)
    # [{"atributo": "adicao_acucar", "fonte": "item", "deve_ser": false, "pergunta": "..."}]
    condicoes: Mapped[list[Any]] = mapped_column(default=list)
    cst_ibs_cbs: Mapped[str | None] = mapped_column(String(3))
    cclasstrib: Mapped[str | None] = mapped_column(String(6))
    vigencia_inicio: Mapped[date | None] = mapped_column(Date)
    vigencia_fim: Mapped[date | None] = mapped_column(Date)
    prioridade: Mapped[int] = mapped_column(Integer, default=100)
    status: Mapped[str] = mapped_column(String(20))
    origem: Mapped[str] = mapped_column(String(30))
    fonte_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ref_versions.id"))
    provision_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("legal_provisions.id"))
    controverso: Mapped[bool] = mapped_column(Boolean, default=False)
    nota_controversia: Mapped[str | None] = mapped_column(Text)
    erros_validacao: Mapped[list[Any]] = mapped_column(default=list)
    avisos: Mapped[list[Any]] = mapped_column(default=list)
    extracao: Mapped[dict[str, Any]] = mapped_column(default=dict)  # modelo, prompt, llm_call_id
    revisado_por: Mapped[uuid.UUID | None]
    revisado_por_email: Mapped[str | None] = mapped_column(String(320))
    revisado_em: Mapped[datetime | None]
    nota_revisao: Mapped[str | None] = mapped_column(Text)
    substitui_id: Mapped[uuid.UUID | None]
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class RuleCode(Base):
    """Índice de prefixos de código de cada regra, para casar rapidamente um NCM/NBS."""

    __tablename__ = "legal_rule_codes"
    __table_args__ = (Index("ix_rule_codes_prefixo", "tipo_codigo", "prefixo"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rule_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("legal_rules.id", ondelete="CASCADE"), index=True)
    tipo_codigo: Mapped[str] = mapped_column(String(3))
    prefixo: Mapped[str] = mapped_column(String(12))
    excecao: Mapped[bool] = mapped_column(Boolean, default=False)
