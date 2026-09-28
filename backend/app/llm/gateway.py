"""Gateway único para a API do Claude.

- Toda chamada é registrada em `llm_calls` com chave de idempotência: se o mesmo nó do mesmo
  item já tem resposta, ela é reutilizada e nada é cobrado de novo.
- Tempo real: Messages API com retentativas (backoff exponencial com jitter).
- Lote: a requisição fica "na fila" e é enviada pela tarefa coletora para a Message Batches API.
- Saídas sempre estruturadas (`output_config.format` com JSON Schema) e validadas com Pydantic.
- Somente descrição, códigos e atributos do item são enviados ao modelo. Nada de dados pessoais.
"""

from __future__ import annotations

import random
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from functools import lru_cache
from typing import Any

import anthropic
import orjson
import structlog
from pydantic import BaseModel, ValidationError
from sqlalchemy import select

from app.config import get_settings
from app.db.session import TenantContext, sync_reference_admin_session, sync_tenant_session
from app.llm import budget
from app.llm.pricing import custo_chamada
from app.llm.prompts import Prompt
from app.models import LlmCall
from app.models.enums import StatusChamadaLLM

log = structlog.get_logger()


class FalhaIA(Exception):
    """A chamada ao modelo falhou de forma definitiva (após retentativas) ou a resposta é inválida."""


class ChaveAPIAusente(FalhaIA):
    pass


@dataclass(frozen=True)
class RequisicaoLLM:
    no: str
    modelo: str
    prompt: Prompt
    conteudo_usuario: dict[str, Any]
    schema: dict[str, Any]
    validador: type[BaseModel]
    esforco: str
    chave_idempotencia: str
    org_id: uuid.UUID | None
    audit_id: uuid.UUID | None = None
    item_id: uuid.UUID | None = None
    max_tokens: int = 8000
    plataforma: bool = False  # chamadas da base de referência (sem organização)

    def params(self) -> dict[str, Any]:
        """Parâmetros da Messages API. O bloco de sistema é estável e fica em cache."""
        return {
            "model": self.modelo,
            "max_tokens": self.max_tokens,
            "system": [{"type": "text", "text": self.prompt.texto, "cache_control": {"type": "ephemeral"}}],
            "messages": [
                {
                    "role": "user",
                    "content": orjson.dumps(self.conteudo_usuario, option=orjson.OPT_SORT_KEYS).decode(),
                }
            ],
            "output_config": {
                "format": {"type": "json_schema", "schema": self.schema},
                **({"effort": self.esforco} if suporta_esforco(self.modelo) else {}),
            },
        }


def suporta_esforco(modelo: str) -> bool:
    """O parâmetro `effort` não existe nos modelos Haiku (a API recusa a requisição)."""
    return "haiku" not in modelo


@dataclass
class ResultadoLLM:
    dados: dict[str, Any]
    call_id: uuid.UUID
    custo_usd: Decimal
    reutilizado: bool
    modelo: str
    prompt_versao: str


@lru_cache
def cliente() -> anthropic.Anthropic:
    s = get_settings()
    if s.anthropic_api_key is None or not s.anthropic_api_key.get_secret_value():
        raise ChaveAPIAusente(
            "A chave da API da Anthropic não está configurada (ANTHROPIC_API_KEY). "
            "Nenhuma análise por IA pode ser feita até que ela seja definida no servidor."
        )
    # Retentativas próprias (abaixo) controlam backoff e registro; o SDK não repete sozinho.
    return anthropic.Anthropic(api_key=s.anthropic_api_key.get_secret_value(), timeout=s.llm_timeout_s, max_retries=0)


def _sessao(req: RequisicaoLLM) -> Any:
    if req.plataforma:
        return sync_reference_admin_session(TenantContext(org_id=None, platform_admin=True))
    return sync_tenant_session(TenantContext.sistema(req.org_id))


def _extrair_json(conteudo: list[Any]) -> dict[str, Any]:
    for bloco in conteudo:
        tipo = bloco.get("type") if isinstance(bloco, dict) else getattr(bloco, "type", None)
        if tipo == "text":
            texto = bloco["text"] if isinstance(bloco, dict) else bloco.text
            return orjson.loads(texto)  # type: ignore[no-any-return]
    raise FalhaIA("A resposta do modelo não trouxe conteúdo estruturado.")


