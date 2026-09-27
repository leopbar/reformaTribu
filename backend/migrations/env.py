"""Ambiente do Alembic. Migrações rodam com o papel dono do schema (MIGRATIONS_DATABASE_URL)."""

from __future__ import annotations

import os

from alembic import context
from sqlalchemy import create_engine, pool

import app.models  # noqa: F401  (registra os modelos)
from app.db.base import Base

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    url = os.environ.get("MIGRATIONS_DATABASE_URL") or config.get_main_option("sqlalchemy.url")
    if not url:
        raise RuntimeError("Defina MIGRATIONS_DATABASE_URL para rodar migrações.")
    return url


def _include_object(obj, name, type_, reflected, compare_to):  # type: ignore[no-untyped-def]
    # Tabelas do checkpoint do LangGraph são gerenciadas pela própria biblioteca.
    if type_ == "table" and name and name.startswith("checkpoint"):
        return False
    return True


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True, include_object=_include_object)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata, include_object=_include_object, compare_type=True
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
