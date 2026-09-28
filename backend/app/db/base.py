"""Base declarativa do SQLAlchemy e tipos comuns."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)
    type_annotation_map = {  # noqa: RUF012
        dict[str, Any]: JSONB,
        list[Any]: JSONB,
        uuid.UUID: UUID(as_uuid=True),
        datetime: DateTime(timezone=True),
    }


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def agora() -> datetime:
    return datetime.now(UTC)


# Padrões calculados no Python (além do servidor) evitam INSERT ... RETURNING/refresh implícitos,
# que conflitariam com políticas de RLS e com o carregamento preguiçoso em sessões assíncronas.
def created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), default=agora, server_default=func.now(), nullable=False)


def updated_at() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True), default=agora, onupdate=agora, server_default=func.now(), nullable=False
    )


# Tabelas com dados de clientes: todas têm org_id e Row-Level Security.
TENANT_TABLES: tuple[str, ...] = (
    "org_settings",
    "memberships",
    "company_access",
    "companies",
    "abbreviations",
    "mapping_templates",
    "uploaded_files",
    "audits",
    "audit_items",
    "item_candidates",
    "item_reviews",
    "approved_memory",
    "llm_calls",
    "llm_batches",
    "export_jobs",
    "export_layouts",
    "audit_log",
    "notifications",
    "company_facts",
    "tax_theses",
    "pendencias",
    "tax_profiles",
)