def validar_resposta(req: RequisicaoLLM, mensagem: dict[str, Any]) -> dict[str, Any]:
    """Valida stop_reason e esquema. Devolve o JSON validado (como dict)."""
    stop = mensagem.get("stop_reason")
    if stop == "refusal":
        raise FalhaIA("O modelo recusou a solicitação.")
    if stop == "max_tokens":
        raise FalhaIA("A resposta do modelo foi cortada por limite de tamanho.")
    try:
        bruto = _extrair_json(mensagem.get("content", []))
        return req.validador.model_validate(bruto).model_dump()
    except (orjson.JSONDecodeError, ValidationError) as e:
        raise FalhaIA(f"A resposta do modelo não segue o formato esperado: {e}") from e


def _uso(mensagem: dict[str, Any]) -> tuple[int, int, int, int]:
    u = mensagem.get("usage") or {}
    return (
        int(u.get("input_tokens") or 0),
        int(u.get("output_tokens") or 0),
        int(u.get("cache_creation_input_tokens") or 0),
        int(u.get("cache_read_input_tokens") or 0),
    )


def registrar_resposta(call: LlmCall, mensagem: dict[str, Any], lote: bool) -> None:
    ent, sai, cw, cr = _uso(mensagem)
    call.tokens_entrada, call.tokens_saida = ent, sai
    call.tokens_cache_escrita, call.tokens_cache_leitura = cw, cr
    call.custo_usd = custo_chamada(call.modelo, ent, sai, cw, cr, lote=lote)
    call.stop_reason = mensagem.get("stop_reason")
    # Guarda só os blocos de texto (a resposta estruturada); o raciocínio não é necessário.
    call.resposta = {
        "content": [b for b in mensagem.get("content", []) if b.get("type") == "text"],
        "stop_reason": mensagem.get("stop_reason"),
        "usage": mensagem.get("usage"),
        "model": mensagem.get("model"),
    }
    call.concluido_em = datetime.now(UTC)


def estimar_custo(req: RequisicaoLLM, lote: bool = False) -> Decimal:
    entrada = (len(req.prompt.texto) + len(orjson.dumps(req.conteudo_usuario))) // 3
    return custo_chamada(req.modelo, entrada, 1500, 0, 0, lote=lote)


def resultado_existente(req: RequisicaoLLM) -> ResultadoLLM | LlmCall | None:
    """Resposta já obtida para esta chave (idempotência). Devolve a chamada se ainda pendente."""
    with _sessao(req) as s:
        call: LlmCall | None = s.scalar(select(LlmCall).where(LlmCall.chave_idempotencia == req.chave_idempotencia))
        if call is None:
            return None
        if call.status == StatusChamadaLLM.CONCLUIDA and call.resposta:
            dados = validar_resposta(req, call.resposta)
            return ResultadoLLM(dados, call.id, Decimal(call.custo_usd), True, call.modelo, call.prompt_versao)
        return call


