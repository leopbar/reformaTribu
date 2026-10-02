"""Analista fiscal: fatos com origem, teses por família, perguntas decisivas e perfis tributários.

- `CompanyFact`: um fato sobre a empresa, um grupo de itens ou um item, sempre com origem e autor.
  Fatos nunca são apagados: uma correção desativa o anterior e aponta para ele.
- `TaxThesis`: a investigação jurídica feita uma vez por família (NCM/NBS + cenário + dossiê + data).
  Guarda as hipóteses testáveis, as condições e os trechos normativos citados.
- `Pendencia`: pergunta que muda o enquadramento, feita no escopo mais amplo possível.
- `TaxProfile`: o perfil tributário de um item num cenário e vigência. Cada reavaliação que muda o
  resultado cria uma versão nova; as anteriores ficam registradas (dossiê de decisão).
- `DecisionMemory`: o enquadramento que uma pessoa aprovou ou corrigiu para um NCM/NBS num cenário e
  ramo (ADR 0028). Reforça ou contesta a conclusão do analista nos itens seguintes da organização.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, Date, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at, updated_at, uuid_pk


class CompanyFact(Base):
    __tablename__ = "company_facts"
    __table_args__ = (
        Index("ix_company_facts_busca", "company_id", "atributo", "ativo"),
        Index("ix_company_facts_item", "company_id", "item_chave"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    escopo: Mapped[str] = mapped_column(String(10))  # empresa | grupo | item
    # grupo: "categoria:<nome normalizado>" ou "familia:<ncm|nbs>:<código>"
    grupo_chave: Mapped[str | None] = mapped_column(String(250))
    # item: código interno do ERP (estável entre auditorias da mesma empresa)
    item_chave: Mapped[str | None] = mapped_column(String(80))
    atributo: Mapped[str] = mapped_column(String(80))
    valor: Mapped[str] = mapped_column(String(200))
    origem: Mapped[str] = mapped_column(String(20))
    evidencia: Mapped[str | None] = mapped_column(Text)
    autor_id: Mapped[uuid.UUID | None]
    autor_email: Mapped[str | None] = mapped_column(String(320))
    audit_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("audits.id", ondelete="SET NULL"))
    pendencia_id: Mapped[uuid.UUID | None]
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    substitui_id: Mapped[uuid.UUID | None]
    created_at: Mapped[datetime] = created_at()


class TaxThesis(Base):
    __tablename__ = "tax_theses"
    __table_args__ = (UniqueConstraint("org_id", "chave", name="uq_tax_theses_org_chave"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    audit_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("audits.id", ondelete="SET NULL"))
    chave: Mapped[str] = mapped_column(String(120))
    tipo_codigo: Mapped[str] = mapped_column(String(3))
    codigo: Mapped[str] = mapped_column(String(12))
    cenario: Mapped[str] = mapped_column(String(40))
    data_referencia: Mapped[date] = mapped_column(Date)
    snapshot_id: Mapped[uuid.UUID | None]
    status: Mapped[str] = mapped_column(String(20))  # concluida | falhou
    # Pacote de evidências enviado ao modelo (trechos, correlações, cClassTrib candidatos).
    evidencias: Mapped[dict[str, Any]] = mapped_column(default=dict)
    # Hipóteses, condições, fatos necessários, Imposto Seletivo e conflitos (saída validada).
    resultado: Mapped[dict[str, Any]] = mapped_column(default=dict)
    validacao: Mapped[dict[str, Any]] = mapped_column(default=dict)
    fatos_empresa: Mapped[dict[str, Any]] = mapped_column(default=dict)
    llm_call_id: Mapped[uuid.UUID | None]
    modelo: Mapped[str | None] = mapped_column(String(80))
    prompt_versao: Mapped[str | None] = mapped_column(String(60))
    erro: Mapped[str | None] = mapped_column(Text)
    # Curadoria: um revisor pode validar a tese; ela passa a contar como precedente aprovado.
    aprovada_por: Mapped[uuid.UUID | None]
    aprovada_por_email: Mapped[str | None] = mapped_column(String(320))
    aprovada_em: Mapped[datetime | None]
    created_at: Mapped[datetime] = created_at()


class Pendencia(Base):
    __tablename__ = "pendencias"
    __table_args__ = (
        UniqueConstraint("audit_id", "atributo", "escopo", "grupo_chave", name="uq_pendencias_pergunta"),
        Index("ix_pendencias_audit_status", "audit_id", "status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    audit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("audits.id", ondelete="CASCADE"))
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    atributo: Mapped[str] = mapped_column(String(80))
    escopo: Mapped[str] = mapped_column(String(10))  # empresa | grupo | item
    # Nunca nulo (a unicidade depende disso): "" para empresa, "item:<código>" para um item só.
    grupo_chave: Mapped[str] = mapped_column(String(250), default="")
    grupo_rotulo: Mapped[str | None] = mapped_column(String(300))
    pergunta: Mapped[str] = mapped_column(Text)
    motivo: Mapped[str | None] = mapped_column(Text)
    # [{"valor": "sim", "rotulo": "Sim", "efeito": "Anexo I (alíquota zero)"}]
    opcoes: Mapped[list[Any]] = mapped_column(default=list)
    nivel: Mapped[str] = mapped_column(String(20), default="operacional")
    item_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), default=list)
    status: Mapped[str] = mapped_column(String(20), default="aberta")
    resposta: Mapped[str | None] = mapped_column(String(200))
    respostas_itens: Mapped[dict[str, Any]] = mapped_column(default=dict)
    respondido_por: Mapped[uuid.UUID | None]
    respondido_por_email: Mapped[str | None] = mapped_column(String(320))
    respondido_em: Mapped[datetime | None]
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class TaxProfile(Base):
    __tablename__ = "tax_profiles"
    __table_args__ = (Index("ix_tax_profiles_item_ativo", "item_id", "ativo"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    audit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("audits.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("audit_items.id", ondelete="CASCADE"))
    codigo_interno: Mapped[str] = mapped_column(String(80))
    cenario: Mapped[str] = mapped_column(String(40))
    vigencia: Mapped[date] = mapped_column(Date)
    versao: Mapped[int] = mapped_column(Integer, default=1)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(30))
    nivel_revisao: Mapped[str | None] = mapped_column(String(20))
    tipo_codigo: Mapped[str | None] = mapped_column(String(3))
    codigo: Mapped[str | None] = mapped_column(String(12))
    cst: Mapped[str | None] = mapped_column(String(3))
    cclasstrib: Mapped[str | None] = mapped_column(String(6))
    perc_red_ibs: Mapped[Decimal | None] = mapped_column(Numeric(7, 4))
    perc_red_cbs: Mapped[Decimal | None] = mapped_column(Numeric(7, 4))
    imposto_seletivo: Mapped[str | None] = mapped_column(String(20))  # nao_sujeito | sujeito | indefinido
    hipotese: Mapped[str | None] = mapped_column(String(20))
    conclusao: Mapped[str | None] = mapped_column(Text)
    confianca_global: Mapped[str | None] = mapped_column(String(15))
    dimensoes: Mapped[dict[str, Any]] = mapped_column(default=dict)
    # Dossiê de decisão: fatos usados (com origem), fundamentos (trechos), versões, tese, motivo da mudança.
    registro: Mapped[dict[str, Any]] = mapped_column(default=dict)
    thesis_id: Mapped[uuid.UUID | None]
    motivo_versao: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = created_at()


class DecisionMemory(Base):
    """Decisão de uma pessoa sobre o enquadramento de um código (ADR 0028).

    Vale para a organização inteira, entre empresas do mesmo ramo (`segmento`); empresa sem ramo
    só aproveita as próprias decisões. Desfazer a decisão desativa o registro."""

    __tablename__ = "decision_memory"
    __table_args__ = (Index("ix_decision_memory_busca", "tipo_codigo", "codigo", "cenario", "ativo"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    audit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("audits.id", ondelete="CASCADE"))
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("audit_items.id", ondelete="CASCADE"))
    review_id: Mapped[uuid.UUID | None]
    segmento: Mapped[str | None] = mapped_column(String(40))
    cenario: Mapped[str] = mapped_column(String(40))
    tipo_codigo: Mapped[str] = mapped_column(String(3))
    codigo: Mapped[str] = mapped_column(String(12))
    cclasstrib: Mapped[str] = mapped_column(String(6))
    cst: Mapped[str | None] = mapped_column(String(3))
    imposto_seletivo: Mapped[str | None] = mapped_column(String(20))  # nao_sujeito | sujeito
    # Fatos que decidiram o enquadramento ("atributo=valor" ordenados); a decisão só vale com os mesmos.
    fatos_chave: Mapped[str] = mapped_column(Text, default="")
    fatos: Mapped[list[Any]] = mapped_column(default=list)
    # Dispositivos citados na decisão (ex.: "LC 214/2025 Anexo I, item 2"): ligam a decisão à regra legal.
    dispositivo: Mapped[str | None] = mapped_column(Text)
    origem: Mapped[str] = mapped_column(String(20))  # aprovacao | correcao
    peso: Mapped[int] = mapped_column(Integer, default=1)
    user_id: Mapped[uuid.UUID | None]
    user_email: Mapped[str | None] = mapped_column(String(320))
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = created_at()
