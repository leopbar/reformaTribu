"""status do item com até 30 caracteres (aguardando_informacao)

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-28 12:40:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("audit_items", "status", type_=sa.String(length=30), existing_nullable=False)


def downgrade() -> None:
    op.alter_column("audit_items", "status", type_=sa.String(length=20), existing_nullable=False)
