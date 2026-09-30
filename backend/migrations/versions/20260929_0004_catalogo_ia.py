"""catálogo de IA: plataformas, modelos e modelo de cada agente; chave da tese maior

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-29 18:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Cópia do catálogo inicial (a migração não depende do código da aplicação, que pode mudar).
PROVEDORES = [
    ("anthropic", "Anthropic (Claude)", "https://api.anthropic.com"),
    ("openai", "OpenAI (GPT)", "https://api.openai.com/v1"),
    ("deepseek", "DeepSeek", "https://api.deepseek.com"),
]
MODELOS = [
    # modelo, provedor, nome, entrada, saída, cache leitura, mult. escrita, lote, esforço, ativo
    ("claude-haiku-4-5-20251001", "anthropic", "Claude Haiku 4.5", 1.00, 5.00, 0.10, 1.25, True, False, True),
    ("claude-sonnet-5", "anthropic", "Claude Sonnet 5", 2.00, 10.00, 0.20, 1.25, True, True, True),
    ("claude-opus-5-5", "anthropic", "Claude Opus 5.5", 4.00, 20.00, 0.20, 1.25, True, True, True),
    ("claude-fable-5-1", "anthropic", "Claude Fable 5.1", 10.00, 50.00, 0.25, 1.25, True, True, False),
    ("gpt-5", "openai", "GPT-5", 1.25, 10.00, 0.125, 1, False, True, True),
    ("gpt-5-mini", "openai", "GPT-5 mini", 0.25, 2.00, 0.025, 1, False, True, True),
    ("gpt-5-nano", "openai", "GPT-5 nano", 0.05, 0.40, 0.005, 1, False, True, True),
    ("gpt-5.6-sol", "openai", "GPT-5.6 Sol", 4.00, 20.00, 0.40, 1, False, True, False),
    ("gpt-4.1", "openai", "GPT-4.1", 2.00, 8.00, 0.50, 1, False, False, False),
    ("gpt-4.1-mini", "openai", "GPT-4.1 mini", 0.40, 1.60, 0.10, 1, False, False, True),
    ("gpt-4.1-nano", "openai", "GPT-4.1 nano", 0.10, 0.40, 0.025, 1, False, False, True),
    ("deepseek-flash", "deepseek", "DeepSeek Flash", 0.30, 1.20, 0.006, 1, False, False, True),
    ("deepseek-v4-pro", "deepseek", "DeepSeek V4-Pro", 1.32, 3.96, 0.044, 1, False, False, True),
]
AGENTES = [
    ("identificador", "claude-haiku-4-5-20251001", "medium"),
    ("segundo_parecer", "claude-sonnet-5", "medium"),
    ("jurista", "claude-sonnet-5", "medium"),
    ("leitor_fatos", "claude-haiku-4-5-20251001", "low"),
    ("abreviacoes", "claude-haiku-4-5-20251001", "low"),
]


def upgrade() -> None:
    op.create_table(
        "llm_provedores",
        sa.Column("provedor", sa.String(20), primary_key=True),
        sa.Column("nome", sa.String(80), nullable=False),
        sa.Column("ativo", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("chave_cifrada", sa.LargeBinary(), nullable=True),
        sa.Column("chave_final", sa.String(8), nullable=True),
        sa.Column("base_url", sa.String(300), nullable=True),
        sa.Column("testado_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("teste_ok", sa.Boolean(), nullable=True),
        sa.Column("teste_mensagem", sa.Text(), nullable=True),
        sa.Column("atualizado_por", sa.String(320), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_table(
        "llm_modelos",
        sa.Column("modelo", sa.String(80), primary_key=True),
        sa.Column("provedor", sa.String(20), sa.ForeignKey("llm_provedores.provedor"), nullable=False),
        sa.Column("nome", sa.String(120), nullable=False),
        sa.Column("preco_entrada", sa.Numeric(10, 4), nullable=False),
        sa.Column("preco_saida", sa.Numeric(10, 4), nullable=False),
        sa.Column("preco_cache_leitura", sa.Numeric(10, 4), nullable=False),
        sa.Column("mult_cache_escrita", sa.Numeric(5, 2), nullable=False, server_default="1"),
        sa.Column("suporta_lote", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("suporta_esforco", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("ativo", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("notas", sa.Text(), nullable=True),
        sa.Column("atualizado_por", sa.String(320), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_table(
        "llm_agentes",
        sa.Column("agente", sa.String(30), primary_key=True),
        sa.Column("modelo", sa.String(80), sa.ForeignKey("llm_modelos.modelo"), nullable=False),
        sa.Column("esforco", sa.String(10), nullable=False, server_default="medium"),
        sa.Column("atualizado_por", sa.String(320), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    for t in ("llm_provedores", "llm_modelos", "llm_agentes"):
        # Como a base de referência: a aplicação lê; só o papel do superadministrador escreve.
        op.execute(f"GRANT SELECT ON {t} TO reforma_app;")
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {t} TO reforma_ref;")

    op.bulk_insert(
        sa.table("llm_provedores", sa.column("provedor"), sa.column("nome"), sa.column("base_url")),
        [{"provedor": p, "nome": n, "base_url": u} for p, n, u in PROVEDORES],
    )
    cols = ("modelo", "provedor", "nome", "preco_entrada", "preco_saida", "preco_cache_leitura")
    cols += ("mult_cache_escrita", "suporta_lote", "suporta_esforco", "ativo")
    op.bulk_insert(
        sa.table("llm_modelos", *(sa.column(c) for c in cols)),
        [dict(zip(cols, m, strict=True)) for m in MODELOS],
    )
    op.bulk_insert(
        sa.table("llm_agentes", sa.column("agente"), sa.column("modelo"), sa.column("esforco")),
        [{"agente": a, "modelo": m, "esforco": e} for a, m, e in AGENTES],
    )
    # Tese substituída ("refazer com o modelo atual") guarda a chave antiga com um sufixo.
    op.alter_column("tax_theses", "chave", type_=sa.String(120), existing_nullable=False)


def downgrade() -> None:
    op.alter_column("tax_theses", "chave", type_=sa.String(64), existing_nullable=False)
    op.drop_table("llm_agentes")
    op.drop_table("llm_modelos")
    op.drop_table("llm_provedores")
