"""Middlewares ASGI: identificador de correlação, cabeçalhos de segurança e limitação de taxa."""

from __future__ import annotations

import time
import uuid

import orjson
import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import get_settings
from app.core.redis import redis_async

log = structlog.get_logger()

_CABECALHOS_SEGURANCA = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), payment=()"),
    (b"cross-origin-opener-policy", b"same-origin"),
    (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'"),
]


class RequestContextMiddleware:
    """Atribui X-Request-ID, registra a requisição (sem dados sensíveis) e adiciona cabeçalhos."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.hsts = get_settings().em_producao

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        recebido = headers.get(b"x-request-id", b"").decode()[:64]
        request_id = recebido if recebido.replace("-", "").isalnum() and recebido else uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        inicio = time.perf_counter()
        status = 500

        async def _send(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                h = list(message.get("headers", []))
                h.append((b"x-request-id", request_id.encode()))
                h.extend(_CABECALHOS_SEGURANCA)
                if self.hsts:
                    h.append((b"strict-transport-security", b"max-age=63072000; includeSubDomains"))
                message["headers"] = h
            await send(message)

        try:
            await self.app(scope, receive, _send)
        finally:
            log.info(
                "requisicao",
                metodo=scope.get("method"),
                caminho=scope.get("path"),
                status=status,
                duracao_ms=round((time.perf_counter() - inicio) * 1000, 1),
            )


class RateLimitMiddleware:
    """Janela fixa por minuto, por IP. Rotas de autenticação têm limite mais baixo."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.limite = get_settings().rate_limit_por_minuto

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path", "").startswith("/api/saude"):
            await self.app(scope, receive, send)
            return
        cliente = scope.get("client")
        ip = cliente[0] if cliente else "desconhecido"
        caminho: str = scope.get("path", "")
        grupo, limite = ("auth", 30) if caminho.startswith("/api/auth/") else ("geral", self.limite)
        janela = int(time.time() // 60)
        chave = f"rl:{grupo}:{ip}:{janela}"
        try:
            r = redis_async()
            atual = await r.incr(chave)
            if atual == 1:
                await r.expire(chave, 65)
        except Exception:  # Redis indisponível não derruba a API; apenas não limita.
            atual = 0
        if atual > limite:
            corpo = orjson.dumps(
                {
                    "erro": {
                        "codigo": "muitas_requisicoes",
                        "mensagem": "Muitas solicitações em pouco tempo.",
                        "acao": "Aguarde um minuto e tente novamente.",
                    }
                }
            )
            await send(
                {
                    "type": "http.response.start",
                    "status": 429,
                    "headers": [(b"content-type", b"application/json"), (b"retry-after", b"60")],
                }
            )
            await send({"type": "http.response.body", "body": corpo})
            return
        await self.app(scope, receive, send)
