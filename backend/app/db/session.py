"""Engines, sessões e contexto de tenant (Row-Level Security).

Toda transação aberta por uma sessão executa `set_config('app.org_id', ..., true)` com o
contexto guardado em `session.info["tenant"]`. As políticas de RLS no PostgreSQL leem esses
valores; sem contexto, nenhuma linha de tenant fica visível.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


@dataclass(frozen=True)
class TenantContext:
    org_id: uuid.UUID | None
    user_id: uuid.UUID | None = None
    platform_admin: bool = False

    @staticmethod
    def sistema(org_id: uuid.UUID | None) -> TenantContext:
        """Contexto usado por tarefas em segundo plano que agem em nome de uma organização."""
        return TenantContext(org_id=org_id, user_id=None, platform_admin=False)


_SET_CONTEXT = text(
    "SELECT set_config('app.org_id', :org, true), set_config('app.user_id', :usr, true), "
    "set_config('app.platform_admin', :adm, true)"
)


@event.listens_for(Session, "after_begin")
def _aplicar_contexto(session: Session, transaction: Any, connection: Any) -> None:
    ctx: TenantContext | None = session.info.get("tenant")
    connection.execute(
        _SET_CONTEXT,
        {
            "org": str(ctx.org_id) if ctx and ctx.org_id else "",
            "usr": str(ctx.user_id) if ctx and ctx.user_id else "",
            "adm": "true" if ctx and ctx.platform_admin else "false",
        },
    )


def _engine_kwargs() -> dict[str, Any]:
    s = get_settings()
    return {"pool_size": s.db_pool_size, "max_overflow": s.db_pool_size, "pool_pre_ping": True}


@lru_cache
def async_engine() -> AsyncEngine:
    return create_async_engine(get_settings().database_url, **_engine_kwargs())


@lru_cache
def async_ref_engine() -> AsyncEngine:
    return create_async_engine(get_settings().reference_admin_database_url, pool_size=3, pool_pre_ping=True)


@lru_cache
def sync_engine() -> Engine:
    return create_engine(get_settings().database_url, **_engine_kwargs())


@lru_cache
def sync_ref_engine() -> Engine:
    return create_engine(get_settings().reference_admin_database_url, pool_size=3, pool_pre_ping=True)


@lru_cache
def _async_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(async_engine(), expire_on_commit=False)


@lru_cache
def _async_ref_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(async_ref_engine(), expire_on_commit=False)


@lru_cache
def _sync_factory() -> sessionmaker[Session]:
    return sessionmaker(sync_engine(), expire_on_commit=False)


@lru_cache
def _sync_ref_factory() -> sessionmaker[Session]:
    return sessionmaker(sync_ref_engine(), expire_on_commit=False)


@asynccontextmanager
async def tenant_session(ctx: TenantContext | None) -> AsyncIterator[AsyncSession]:
    """Sessão assíncrona com o contexto de tenant aplicado. Faz commit ao sair sem erro."""
    async with _async_factory()() as session:
        session.info["tenant"] = ctx
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise


@asynccontextmanager
async def reference_admin_session(ctx: TenantContext | None) -> AsyncIterator[AsyncSession]:
    """Sessão com o papel que pode escrever na base de referência (só superadministrador)."""
    async with _async_ref_factory()() as session:
        session.info["tenant"] = ctx
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise


@contextmanager
def sync_tenant_session(ctx: TenantContext | None) -> Iterator[Session]:
    with _sync_factory()() as session:
        session.info["tenant"] = ctx
        try:
            yield session
            session.commit()
        except BaseException:
            session.rollback()
            raise


@contextmanager
def sync_reference_admin_session(ctx: TenantContext | None = None) -> Iterator[Session]:
    with _sync_ref_factory()() as session:
        session.info["tenant"] = ctx
        try:
            yield session
            session.commit()
        except BaseException:
            session.rollback()
            raise
