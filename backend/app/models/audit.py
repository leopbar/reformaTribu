"""Dados por tenant: arquivos, auditorias, itens, revisões, memória aprovada, IA e exportações."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at, updated_at, uuid_pk


class Abbreviation(Base):
    """Dicionário de abreviações. org_id nulo = dicionário global da plataforma."""

    __tablename__ = "abbreviations"
    __table_args__ = (UniqueConstraint("org_id", "abreviacao", name="uq_abbreviations_org_abrev"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    abreviacao: Mapped[str] = mapped_column(String(40))
    expansao: Mapped[str] = mapped_column(String(120))
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = created_at()


class MappingTemplate(Base):
    __tablename__ = "mapping_templates"

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    company_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    nome: Mapped[str] = mapped_column(String(120))
    sistema_origem: Mapped[str | None] = mapped_column(String(120))
    mapeamento: Mapped[dict[str, Any]] = mapped_column(default=dict)  # campo -> nome da coluna
    assinatura_colunas: Mapped[str | None] = mapped_column(String(64))
    created_by: Mapped[uuid.UUID | None]
    created_at: Mapped[datetime] = created_at()


class UploadedFile(Base):
    __tablename__ = "uploaded_files"

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    nome_original: Mapped[str] = mapped_column(String(300))
    storage_path: Mapped[str | None] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    tamanho_bytes: Mapped[int] = mapped_column(BigInteger)
    formato: Mapped[str] = mapped_column(String(10))  # xlsx | xls | csv
    encoding: Mapped[str | None] = mapped_column(String(20))
    separador: Mapped[str | None] = mapped_column(String(3))
    planilha: Mapped[str | None] = mapped_column(String(120))
    planilhas: Mapped[list[Any]] = mapped_column(default=list)
    linha_cabecalho: Mapped[int] = mapped_column(Integer, default=0)
    total_linhas: Mapped[int] = mapped_column(Integer, default=0)
    colunas: Mapped[list[Any]] = mapped_column(default=list)
    amostra: Mapped[list[Any]] = mapped_column(default=list)
    enviado_por: Mapped[uuid.UUID | None]
    expurgar_em: Mapped[date | None] = mapped_column(Date)
    expurgado_em: Mapped[datetime | None]
    created_at: Mapped[datetime] = created_at()


class Audit(Base):
    __tablename__ = "audits"

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    file_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("uploaded_files.id", ondelete="SET NULL"))
    nome: Mapped[str] = mapped_column(String(200))
    mapeamento: Mapped[dict[str, Any]] = mapped_column(default=dict)
    snapshot_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ref_snapshots.id"))
    status: Mapped[str] = mapped_column(String(30), index=True)
    modo: Mapped[str | None] = mapped_column(String(20))
    data_referencia: Mapped[date] = mapped_column(Date)
    contexto_operacao: Mapped[dict[str, Any]] = mapped_column(default=dict)
    total_itens: Mapped[int] = mapped_column(Integer, default=0)
    contadores: Mapped[dict[str, Any]] = mapped_column(default=dict)
    problemas_resumo: Mapped[dict[str, Any]] = mapped_column(default=dict)
    estimativa: Mapped[dict[str, Any]] = mapped_column(default=dict)
    custo_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal(0))
    tokens: Mapped[dict[str, Any]] = mapped_column(default=dict)
    configuracao: Mapped[dict[str, Any]] = mapped_column(default=dict)  # modelos/limiares usados
    erro: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None]
    iniciado_em: Mapped[datetime | None]
    concluido_em: Mapped[datetime | None]
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class AuditItem(Base):
    __tablename__ = "audit_items"
    __table_args__ = (
        Index("ix_audit_items_audit_status", "audit_id", "status"),
        Index("ix_audit_items_audit_linha", "audit_id", "linha"),
        Index("ix_audit_items_audit_revisao", "audit_id", "revisao_status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    audit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("audits.id", ondelete="CASCADE"))
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    linha: Mapped[int] = mapped_column(Integer)

    # Dados de entrada (somente os campos mapeados; nada de dados pessoais)
    codigo_interno: Mapped[str] = mapped_column(String(80))
    codigo_interno_gerado: Mapped[bool] = mapped_column(Boolean, default=False)
    descricao: Mapped[str] = mapped_column(Text)
    ncm_informado: Mapped[str | None] = mapped_column(String(40))
    nbs_informado: Mapped[str | None] = mapped_column(String(40))
    tipo_informado: Mapped[str | None] = mapped_column(String(40))
    gtin: Mapped[str | None] = mapped_column(String(20))
    cest: Mapped[str | None] = mapped_column(String(20))
    unidade: Mapped[str | None] = mapped_column(String(20))
    marca: Mapped[str | None] = mapped_column(String(120))
    categoria: Mapped[str | None] = mapped_column(String(200))
    cst_atual: Mapped[str | None] = mapped_column(String(10))
    cclasstrib_atual: Mapped[str | None] = mapped_column(String(10))

    # Limpeza
    ncm: Mapped[str | None] = mapped_column(String(12))
    nbs: Mapped[str | None] = mapped_column(String(12))
    problemas: Mapped[list[Any]] = mapped_column(default=list)
    duplicado_de: Mapped[int | None] = mapped_column(Integer)
    ignorado: Mapped[bool] = mapped_column(Boolean, default=False)

    # Pipeline
    descricao_normalizada: Mapped[str | None] = mapped_column(Text)
    tipo: Mapped[str | None] = mapped_column(String(20))
    etapa: Mapped[str | None] = mapped_column(String(40))
    tentativa: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="pendente")
    motivos: Mapped[list[str]] = mapped_column(ARRAY(String(50)), default=list)
    perguntas: Mapped[list[Any]] = mapped_column(default=list)
    origem: Mapped[str | None] = mapped_column(String(30))  # pipeline | memoria_aprovada
    memory_id: Mapped[uuid.UUID | None]

    tipo_codigo_sugerido: Mapped[str | None] = mapped_column(String(3))
    codigo_sugerido: Mapped[str | None] = mapped_column(String(12))
    cst_sugerido: Mapped[str | None] = mapped_column(String(3))
    cclasstrib_sugerido: Mapped[str | None] = mapped_column(String(6))
    regra_id: Mapped[uuid.UUID | None]
    regras_consideradas: Mapped[list[Any]] = mapped_column(default=list)
    tipo_tratamento: Mapped[str | None] = mapped_column(String(30))
    dispositivo_legal: Mapped[str | None] = mapped_column(Text)
    imposto_seletivo: Mapped[bool] = mapped_column(Boolean, default=False)
    confianca: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    confianca_componentes: Mapped[dict[str, Any]] = mapped_column(default=dict)
    atributos: Mapped[dict[str, Any]] = mapped_column(default=dict)
    julgamento: Mapped[dict[str, Any]] = mapped_column(default=dict)
    escalonamento: Mapped[dict[str, Any]] = mapped_column(default=dict)
    estrutura: Mapped[dict[str, Any]] = mapped_column(default=dict)
    custo_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal(0))
    processado_em: Mapped[datetime | None]
    erro: Mapped[str | None] = mapped_column(Text)

    # Revisão humana
    revisao_status: Mapped[str] = mapped_column(String(20), default="pendente")
    final_tipo_codigo: Mapped[str | None] = mapped_column(String(3))
    final_codigo: Mapped[str | None] = mapped_column(String(12))
    final_cst: Mapped[str | None] = mapped_column(String(3))
    final_cclasstrib: Mapped[str | None] = mapped_column(String(6))
    final_regra_id: Mapped[uuid.UUID | None]
    final_dispositivo: Mapped[str | None] = mapped_column(Text)
    revisado_por: Mapped[uuid.UUID | None]
    revisado_em: Mapped[datetime | None]
    updated_at: Mapped[datetime] = updated_at()


class ItemCandidate(Base):
    __tablename__ = "item_candidates"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("audit_items.id", ondelete="CASCADE"), index=True)
    tipo_codigo: Mapped[str] = mapped_column(String(3))
    codigo: Mapped[str] = mapped_column(String(12))
    descricao_completa: Mapped[str] = mapped_column(Text)
    posicao: Mapped[int] = mapped_column(Integer)
    rank_semantico: Mapped[int | None] = mapped_column(Integer)
    rank_textual: Mapped[int | None] = mapped_column(Integer)
    score: Mapped[Decimal] = mapped_column(Numeric(10, 6))
    codigo_atual: Mapped[bool] = mapped_column(Boolean, default=False)


class ItemReview(Base):
    """Histórico de decisões (somente inserção)."""

    __tablename__ = "item_reviews"

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    audit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("audits.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("audit_items.id", ondelete="CASCADE"), index=True)
    acao: Mapped[str] = mapped_column(String(20))
    antes: Mapped[dict[str, Any]] = mapped_column(default=dict)
    depois: Mapped[dict[str, Any]] = mapped_column(default=dict)
    comentario: Mapped[str | None] = mapped_column(Text)
    lote_id: Mapped[uuid.UUID | None]
    desfaz_review_id: Mapped[uuid.UUID | None]
    user_id: Mapped[uuid.UUID]
    user_email: Mapped[str | None] = mapped_column(String(320))
    created_at: Mapped[datetime] = created_at()


class ApprovedMemory(Base):
    """Classificações aprovadas por humanos, reutilizadas em auditorias futuras da empresa."""

    __tablename__ = "approved_memory"
    __table_args__ = (
        Index("ix_memory_company_desc", "company_id", "descricao_hash"),
        Index("ix_memory_company_gtin", "company_id", "gtin"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    gtin: Mapped[str | None] = mapped_column(String(20))
    descricao_normalizada: Mapped[str] = mapped_column(Text)
    descricao_hash: Mapped[str] = mapped_column(String(64))
    tipo_codigo: Mapped[str] = mapped_column(String(3))
    codigo: Mapped[str] = mapped_column(String(12))
    cst: Mapped[str | None] = mapped_column(String(3))
    cclasstrib: Mapped[str | None] = mapped_column(String(6))
    atributos: Mapped[dict[str, Any]] = mapped_column(default=dict)
    review_id: Mapped[uuid.UUID | None]
    audit_id: Mapped[uuid.UUID | None]
    snapshot_id: Mapped[uuid.UUID | None]
    aprovado_por: Mapped[uuid.UUID | None]
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = created_at()


class LlmCall(Base):
    __tablename__ = "llm_calls"
    __table_args__ = (
        Index("ix_llm_calls_status_modelo", "status", "modelo"),
        Index("ix_llm_calls_org_created", "org_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    # Nulo para chamadas de plataforma (extração de regras), visíveis só ao superadministrador.
    org_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    audit_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("audits.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("audit_items.id", ondelete="CASCADE"), index=True)
    no: Mapped[str] = mapped_column(String(40))
    modelo: Mapped[str] = mapped_column(String(80))
    prompt_versao: Mapped[str] = mapped_column(String(60))
    modo: Mapped[str] = mapped_column(String(20))
    chave_idempotencia: Mapped[str] = mapped_column(String(200), unique=True)
    status: Mapped[str] = mapped_column(String(20))
    batch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("llm_batches.id"), index=True)
    requisicao: Mapped[dict[str, Any]] = mapped_column(default=dict)
    resposta: Mapped[dict[str, Any] | None]
    stop_reason: Mapped[str | None] = mapped_column(String(30))
    tokens_entrada: Mapped[int] = mapped_column(Integer, default=0)
    tokens_saida: Mapped[int] = mapped_column(Integer, default=0)
    tokens_cache_escrita: Mapped[int] = mapped_column(Integer, default=0)
    tokens_cache_leitura: Mapped[int] = mapped_column(Integer, default=0)
    custo_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal(0))
    latencia_ms: Mapped[int | None] = mapped_column(Integer)
    tentativas: Mapped[int] = mapped_column(Integer, default=0)
    request_id: Mapped[str | None] = mapped_column(String(80))
    erro: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()
    concluido_em: Mapped[datetime | None]


class LlmBatch(Base):
    __tablename__ = "llm_batches"

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    audit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("audits.id", ondelete="CASCADE"), index=True)
    anthropic_batch_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    modelo: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20))
    total_requisicoes: Mapped[int] = mapped_column(Integer, default=0)
    contagens: Mapped[dict[str, Any]] = mapped_column(default=dict)
    erro: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()
    concluido_em: Mapped[datetime | None]


class ExportLayout(Base):
    __tablename__ = "export_layouts"

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    nome: Mapped[str] = mapped_column(String(120))
    # [{"campo": "codigo_interno", "titulo": "COD"}, ...]
    colunas: Mapped[list[Any]] = mapped_column(default=list)
    separador_csv: Mapped[str] = mapped_column(String(3), default=";")
    ncm_formatado: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = created_at()


class ExportJob(Base):
    __tablename__ = "export_jobs"

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    audit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("audits.id", ondelete="CASCADE"), index=True)
    formato: Mapped[str] = mapped_column(String(10))  # xlsx | csv | pdf
    layout_id: Mapped[uuid.UUID | None]
    status: Mapped[str] = mapped_column(String(20))
    arquivo_path: Mapped[str | None] = mapped_column(Text)
    arquivo_nome: Mapped[str | None] = mapped_column(String(200))
    total_itens: Mapped[int] = mapped_column(Integer, default=0)
    erro: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None]
    created_at: Mapped[datetime] = created_at()
    concluido_em: Mapped[datetime | None]
