"""Catálogo de IA da plataforma (sem org_id; só o superadministrador altera).

- `LlmProvider`: uma plataforma (Anthropic, OpenAI, DeepSeek), com a chave de API cifrada.
- `LlmModel`: um modelo com preço por milhão de tokens e o que ele suporta (lote, esforço).
- `LlmAgent`: o modelo e o esforço escolhidos para cada agente de IA do sistema.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, LargeBinary, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, updated_at


class LlmProvider(Base):
    __tablename__ = "llm_provedores"

    provedor: Mapped[str] = mapped_column(String(20), primary_key=True)
    nome: Mapped[str] = mapped_column(String(80))
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    chave_cifrada: Mapped[bytes | None] = mapped_column(LargeBinary)
    chave_final: Mapped[str | None] = mapped_column(String(8))
    base_url: Mapped[str | None] = mapped_column(String(300))
    testado_em: Mapped[datetime | None]
    teste_ok: Mapped[bool | None] = mapped_column(Boolean)
    teste_mensagem: Mapped[str | None] = mapped_column(Text)
    atualizado_por: Mapped[str | None] = mapped_column(String(320))
    updated_at: Mapped[datetime] = updated_at()


class LlmModel(Base):
    __tablename__ = "llm_modelos"

    modelo: Mapped[str] = mapped_column(String(80), primary_key=True)
    provedor: Mapped[str] = mapped_column(ForeignKey("llm_provedores.provedor"))
    nome: Mapped[str] = mapped_column(String(120))
    preco_entrada: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    preco_saida: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    preco_cache_leitura: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    mult_cache_escrita: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal(1))
    suporta_lote: Mapped[bool] = mapped_column(Boolean, default=False)
    suporta_esforco: Mapped[bool] = mapped_column(Boolean, default=False)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    notas: Mapped[str | None] = mapped_column(Text)
    atualizado_por: Mapped[str | None] = mapped_column(String(320))
    updated_at: Mapped[datetime] = updated_at()


class LlmAgent(Base):
    __tablename__ = "llm_agentes"

    agente: Mapped[str] = mapped_column(String(30), primary_key=True)
    modelo: Mapped[str] = mapped_column(ForeignKey("llm_modelos.modelo"))
    esforco: Mapped[str] = mapped_column(String(10), default="medium")
    atualizado_por: Mapped[str | None] = mapped_column(String(320))
    updated_at: Mapped[datetime] = updated_at()