def chamar_tempo_real(req: RequisicaoLLM) -> ResultadoLLM:
    existente = resultado_existente(req)
    if isinstance(existente, ResultadoLLM):
        return existente
    s = get_settings()
    api = cliente()

    if req.org_id and not req.plataforma:
        with _sessao(req) as sess:
            excesso = budget.checar(sess, req.org_id, estimar_custo(req))
        if excesso is not None:
            raise excesso

    with _sessao(req) as sess:
        call = sess.scalar(select(LlmCall).where(LlmCall.chave_idempotencia == req.chave_idempotencia))
        if call is None:
            call = LlmCall(
                org_id=req.org_id,
                audit_id=req.audit_id,
                item_id=req.item_id,
                no=req.no,
                modelo=req.modelo,
                prompt_versao=req.prompt.rotulo,
                modo="tempo_real",
                chave_idempotencia=req.chave_idempotencia,
                status=StatusChamadaLLM.ENVIADA,
                requisicao={"resumo": _resumo_requisicao(req)},
            )
            sess.add(call)
        call.status = StatusChamadaLLM.ENVIADA
        sess.flush()  # o id (uuid) é atribuído no flush
        call_id = call.id

    ultimo_erro: Exception | None = None
    inicio = time.perf_counter()
    mensagem: dict[str, Any] | None = None
    tentativas = 0
    for tentativa in range(1, s.llm_max_tentativas + 1):
        tentativas = tentativa
        try:
            resp = api.messages.create(**req.params())
            mensagem = resp.to_dict()
            mensagem["_request_id"] = getattr(resp, "_request_id", None)
            break
        except (
            anthropic.RateLimitError,
            anthropic.InternalServerError,
            anthropic.APIConnectionError,
            anthropic.APITimeoutError,
        ) as e:
            ultimo_erro = e
        except anthropic.APIStatusError as e:
            if e.status_code in (408, 409, 429) or e.status_code >= 500:
                ultimo_erro = e
            else:
                ultimo_erro = e
                break
        espera = _espera(tentativa, ultimo_erro)
        log.warning(
            "llm_retentativa",
            no=req.no,
            tentativa=tentativa,
            espera_s=round(espera, 1),
            erro=type(ultimo_erro).__name__,
        )
        time.sleep(espera)

    latencia = int((time.perf_counter() - inicio) * 1000)
    # A falha é gravada ANTES de ser propagada (uma exceção dentro da sessão desfaria o registro).
    falha: FalhaIA | None = None
    with _sessao(req) as sess:
        call = sess.get(LlmCall, call_id)
        assert call is not None
        call.tentativas = tentativas
        call.latencia_ms = latencia
        if mensagem is None:
            call.status = StatusChamadaLLM.FALHOU
            call.erro = f"{type(ultimo_erro).__name__}: {str(ultimo_erro)[:500]}"
            falha = FalhaIA("Não foi possível obter resposta do modelo após várias tentativas.")
        else:
            call.request_id = mensagem.get("_request_id")
            registrar_resposta(call, mensagem, lote=False)
            try:
                dados = validar_resposta(req, mensagem)
                call.status = StatusChamadaLLM.CONCLUIDA
                resultado = ResultadoLLM(dados, call.id, Decimal(call.custo_usd), False, req.modelo, req.prompt.rotulo)
            except FalhaIA as e:
                call.status = StatusChamadaLLM.FALHOU
                call.erro = str(e)[:1000]
                falha = e
    if falha is not None:
        raise falha from ultimo_erro
    return resultado


def enfileirar_lote(req: RequisicaoLLM) -> uuid.UUID:
    """Registra a requisição para envio pela Batch API. Idempotente."""
    with _sessao(req) as sess:
        existente: LlmCall | None = sess.scalar(
            select(LlmCall).where(LlmCall.chave_idempotencia == req.chave_idempotencia)
        )
        if existente is not None:
            call = existente
            if call.status == StatusChamadaLLM.FALHOU:
                call.status = StatusChamadaLLM.NA_FILA
                call.batch_id = None
                call.requisicao = {"params": req.params(), "resumo": _resumo_requisicao(req)}
            return call.id
        call = LlmCall(
            org_id=req.org_id,
            audit_id=req.audit_id,
            item_id=req.item_id,
            no=req.no,
            modelo=req.modelo,
            prompt_versao=req.prompt.rotulo,
            modo="lote",
            chave_idempotencia=req.chave_idempotencia,
            status=StatusChamadaLLM.NA_FILA,
            requisicao={"params": req.params(), "resumo": _resumo_requisicao(req)},
        )
        sess.add(call)
        sess.flush()
        return call.id


def _resumo_requisicao(req: RequisicaoLLM) -> dict[str, Any]:
    return {
        "no": req.no,
        "modelo": req.modelo,
        "prompt": req.prompt.rotulo,
        "esforco": req.esforco,
        "conteudo": req.conteudo_usuario,
    }


def _espera(tentativa: int, erro: Exception | None) -> float:
    if isinstance(erro, anthropic.APIStatusError):
        ra = erro.response.headers.get("retry-after") if erro.response is not None else None
        if ra:
            try:
                return min(float(ra), 120.0) + random.uniform(0, 1)
            except ValueError:
                pass
    return float(min(2**tentativa, 60)) + random.uniform(0, 1.5)
