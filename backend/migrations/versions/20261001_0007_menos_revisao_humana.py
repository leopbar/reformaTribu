"""menos revisão humana: pausa por falha da IA, ajuste de cadastro e itens parecidos aprovados (ADR 0029)

- `sys_orgs_com_trabalho` passa a incluir auditorias pausadas porque a plataforma de IA não respondeu
  (`pausada_ia`), para a tarefa periódica retomá-las;
- `audit_items.ajuste_cadastro` / `ajuste_cadastro_status`: o NCM/NBS a confirmar no cadastro quando a
  dúvida não muda o imposto (a classificação do IBS/CBS sai; o código vai para a lista "Ajustes de
  cadastro");
- `approved_memory.embedding`: vetor da descrição aprovada por uma pessoa, para achar itens parecidos.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-01 20:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _funcao(status: str) -> None:
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION public.sys_orgs_com_trabalho()
         RETURNS TABLE(org_id uuid)
         LANGUAGE sql STABLE SECURITY DEFINER
         SET search_path TO 'public'
        AS $function$
            SELECT DISTINCT a.org_id FROM audits a WHERE a.status IN ({status})
            UNION
            SELECT DISTINCT c.org_id FROM llm_calls c WHERE c.status IN ('na_fila', 'enviada') AND c.org_id IS NOT NULL
        $function$
        """
    )


def upgrade() -> None:
    _funcao("'processando', 'aguardando_lote', 'pausada_orcamento', 'pausada_ia'")
    op.add_column(
        "audit_items",
        sa.Column(
            "ajuste_cadastro",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column("audit_items", sa.Column("ajuste_cadastro_status", sa.String(length=20), nullable=True))
    op.create_index("ix_audit_items_audit_ajuste", "audit_items", ["audit_id", "ajuste_cadastro_status"], unique=False)
    op.execute("ALTER TABLE approved_memory ADD COLUMN embedding vector")


def downgrade() -> None:
    op.execute("ALTER TABLE approved_memory DROP COLUMN embedding")
    op.drop_index("ix_audit_items_audit_ajuste", table_name="audit_items")
    op.drop_column("audit_items", "ajuste_cadastro_status")
    op.drop_column("audit_items", "ajuste_cadastro")
    _funcao("'processando', 'aguardando_lote', 'pausada_orcamento'")
