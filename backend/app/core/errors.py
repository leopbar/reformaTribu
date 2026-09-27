"""Erros de aplicação com mensagens claras em português, sem jargão técnico."""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = structlog.get_logger()


class AppError(Exception):
    status_code = 400
    codigo = "erro"

    def __init__(
        self,
        mensagem: str,
        *,
        acao: str | None = None,
        detalhes: Any = None,
        codigo: str | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.acao = acao
        self.detalhes = detalhes
        if codigo:
            self.codigo = codigo
        if status_code:
            self.status_code = status_code


class NaoEncontrado(AppError):
    status_code = 404
    codigo = "nao_encontrado"


class NaoAutorizado(AppError):
    status_code = 401
    codigo = "nao_autenticado"


class Proibido(AppError):
    status_code = 403
    codigo = "sem_permissao"


class Conflito(AppError):
    status_code = 409
    codigo = "conflito"


class MuitasTentativas(AppError):
    status_code = 429
    codigo = "muitas_tentativas"


class Indisponivel(AppError):
    status_code = 503
    codigo = "indisponivel"


def _corpo(codigo: str, mensagem: str, acao: str | None = None, detalhes: Any = None) -> dict[str, Any]:
    corpo: dict[str, Any] = {"erro": {"codigo": codigo, "mensagem": mensagem}}
    if acao:
        corpo["erro"]["acao"] = acao
    if detalhes is not None:
        corpo["erro"]["detalhes"] = detalhes
    return corpo


_TRADUCAO_VALIDACAO = {
    "missing": "Campo obrigatório não informado.",
    "string_too_short": "Texto curto demais.",
    "string_too_long": "Texto longo demais.",
    "value_error": "Valor inválido.",
    "int_parsing": "Informe um número inteiro.",
    "decimal_parsing": "Informe um número.",
    "float_parsing": "Informe um número.",
    "uuid_parsing": "Identificador inválido.",
    "enum": "Opção inválida.",
    "literal_error": "Opção inválida.",
    "date_from_datetime_parsing": "Data inválida.",
    "date_parsing": "Data inválida.",
    "bool_parsing": "Informe verdadeiro ou falso.",
}


def instalar_tratadores(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(_corpo(exc.codigo, exc.mensagem, exc.acao, exc.detalhes), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validacao(request: Request, exc: RequestValidationError) -> JSONResponse:
        campos = []
        for e in exc.errors():
            loc = [str(p) for p in e.get("loc", []) if p not in ("body", "query", "path")]
            msg = e.get("msg", "")
            if msg.startswith("Value error, "):
                msg = msg.removeprefix("Value error, ")
            else:
                msg = _TRADUCAO_VALIDACAO.get(e.get("type", ""), "Valor inválido.")
            campos.append({"campo": ".".join(loc), "mensagem": msg})
        return JSONResponse(
            _corpo("dados_invalidos", "Alguns campos precisam de correção.", "Revise os campos indicados.", campos),
            status_code=422,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        mensagens = {
            404: "O endereço solicitado não existe.",
            405: "Operação não permitida neste endereço.",
            401: "Sua sessão expirou. Entre novamente.",
            403: "Você não tem permissão para esta ação.",
        }
        msg = (
            exc.detail
            if isinstance(exc.detail, str) and exc.status_code not in mensagens
            else mensagens.get(exc.status_code, "Não foi possível concluir a solicitação.")
        )
        return JSONResponse(_corpo("http_" + str(exc.status_code), msg), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def _inesperado(request: Request, exc: Exception) -> JSONResponse:
        log.exception("erro_inesperado", path=request.url.path)
        return JSONResponse(
            _corpo(
                "erro_interno",
                "Algo deu errado do nosso lado e a operação não foi concluída.",
                "Tente novamente em instantes. Se persistir, informe o código de rastreio ao suporte: "
                + str(getattr(request.state, "request_id", "")),
            ),
            status_code=500,
        )
