"""Eventos de progresso via Redis pub/sub (consumidos pelo endpoint SSE)."""

from __future__ import annotations

import uuid
from typing import Any

import orjson

from app.core.redis import redis_sync


def canal_auditoria(audit_id: uuid.UUID | str) -> str:
    return f"eventos:auditoria:{audit_id}"


def publicar(audit_id: uuid.UUID | str, tipo: str, dados: dict[str, Any] | None = None) -> None:
    try:
        redis_sync().publish(canal_auditoria(audit_id), orjson.dumps({"tipo": tipo, **(dados or {})}).decode())
    except Exception:  # noqa: S110  (eventos são melhor-esforço; o estado real está no banco)
        pass
