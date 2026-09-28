"""Base de referência oficial (global, versionada, nunca sobrescrita)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    Computed,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at, uuid_pk

# A dimensão do vetor segue EMBEDDINGS_DIM e é ajustada no banco pelo comando `migrate`.


class RefVersion(Base):
    """Uma importação de uma fonte oficial. Cada importação cria uma versão nova."""

    __tablename__ = "ref_versions"
    __table_args__ = (UniqueConstraint("fonte", "sha256", name="uq_ref_versions_fonte_sha"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    fonte: Mapped[str] = mapped_column(String(20), index=True)
    rotulo: Mapped[str] = mapped_column(String(200))
    url_origem: Mapped[str | None] = mapped_column(Text)
    modo_coleta: Mapped[str] = mapped_column(String(20))  # download | upload_manual
    coletado_em: Mapped[datetime]
    sha256: Mapped[str] = mapped_column(String(64))
    arquivo_path: Mapped[str] = mapped_column(Text)
    arquivo_nome: Mapped[str | None] = mapped_column(String(300))
    vigencia_inicio: Mapped[date | None] = mapped_column(Date)
    vigencia_fim: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20))
    importado_por: Mapped[uuid.UUID | None]
    importado_por_email: Mapped[str | None] = mapped_column(String(320))
    estatisticas: Mapped[dict[str, Any]] = mapped_column(default=dict)
    avisos: Mapped[list[Any]] = mapped_column(default=list)
    erro: Mapped[str | None] = mapped_column(Text)
    embeddings_status: Mapped[str] = mapped_column(String(20), default="nao_aplicavel")
    embeddings_modelo: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = created_at()


class _NomenclaturaMixin:
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    codigo: Mapped[str] = mapped_column(String(12))  # somente dígitos
    codigo_formatado: Mapped[str] = mapped_column(String(20))
    nivel: Mapped[str] = mapped_column(String(20))
    codigo_pai: Mapped[str | None] = mapped_column(String(12))
    descricao: Mapped[str] = mapped_column(Text)
    # Descrição hierárquica completa: capítulo › posição › subposição › item.
    descricao_completa: Mapped[str] = mapped_column(Text)
    folha: Mapped[bool] = mapped_column(Boolean, default=False)
    data_inicio: Mapped[date | None] = mapped_column(Date)
    data_fim: Mapped[date | None] = mapped_column(Date)
    ato_legal: Mapped[str | None] = mapped_column(String(200))
    embedding: Mapped[list[float] | None] = mapped_column(Vector(), nullable=True)
    tsv: Mapped[Any] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('portuguese', immutable_unaccent(descricao_completa))", persisted=True),
    )


class NcmNode(_NomenclaturaMixin, Base):
    __tablename__ = "ncm_nodes"
    __table_args__ = (
        UniqueConstraint("version_id", "codigo", name="uq_ncm_nodes_version_codigo"),
        Index("ix_ncm_nodes_tsv", "tsv", postgresql_using="gin"),
        Index("ix_ncm_nodes_codigo", "codigo"),
    )

    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ref_versions.id", ondelete="CASCADE"))


class NbsNode(_NomenclaturaMixin, Base):
    __tablename__ = "nbs_nodes"
    __table_args__ = (
        UniqueConstraint("version_id", "codigo", name="uq_nbs_nodes_version_codigo"),
        Index("ix_nbs_nodes_tsv", "tsv", postgresql_using="gin"),
        Index("ix_nbs_nodes_codigo", "codigo"),
    )

    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ref_versions.id", ondelete="CASCADE"))


class CstCode(Base):
    __tablename__ = "cst_codes"
    __table_args__ = (UniqueConstraint("version_id", "cst", name="uq_cst_codes_version_cst"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ref_versions.id", ondelete="CASCADE"))
    cst: Mapped[str] = mapped_column(String(3))
    descricao: Mapped[str] = mapped_column(Text)
    indicadores: Mapped[dict[str, Any]] = mapped_column(default=dict)
    data_inicio: Mapped[date | None] = mapped_column(Date)
    data_fim: Mapped[date | None] = mapped_column(Date)


class CClassTribCode(Base):
    __tablename__ = "cclasstrib_codes"
    __table_args__ = (UniqueConstraint("version_id", "codigo", name="uq_cclasstrib_version_codigo"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ref_versions.id", ondelete="CASCADE"))
    codigo: Mapped[str] = mapped_column(String(6))
    cst: Mapped[str] = mapped_column(String(3))
    nome: Mapped[str] = mapped_column(Text)
    nome_reduzido: Mapped[str | None] = mapped_column(Text)
    perc_red_ibs: Mapped[Decimal | None] = mapped_column(Numeric(7, 4))
    perc_red_cbs: Mapped[Decimal | None] = mapped_column(Numeric(7, 4))
    tipo_aliquota: Mapped[str | None] = mapped_column(String(40))
    nro_anexo: Mapped[int | None] = mapped_column(Integer)
    url_legislacao: Mapped[str | None] = mapped_column(Text)
    texto_regulamento_cbs: Mapped[str | None] = mapped_column(Text)
    texto_regulamento_ibs: Mapped[str | None] = mapped_column(Text)
    ind_nfe: Mapped[bool] = mapped_column(Boolean, default=False)
    ind_nfce: Mapped[bool] = mapped_column(Boolean, default=False)
    ind_nfse: Mapped[bool] = mapped_column(Boolean, default=False)
    indicadores: Mapped[dict[str, Any]] = mapped_column(default=dict)
    data_inicio: Mapped[date | None] = mapped_column(Date)
    data_fim: Mapped[date | None] = mapped_column(Date)


class CClassTribCorrelacao(Base):
    """Correlação oficial cClassTrib ↔ NCM/NBS publicada junto com a tabela (anexos)."""

    __tablename__ = "cclasstrib_correlacoes"
    __table_args__ = (Index("ix_correl_version_codigo", "version_id", "codigo_ncm_nbs"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ref_versions.id", ondelete="CASCADE"))
    cclasstrib: Mapped[str] = mapped_column(String(6))
    nro_anexo: Mapped[int | None] = mapped_column(Integer)
    descricao_anexo: Mapped[str | None] = mapped_column(Text)
    codigo_ncm_nbs: Mapped[str] = mapped_column(String(12))
    tipo_codigo: Mapped[str] = mapped_column(String(3))
    tipo_permissao: Mapped[str | None] = mapped_column(String(20))
    descricao_condicao: Mapped[str | None] = mapped_column(Text)
    descricao_excecao: Mapped[str | None] = mapped_column(Text)
    observacao: Mapped[str | None] = mapped_column(Text)
    nro_item_anexo: Mapped[str | None] = mapped_column(String(20))
    descricao_item_anexo: Mapped[str | None] = mapped_column(Text)
    data_inicio: Mapped[date | None] = mapped_column(Date)
    data_fim: Mapped[date | None] = mapped_column(Date)


class LegalProvision(Base):
    """Trecho do texto legal (dispositivo) extraído da publicação oficial."""

    __tablename__ = "legal_provisions"
    __table_args__ = (
        Index("ix_legal_provisions_anexo_item", "version_id", "anexo", "item"),
        Index("ix_legal_provisions_tsv", "tsv", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ref_versions.id", ondelete="CASCADE"))
    tipo: Mapped[str] = mapped_column(String(20))  # anexo_item | artigo
    anexo: Mapped[str | None] = mapped_column(String(10))
    titulo_anexo: Mapped[str | None] = mapped_column(Text)
    item: Mapped[str | None] = mapped_column(String(20))
    artigo: Mapped[str | None] = mapped_column(String(20))
    texto: Mapped[str] = mapped_column(Text)
    codigos_citados: Mapped[list[str]] = mapped_column(ARRAY(String(20)), default=list)
    ordem: Mapped[int] = mapped_column(Integer, default=0)
    # Base normativa temporal: de qual ato é o trecho e quando ele vale.
    norma: Mapped[str] = mapped_column(String(80), default="LC 214/2025")
    vigencia_inicio: Mapped[date | None] = mapped_column(Date)
    vigencia_fim: Mapped[date | None] = mapped_column(Date)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(), nullable=True)
    tsv: Mapped[Any] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('portuguese', immutable_unaccent(coalesce(titulo_anexo, '') || ' ' || texto))",
            persisted=True,
        ),
    )


class ConditionAttribute(Base):
    """Catálogo de atributos usados nas condições legais (ex.: adicao_acucar)."""

    __tablename__ = "condition_attributes"

    chave: Mapped[str] = mapped_column(String(60), primary_key=True)
    fonte: Mapped[str] = mapped_column(String(20))  # item | empresa | operacao
    descricao: Mapped[str] = mapped_column(Text)
    pergunta: Mapped[str] = mapped_column(Text)
    valores: Mapped[list[Any]] = mapped_column(default=list)  # vazio = sim/nao
    created_at: Mapped[datetime] = created_at()


class RefSnapshot(Base):
    """Conjunto imutável de versões + regras aprovadas usado por uma auditoria."""

    __tablename__ = "ref_snapshots"

    id: Mapped[uuid.UUID] = uuid_pk()
    hash: Mapped[str] = mapped_column(String(64), unique=True)
    versoes: Mapped[dict[str, Any]] = mapped_column(default=dict)  # {fonte: version_id}
    regras_aprovadas: Mapped[list[Any]] = mapped_column(default=list)  # [rule_id]
    regras_pendentes: Mapped[list[Any]] = mapped_column(default=list)  # [rule_id]
    completude: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = created_at()
