"""memória de decisões: o enquadramento que pessoas aprovaram por código, cenário e ramo (ADR 0028)

Cria a tabela `decision_memory` (isolada por organização) e a preenche com os itens já aprovados por
pessoas, para que as decisões tomadas antes desta versão também contem.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-30 23:00:00
"""

import json
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Cópia de `decisoes.chave_fatos` (a migração não depende do código da aplicação, que pode mudar).
def _chave_fatos(fatos: list[dict] | None) -> str:
    pares = {
        str(f.get("atributo") or "").strip().lower(): str(f.get("valor") or "").strip().lower()
        for f in fatos or []
        if f.get("atributo")
    }
    return ";".join(f"{k}={v}" for k, v in sorted(pares.items()))


def upgrade() -> None:
    jsonb = postgresql.JSONB(astext_type=sa.Text())
    op.create_table(
        "decision_memory",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("company_id", sa.UUID(), nullable=False),
        sa.Column("audit_id", sa.UUID(), nullable=False),
        sa.Column("item_id", sa.UUID(), nullable=False),
        sa.Column("review_id", sa.UUID(), nullable=True),
        sa.Column("segmento", sa.String(length=40), nullable=True),
        sa.Column("cenario", sa.String(length=40), nullable=False),
        sa.Column("tipo_codigo", sa.String(length=3), nullable=False),
        sa.Column("codigo", sa.String(length=12), nullable=False),
        sa.Column("cclasstrib", sa.String(length=6), nullable=False),
        sa.Column("cst", sa.String(length=3), nullable=True),
        sa.Column("imposto_seletivo", sa.String(length=20), nullable=True),
        sa.Column("fatos_chave", sa.Text(), nullable=False),
        sa.Column("fatos", jsonb, nullable=False),
        sa.Column("dispositivo", sa.Text(), nullable=True),
        sa.Column("origem", sa.String(length=20), nullable=False),
        sa.Column("peso", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("user_email", sa.String(length=320), nullable=True),
        sa.Column("ativo", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], name=op.f("fk_decision_memory_org_id_organizations"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], name=op.f("fk_decision_memory_company_id_companies"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["audit_id"], ["audits.id"], name=op.f("fk_decision_memory_audit_id_audits"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["item_id"], ["audit_items.id"], name=op.f("fk_decision_memory_item_id_audit_items"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_decision_memory")),
    )
    op.create_index(op.f("ix_decision_memory_org_id"), "decision_memory", ["org_id"])
    op.create_index("ix_decision_memory_busca", "decision_memory", ["tipo_codigo", "codigo", "cenario", "ativo"])
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON decision_memory TO reforma_app;")
    op.execute(
        """
ALTER TABLE decision_memory ENABLE ROW LEVEL SECURITY;
ALTER TABLE decision_memory FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON decision_memory
  USING (org_id = app_org_id()) WITH CHECK (org_id = app_org_id());
"""
    )

    # Itens já aprovados por pessoas (não os automáticos), exceto os decididos pela operação.
    con = op.get_bind()
    itens = con.execute(
        sa.text(
            "SELECT i.id, i.org_id, i.company_id, i.audit_id, i.cenario, i.final_tipo_codigo, i.final_codigo, "
            "i.final_cclasstrib, i.final_cst, i.final_dispositivo, i.is_situacao, i.fatos_usados, i.hipotese, c.segmento, "
            "r.id AS review_id, r.user_id, r.user_email "
            "FROM audit_items i JOIN companies c ON c.id = i.company_id "
            "JOIN LATERAL (SELECT x.id, x.user_id, x.user_email FROM item_reviews x WHERE x.item_id = i.id "
            "  AND x.acao = 'aprovar' AND NOT EXISTS (SELECT 1 FROM item_reviews d WHERE d.desfaz_review_id = x.id) "
            "  ORDER BY x.created_at DESC LIMIT 1) r ON true "
            "WHERE i.revisao_status = 'aprovado' AND NOT i.aprovado_automaticamente "
            "AND i.final_cclasstrib IS NOT NULL AND i.final_codigo IS NOT NULL "
            "AND coalesce(i.hipotese, '') NOT LIKE 'OP-%'"
        )
    ).fetchall()
    for i in itens:
        manual = i.hipotese == "manual"
        con.execute(
            sa.text(
                "INSERT INTO decision_memory (id, org_id, company_id, audit_id, item_id, review_id, segmento, "
                "cenario, tipo_codigo, codigo, cclasstrib, cst, imposto_seletivo, fatos_chave, fatos, dispositivo, origem, "
                "peso, user_id, user_email, ativo) VALUES (:id, :org, :c, :a, :i, :r, :seg, :cen, :tc, :cod, "
                ":cct, :cst, :is_, :fc, CAST(:f AS jsonb), :disp, :o, :p, :u, :ue, true)"
            ),
            {
                "id": uuid.uuid4(),
                "org": i.org_id,
                "c": i.company_id,
                "a": i.audit_id,
                "i": i.id,
                "r": i.review_id,
                "seg": i.segmento,
                "cen": i.cenario,
                "tc": i.final_tipo_codigo or "ncm",
                "cod": i.final_codigo,
                "cct": i.final_cclasstrib,
                "cst": i.final_cst,
                "is_": "sujeito" if i.is_situacao == "sujeito" else "nao_sujeito",
                "fc": _chave_fatos(i.fatos_usados),
                "f": _json(i.fatos_usados),
                "disp": i.final_dispositivo,
                "o": "correcao" if manual else "aprovacao",
                "p": 2 if manual else 1,
                "u": i.user_id,
                "ue": i.user_email,
            },
        )


def _json(fatos: list[dict] | None) -> str:
    return json.dumps([{"atributo": f.get("atributo"), "valor": f.get("valor")} for f in fatos or []])


def downgrade() -> None:
    op.drop_table("decision_memory")
