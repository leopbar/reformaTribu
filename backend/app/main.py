"""Aplicação FastAPI."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from sqlalchemy import text

from app.api import analise, audits, auth, dashboard, exports, fluxo, ia, orgs, reference, review
from app.config import get_settings
from app.core.errors import instalar_tratadores
from app.core.logging import configurar_logs
from app.core.middleware import RateLimitMiddleware, RequestContextMiddleware
from app.core.redis import redis_async
from app.db.session import tenant_session

s = get_settings()
configurar_logs(s.log_level)

app = FastAPI(
    title="Auditor Fiscal de Cadastros — API",
    version="1.0.0",
    description="Auditoria de NCM/NBS, enquadramento na LC 214/2025 e sugestão de CST/cClassTrib. "
    "Ferramenta de apoio à decisão: a responsabilidade técnica é do profissional responsável.",
    docs_url=None if s.em_producao else "/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
)

instalar_tratadores(app)
app.add_middleware(GZipMiddleware, minimum_size=2048)
app.add_middleware(
    CORSMiddleware,
    allow_origins=s.cors_origens,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-CSRF-Token", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(RequestContextMiddleware)

api = APIRouter(prefix="/api")
for r in (
    auth.router,
    orgs.router,
    dashboard.router,
    audits.router,
    review.router,
    analise.router,
    fluxo.router,
    ia.router,
    exports.router,
    reference.router,
):
    api.include_router(r)


@api.get("/saude", tags=["infra"])
async def saude() -> dict[str, Any]:
    """Verificação de saúde (banco e Redis)."""
    estado: dict[str, Any] = {"api": "ok"}
    try:
        async with tenant_session(None) as sess:
            await sess.execute(text("SELECT 1"))
        estado["banco"] = "ok"
    except Exception:
        estado["banco"] = "indisponivel"
    try:
        await redis_async().ping()
        estado["redis"] = "ok"
    except Exception:
        estado["redis"] = "indisponivel"
    return estado


app.include_router(api)
