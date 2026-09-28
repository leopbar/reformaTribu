"""analista fiscal: fatos, teses por família, perguntas, perfis tributários e base normativa temporal

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-28 12:10:20.978633
"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NOVAS_TABELAS = ("company_facts", "pendencias", "tax_theses", "tax_profiles")

# Resultados do desenho anterior viram "revisão do contador": foram decididos por outro critério.
CONVERSAO_STATUS = """
UPDATE audit_items SET status = 'revisao_contador', nivel_revisao = 'contador'
 WHERE status IN ('confirmado', 'corrigido', 'analise_humana');
"""


def _ts() -> list[sa.Column]:  # type: ignore[type-arg]
    return [sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)]


def _tenant(tabela: str) -> list[sa.Column | sa.ForeignKeyConstraint]:  # type: ignore[type-arg]
    return [
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], name=op.f(f"fk_{tabela}_org_id_organizations"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{tabela}")),
    ]


def upgrade() -> None:
    jsonb = postgresql.JSONB(astext_type=sa.Text())
    op.create_table(
        "company_facts",
        *_tenant("company_facts"),
        sa.Column("company_id", sa.UUID(), nullable=False),
        sa.Column("escopo", sa.String(length=10), nullable=False),
        sa.Column("grupo_chave", sa.String(length=250), nullable=True),
        sa.Column("item_chave", sa.String(length=80), nullable=True),
        sa.Column("atributo", sa.String(length=80), nullable=False),
        sa.Column("valor", sa.String(length=200), nullable=False),
        sa.Column("origem", sa.String(length=20), nullable=False),
        sa.Column("evidencia", sa.Text(), nullable=True),
        sa.Column("autor_id", sa.UUID(), nullable=True),
        sa.Column("autor_email", sa.String(length=320), nullable=True),
        sa.Column("audit_id", sa.UUID(), nullable=True),
        sa.Column("pendencia_id", sa.UUID(), nullable=True),
        sa.Column("ativo", sa.Boolean(), nullable=False),
        sa.Column("substitui_id", sa.UUID(), nullable=True),
        *_ts(),
        sa.ForeignKeyConstraint(
            ["audit_id"], ["audits.id"], name=op.f("fk_company_facts_audit_id_audits"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], name=op.f("fk_company_facts_company_id_companies"), ondelete="CASCADE"
        ),
    )
    op.create_index("ix_company_facts_busca", "company_facts", ["company_id", "atributo", "ativo"])
    op.create_index("ix_company_facts_item", "company_facts", ["company_id", "item_chave"])
    op.create_index(op.f("ix_company_facts_org_id"), "company_facts", ["org_id"])

    op.create_table(
        "pendencias",
        *_tenant("pendencias"),
        sa.Column("audit_id", sa.UUID(), nullable=False),
        sa.Column("company_id", sa.UUID(), nullable=False),
        sa.Column("atributo", sa.String(length=80), nullable=False),
        sa.Column("escopo", sa.String(length=10), nullable=False),
        sa.Column("grupo_chave", sa.String(length=250), nullable=False, server_default=""),
        sa.Column("grupo_rotulo", sa.String(length=300), nullable=True),
        sa.Column("pergunta", sa.Text(), nullable=False),
        sa.Column("motivo", sa.Text(), nullable=True),
        sa.Column("opcoes", jsonb, nullable=False, server_default="[]"),
        sa.Column("nivel", sa.String(length=20), nullable=False, server_default="operacional"),
        sa.Column("item_ids", postgresql.ARRAY(sa.UUID()), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="aberta"),
        sa.Column("resposta", sa.String(length=200), nullable=True),
        sa.Column("respostas_itens", jsonb, nullable=False, server_default="{}"),
        sa.Column("respondido_por", sa.UUID(), nullable=True),
        sa.Column("respondido_por_email", sa.String(length=320), nullable=True),
        sa.Column("respondido_em", sa.DateTime(timezone=True), nullable=True),
        *_ts(),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["audit_id"], ["audits.id"], name=op.f("fk_pendencias_audit_id_audits"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], name=op.f("fk_pendencias_company_id_companies"), ondelete="CASCADE"
        ),
        sa.UniqueConstraint("audit_id", "atributo", "escopo", "grupo_chave", name="uq_pendencias_pergunta"),
    )
    op.create_index("ix_pendencias_audit_status", "pendencias", ["audit_id", "status"])
    op.create_index(op.f("ix_pendencias_org_id"), "pendencias", ["org_id"])

    op.create_table(
        "tax_theses",
        *_tenant("tax_theses"),
        sa.Column("company_id", sa.UUID(), nullable=False),
        sa.Column("audit_id", sa.UUID(), nullable=True),
        sa.Column("chave", sa.String(length=64), nullable=False),
        sa.Column("tipo_codigo", sa.String(length=3), nullable=False),
        sa.Column("codigo", sa.String(length=12), nullable=False),
        sa.Column("cenario", sa.String(length=40), nullable=False),
        sa.Column("data_referencia", sa.Date(), nullable=False),
        sa.Column("snapshot_id", sa.UUID(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("evidencias", jsonb, nullable=False, server_default="{}"),
        sa.Column("resultado", jsonb, nullable=False, server_default="{}"),
        sa.Column("validacao", jsonb, nullable=False, server_default="{}"),
        sa.Column("fatos_empresa", jsonb, nullable=False, server_default="{}"),
        sa.Column("llm_call_id", sa.UUID(), nullable=True),
        sa.Column("modelo", sa.String(length=80), nullable=True),
        sa.Column("prompt_versao", sa.String(length=60), nullable=True),
        sa.Column("erro", sa.Text(), nullable=True),
        sa.Column("aprovada_por", sa.UUID(), nullable=True),
        sa.Column("aprovada_por_email", sa.String(length=320), nullable=True),
        sa.Column("aprovada_em", sa.DateTime(timezone=True), nullable=True),
        *_ts(),
        sa.ForeignKeyConstraint(
            ["audit_id"], ["audits.id"], name=op.f("fk_tax_theses_audit_id_audits"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], name=op.f("fk_tax_theses_company_id_companies"), ondelete="CASCADE"
        ),
        sa.UniqueConstraint("org_id", "chave", name="uq_tax_theses_org_chave"),
    )
    op.create_index(op.f("ix_tax_theses_company_id"), "tax_theses", ["company_id"])
    op.create_index(op.f("ix_tax_theses_org_id"), "tax_theses", ["org_id"])

    op.create_table(
        "tax_profiles",
        *_tenant("tax_profiles"),
        sa.Column("company_id", sa.UUID(), nullable=False),
        sa.Column("audit_id", sa.UUID(), nullable=False),
        sa.Column("item_id", sa.UUID(), nullable=False),
        sa.Column("codigo_interno", sa.String(length=80), nullable=False),
        sa.Column("cenario", sa.String(length=40), nullable=False),
        sa.Column("vigencia", sa.Date(), nullable=False),
        sa.Column("versao", sa.Integer(), nullable=False),
        sa.Column("ativo", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("nivel_revisao", sa.String(length=20), nullable=True),
        sa.Column("tipo_codigo", sa.String(length=3), nullable=True),
        sa.Column("codigo", sa.String(length=12), nullable=True),
        sa.Column("cst", sa.String(length=3), nullable=True),
        sa.Column("cclasstrib", sa.String(length=6), nullable=True),
        sa.Column("perc_red_ibs", sa.Numeric(precision=7, scale=4), nullable=True),
        sa.Column("perc_red_cbs", sa.Numeric(precision=7, scale=4), nullable=True),
        sa.Column("imposto_seletivo", sa.String(length=20), nullable=True),
        sa.Column("hipotese", sa.String(length=20), nullable=True),
        sa.Column("conclusao", sa.Text(), nullable=True),
        sa.Column("confianca_global", sa.String(length=15), nullable=True),
        sa.Column("dimensoes", jsonb, nullable=False, server_default="{}"),
        sa.Column("registro", jsonb, nullable=False, server_default="{}"),
        sa.Column("thesis_id", sa.UUID(), nullable=True),
        sa.Column("motivo_versao", sa.String(length=200), nullable=True),
        *_ts(),
        sa.ForeignKeyConstraint(
            ["audit_id"], ["audits.id"], name=op.f("fk_tax_profiles_audit_id_audits"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], name=op.f("fk_tax_profiles_company_id_companies"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["item_id"], ["audit_items.id"], name=op.f("fk_tax_profiles_item_id_audit_items"), ondelete="CASCADE"
        ),
    )
    op.create_index(op.f("ix_tax_profiles_audit_id"), "tax_profiles", ["audit_id"])
    op.create_index("ix_tax_profiles_item_ativo", "tax_profiles", ["item_id", "ativo"])
    op.create_index(op.f("ix_tax_profiles_org_id"), "tax_profiles", ["org_id"])

    novas_colunas_item = [
        sa.Column("cenario", sa.String(length=40), nullable=False, server_default="venda_consumidor"),
        sa.Column("identidade", jsonb, nullable=False, server_default="{}"),
        sa.Column("thesis_id", sa.UUID(), nullable=True),
        sa.Column("hipotese", sa.String(length=20), nullable=True),
        sa.Column("conclusao", sa.Text(), nullable=True),
        sa.Column("fundamentos", jsonb, nullable=False, server_default="[]"),
        sa.Column("fatos_usados", jsonb, nullable=False, server_default="[]"),
        sa.Column("dimensoes", jsonb, nullable=False, server_default="{}"),
        sa.Column("confianca_global", sa.String(length=15), nullable=True),
        sa.Column("nivel_revisao", sa.String(length=20), nullable=True),
        sa.Column("perc_red_ibs", sa.Numeric(precision=7, scale=4), nullable=True),
        sa.Column("perc_red_cbs", sa.Numeric(precision=7, scale=4), nullable=True),
        sa.Column("is_situacao", sa.String(length=20), nullable=True),
        sa.Column("perfil_versao", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("aprovado_automaticamente", sa.Boolean(), nullable=False, server_default=sa.false()),
    ]
    for c in novas_colunas_item:
        op.add_column("audit_items", c)
    op.add_column("companies", sa.Column("segmento", sa.String(length=40), nullable=True))
    op.add_column(
        "org_settings", sa.Column("aprovacao_automatica", sa.Boolean(), nullable=False, server_default=sa.true())
    )

    # Base normativa temporal (a dimensão do vetor é ajustada pelo comando `migrate`).
    op.add_column(
        "legal_provisions", sa.Column("norma", sa.String(length=80), nullable=False, server_default="LC 214/2025")
    )
    op.add_column("legal_provisions", sa.Column("vigencia_inicio", sa.Date(), nullable=True))
    op.add_column("legal_provisions", sa.Column("vigencia_fim", sa.Date(), nullable=True))
    op.add_column("legal_provisions", sa.Column("embedding", pgvector.sqlalchemy.vector.VECTOR(), nullable=True))
    op.add_column(
        "legal_provisions",
        sa.Column(
            "tsv",
            postgresql.TSVECTOR(),
            sa.Computed(
                "to_tsvector('portuguese', immutable_unaccent(coalesce(titulo_anexo, '') || ' ' || texto))",
                persisted=True,
            ),
            nullable=False,
        ),
    )
    op.create_index("ix_legal_provisions_tsv", "legal_provisions", ["tsv"], postgresql_using="gin")
    op.execute("UPDATE ref_versions SET embeddings_status = 'pendente' WHERE fonte = 'lc214' AND status = 'ativa'")

    for t in NOVAS_TABELAS:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {t} TO reforma_app;")
        op.execute(
            f"""
ALTER TABLE {t} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {t} FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON {t}
  USING (org_id = app_org_id()) WITH CHECK (org_id = app_org_id());
"""
        )
    op.execute(CONVERSAO_STATUS)


def downgrade() -> None:
    op.drop_index("ix_legal_provisions_tsv", table_name="legal_provisions")
    for c in ("tsv", "embedding", "vigencia_fim", "vigencia_inicio", "norma"):
        op.drop_column("legal_provisions", c)
    op.drop_column("org_settings", "aprovacao_automatica")
    op.drop_column("companies", "segmento")
    for c in (
        "aprovado_automaticamente",
        "perfil_versao",
        "is_situacao",
        "perc_red_cbs",
        "perc_red_ibs",
        "nivel_revisao",
        "confianca_global",
        "dimensoes",
        "fatos_usados",
        "fundamentos",
        "conclusao",
        "hipotese",
        "thesis_id",
        "identidade",
        "cenario",
    ):
        op.drop_column("audit_items", c)
    for t in reversed(NOVAS_TABELAS):
        op.drop_table(t)
