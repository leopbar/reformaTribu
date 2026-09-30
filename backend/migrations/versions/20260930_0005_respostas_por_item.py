"""respostas de perguntas em grupo passam a valer só para os itens listados (ADR 0026)

Antes, a resposta a uma pergunta feita para uma categoria do ERP (ou um NCM) virava um fato de GRUPO,
herdado por qualquer item daquela categoria, inclusive itens que chegaram depois e que a pessoa nunca
viu (ex.: "a bebida foi preparada no local? não", dada pensando na água mineral, valeu para o café
espresso). Agora a resposta vira um fato por item.

Esta migração converte os fatos de grupo ativos que vieram de perguntas: cada um vira fatos de item para
os itens da mesma auditoria e do mesmo grupo (os que estavam na pergunta quando ela foi respondida), e o
fato de grupo é desativado (o histórico fica). Itens de outras auditorias deixam de herdar a resposta e,
se precisarem dela, recebem a pergunta de novo.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-30 20:00:00
"""

import re
import unicodedata
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Cópia de `grupo_categoria` (a migração não depende do código da aplicação, que pode mudar).
def _grupo_categoria(categoria: str | None) -> str | None:
    t = unicodedata.normalize("NFKD", categoria or "").encode("ascii", "ignore").decode().lower().strip()
    c = re.sub(r"\s+", " ", t).strip()
    return f"categoria:{c[:200]}" if c else None


def upgrade() -> None:
    con = op.get_bind()
    fatos = con.execute(
        sa.text(
            "SELECT id, org_id, company_id, grupo_chave, atributo, valor, origem, evidencia, autor_id, "
            "autor_email, audit_id, pendencia_id, created_at FROM company_facts "
            "WHERE escopo = 'grupo' AND ativo AND audit_id IS NOT NULL"
        )
    ).fetchall()
    for f in fatos:
        itens = con.execute(
            sa.text(
                "SELECT codigo_interno, categoria, identidade->>'tipo_codigo' AS tipo, "
                "identidade->>'codigo' AS codigo FROM audit_items WHERE audit_id = :a"
            ),
            {"a": f.audit_id},
        ).fetchall()
        if f.grupo_chave.startswith("categoria:"):
            alvo = [i.codigo_interno for i in itens if _grupo_categoria(i.categoria) == f.grupo_chave]
        elif f.grupo_chave.startswith("familia:"):
            alvo = [i.codigo_interno for i in itens if f"familia:{i.tipo}:{i.codigo}" == f.grupo_chave]
        else:
            alvo = []
        for chave_item in dict.fromkeys(alvo):
            ja = con.execute(
                sa.text(
                    "SELECT 1 FROM company_facts WHERE company_id = :c AND escopo = 'item' AND item_chave = :i "
                    "AND atributo = :at AND ativo LIMIT 1"
                ),
                {"c": f.company_id, "i": chave_item, "at": f.atributo},
            ).first()
            if ja is not None:
                continue  # uma resposta do próprio item já prevalecia
            con.execute(
                sa.text(
                    "INSERT INTO company_facts (id, org_id, company_id, escopo, grupo_chave, item_chave, atributo, "
                    "valor, origem, evidencia, autor_id, autor_email, audit_id, pendencia_id, ativo, substitui_id, "
                    "created_at) VALUES (:id, :org, :c, 'item', NULL, :i, :at, :v, :o, :ev, :au, :ae, :a, :p, true, "
                    ":sub, :cr)"
                ),
                {
                    "id": uuid.uuid4(),
                    "org": f.org_id,
                    "c": f.company_id,
                    "i": chave_item,
                    "at": f.atributo,
                    "v": f.valor,
                    "o": f.origem,
                    "ev": ((f.evidencia or "") + " (resposta dada para o grupo; vale para os itens da pergunta)")[
                        :2000
                    ],
                    "au": f.autor_id,
                    "ae": f.autor_email,
                    "a": f.audit_id,
                    "p": f.pendencia_id,
                    "sub": f.id,
                    "cr": f.created_at,
                },
            )
        con.execute(sa.text("UPDATE company_facts SET ativo = false WHERE id = :id"), {"id": f.id})


def downgrade() -> None:
    con = op.get_bind()
    # Reativa os fatos de grupo e desativa os fatos de item criados a partir deles.
    con.execute(
        sa.text(
            "UPDATE company_facts g SET ativo = true FROM company_facts i "
            "WHERE i.substitui_id = g.id AND g.escopo = 'grupo' AND i.escopo = 'item' AND i.ativo"
        )
    )
    con.execute(
        sa.text(
            "UPDATE company_facts i SET ativo = false FROM company_facts g "
            "WHERE i.substitui_id = g.id AND g.escopo = 'grupo' AND i.escopo = 'item'"
        )
    )
