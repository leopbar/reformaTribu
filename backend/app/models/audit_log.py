"""Log de auditoria imutável (somente inserção, com cadeia de hash)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at


class AuditLog(Base):
    __tablename__ = "audit_log"
    # Sem RETURNING: registros de plataforma não são legíveis pela aplicação (RLS).
    __table_args__ = {"implicit_returning": False}  # noqa: RUF012

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # Nulo para ações de plataforma (base de referência), visíveis só ao superadministrador.
    org_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    user_id: Mapped[uuid.UUID | None]
    user_email: Mapped[str | None] = mapped_column(String(320))
    acao: Mapped[str] = mapped_column(String(60), index=True)
    entidade: Mapped[str | None] = mapped_column(String(60))
    entidade_id: Mapped[str | None] = mapped_column(String(80))
    detalhes: Mapped[dict[str, Any]] = mapped_column(default=dict)
    ip: Mapped[str | None] = mapped_column(String(64))
    request_id: Mapped[str | None] = mapped_column(String(64))
    hash_anterior: Mapped[str | None] = mapped_column(String(64))
    hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = created_at()
