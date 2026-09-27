"""Organizações (tenants), usuários, vínculos, empresas auditadas e configurações."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, created_at, updated_at, uuid_pk


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = uuid_pk()
    nome: Mapped[str] = mapped_column(String(200))
    tipo: Mapped[str] = mapped_column(String(30))
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = created_at()

    settings: Mapped[OrgSettings] = relationship(back_populates="organization", uselist=False)


class OrgSettings(Base):
    """Configurações por organização: limites de confiança, modelos, orçamento, retenção."""

    __tablename__ = "org_settings"

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True)
    limiar_confirmado: Mapped[Decimal] = mapped_column(Numeric(4, 3), default=Decimal("0.900"))
    limiar_corrigido: Mapped[Decimal] = mapped_column(Numeric(4, 3), default=Decimal("0.850"))
    limiar_escalonamento: Mapped[Decimal] = mapped_column(Numeric(4, 3), default=Decimal("0.800"))
    modelo_principal: Mapped[str | None] = mapped_column(String(80))
    modelo_escalonamento: Mapped[str | None] = mapped_column(String(80))
    modelo_leve: Mapped[str | None] = mapped_column(String(80))
    usar_modelo_leve: Mapped[bool] = mapped_column(Boolean, default=False)
    orcamento_mensal_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), default=Decimal("100.00"))
    alerta_orcamento_pct: Mapped[int] = mapped_column(Integer, default=80)
    lote_min_itens: Mapped[int | None] = mapped_column(Integer)
    imposto_seletivo_exige_analise: Mapped[bool] = mapped_column(Boolean, default=True)
    retencao_arquivos_dias: Mapped[int] = mapped_column(Integer, default=30)
    ultimo_alerta_orcamento: Mapped[str | None] = mapped_column(String(7))  # AAAA-MM
    extras: Mapped[dict[str, Any]] = mapped_column(default=dict)
    updated_at: Mapped[datetime] = updated_at()

    organization: Mapped[Organization] = relationship(back_populates="settings")


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(CITEXT, unique=True)
    nome: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(Text)
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    ultimo_login_em: Mapped[datetime | None]
    created_at: Mapped[datetime] = created_at()


class Membership(Base):
    """Vínculo usuário–organização com papel. Um usuário pode pertencer a várias organizações."""

    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("org_id", "user_id", name="uq_memberships_org_user"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    papel: Mapped[str] = mapped_column(String(20))
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = created_at()

    user: Mapped[User] = relationship()


class Company(Base):
    """Empresa auditada. Pertence a uma organização."""

    __tablename__ = "companies"
    __table_args__ = (UniqueConstraint("org_id", "cnpj", name="uq_companies_org_cnpj"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    razao_social: Mapped[str] = mapped_column(String(250))
    nome_fantasia: Mapped[str | None] = mapped_column(String(250))
    cnpj: Mapped[str] = mapped_column(String(14))
    regime_tributario: Mapped[str] = mapped_column(String(30))
    uf: Mapped[str] = mapped_column(String(2))
    atividade_principal: Mapped[str | None] = mapped_column(String(300))
    cnae: Mapped[str | None] = mapped_column(String(10))
    # Atributos usados por condições legais de fonte "empresa" (ex.: profissao_regulamentada).
    atributos: Mapped[dict[str, Any]] = mapped_column(default=dict)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = created_at()


class CompanyAccess(Base):
    """Restringe usuários com papel Leitura às empresas liberadas."""

    __tablename__ = "company_access"
    __table_args__ = (UniqueConstraint("membership_id", "company_id", name="uq_company_access"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    membership_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("memberships.id", ondelete="CASCADE"))
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))


class RefreshToken(Base):
    """Refresh tokens com rotação e detecção de reuso (por família)."""

    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    familia_id: Mapped[uuid.UUID] = mapped_column(index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    org_id: Mapped[uuid.UUID | None]
    expira_em: Mapped[datetime]
    revogado_em: Mapped[datetime | None]
    substituido_por: Mapped[uuid.UUID | None]
    user_agent: Mapped[str | None] = mapped_column(String(300))
    ip: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = created_at()


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    tipo: Mapped[str] = mapped_column(String(50))
    titulo: Mapped[str] = mapped_column(String(200))
    mensagem: Mapped[str] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(String(300))
    lida_em: Mapped[datetime | None]
    created_at: Mapped[datetime] = created_at()
