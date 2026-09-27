"""Infraestrutura de testes.

Os testes de integração usam um PostgreSQL real (banco `<POSTGRES_DB>_test`, criado pelo script de
inicialização do contêiner) com os mesmos papéis e políticas de RLS da aplicação. Rode com:

    make test          # dentro do contêiner da API

Mocks só existem aqui: a API do Claude e o serviço de embeddings são substituídos por dublês.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]


def _para_teste(url: str) -> str:
    base, _, nome = url.rpartition("/")
    return url if nome.endswith("_test") else f"{base}/{nome}_test"


# Aponta a aplicação para o banco de testes ANTES de importar qualquer módulo do app.
for var in ("DATABASE_URL", "REFERENCE_ADMIN_DATABASE_URL", "MIGRATIONS_DATABASE_URL"):
    if os.environ.get(var):
        os.environ[var] = _para_teste(os.environ[var])
os.environ.setdefault("JWT_SECRET", "segredo-de-teste-" + uuid.uuid4().hex)
os.environ["APP_ENV"] = "teste"
os.environ["COOKIE_SECURE"] = "false"
os.environ.setdefault("REDIS_URL", "redis://redis:6379/5")
os.environ["ANTHROPIC_API_KEY"] = "chave-falsa-de-teste"

BANCO_DISPONIVEL = bool(os.environ.get("MIGRATIONS_DATABASE_URL"))


@pytest.fixture(scope="session")
def banco() -> Iterator[None]:
    if not BANCO_DISPONIVEL:
        pytest.skip("Banco de testes indisponível (rode `make test` no contêiner).")
    subprocess.run([sys.executable, "-m", "app.cli", "migrate"], cwd=RAIZ, check=True, env=os.environ.copy())
    yield


@pytest.fixture
def limpo(banco: None) -> Iterator[None]:
    """Esvazia as tabelas antes do teste (como dono do schema, fora da RLS)."""
    import psycopg

    dsn = os.environ["MIGRATIONS_DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(dsn, autocommit=True) as c:
        tabelas = [
            r[0]
            for r in c.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename NOT IN ('alembic_version')"
            )
        ]
        c.execute("SET session_replication_role = replica")  # ignora gatilhos de imutabilidade na limpeza
        c.execute("TRUNCATE " + ", ".join(tabelas) + " RESTART IDENTITY CASCADE")
        c.execute("SET session_replication_role = DEFAULT")
    from app.pipeline import context

    context._CACHE.clear()
    yield


@pytest.fixture(scope="session", autouse=True)
def _fechar_pool_checkpoint() -> Iterator[None]:
    yield
    try:
        from app.pipeline.graph import pool

        if pool.cache_info().currsize:
            pool().close()
    except Exception:  # noqa: S110
        pass


def dono():  # type: ignore[no-untyped-def]
    import psycopg

    dsn = os.environ["MIGRATIONS_DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
    return psycopg.connect(dsn, autocommit=True)
