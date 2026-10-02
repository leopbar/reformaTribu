"""Gateway único para as plataformas de IA (Anthropic, OpenAI, DeepSeek).

- Toda chamada é registrada em `llm_calls` com chave de idempotência: se o mesmo nó do mesmo
  item já tem resposta, ela é reutilizada e nada é cobrado de novo.
- Tempo real: a plataforma do modelo (`provedores.py`) com retentativas (backoff exponencial com jitter).
- Lote: só modelos da Anthropic (Message Batches API); os demais saem em tempo real.
- Saídas sempre estruturadas e validadas com Pydantic, qualquer que seja o modelo.
- Somente descrição, códigos e atributos do item são enviados ao modelo. Nada de dados pessoais.
"""

from __future__ import annotations

import random
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import anthropic
import orjson
import structlog
from pydantic import BaseModel, ValidationError
from sqlalchemy import select

from app.config import get_settings
from app.db.session import TenantContext, sync_reference_admin_session, sync_tenant_session
from app.llm import budget, catalogo, provedores
from app.llm.pricing import custo_chamada
from app.llm.prompts import Prompt
from app.models import LlmCall
from app.models.enums import StatusChamadaLLM

log = structlog.get_logger()


class FalhaIA(Exception):
    """A chamada ao modelo falhou de forma definitiva (após retentativas) ou a resposta é inválida."""


class ChaveAPIAusente(FalhaIA):
    pass


class IAIndisponivel(FalhaIA):
    """A plataforma de IA não respondeu: sem créditos, fora do ar, limite de uso ou chave recusada.

    Não é dúvida sobre o item: a análise espera a plataforma voltar, em vez de seguir por um caminho
    de reserva ou mandar o item para uma pessoa (ADR 0029)."""


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
        """Parâmetros da Messages API (usados pelo lote, que só existe para a Anthropic)."""
        return provedores.params_anthropic(self)


def suporta_lote(modelo: str) -> bool:
    return catalogo.suporta_lote(modelo)


@dataclass
class ResultadoLLM:
    dados: dict[str, Any]
    call_id: uuid.UUID
    custo_usd: Decimal
    reutilizado: bool
    modelo: str
    prompt_versao: str


def cliente() -> anthropic.Anthropic:
    """Cliente da Anthropic (lote e chamadas em tempo real de modelos Claude)."""
    try:
        return provedores.cliente_anthropic()
    except provedores.SemChave as e:
        raise ChaveAPIAusente(str(e)) from e


cliente.cache_clear = provedores._cliente_anthropic.cache_clear  # type: ignore[attr-defined]


def verificar_chaves(modelos_usados: list[str]) -> None:
    """Falha cedo (antes de iniciar a auditoria) se falta a chave de alguma plataforma necessária."""
    faltando = sorted(
        {
            catalogo.PROVEDORES.get(p, {}).get("nome", p)
            for p in {catalogo.provedor_de(m) for m in modelos_usados}
            if not catalogo.credencial(p)[0]
        }
    )
    if faltando:
        raise ChaveAPIAusente(
            "Falta a chave de API de: " + ", ".join(faltando) + ". Nenhuma análise por IA pode ser feita "
            "até que o superadministrador a cadastre em Chaves de API."
        )


def _chamar(req: RequisicaoLLM) -> dict[str, Any]:
    """Uma chamada à plataforma do modelo. Modelos Claude passam por `cliente()` (substituível nos testes)."""
    if catalogo.provedor_de(req.modelo) != "anthropic":
        try:
            return provedores.chamar(req)
        except provedores.SemChave as e:
            raise ChaveAPIAusente(str(e)) from e
    api = cliente()
    try:
        resp = api.messages.create(**req.params())
    except (anthropic.RateLimitError, anthropic.InternalServerError, anthropic.APIConnectionError) as e:
        raise provedores.ErroTransitorio(f"{type(e).__name__}: {e}", _retry_after(e)) from e
    except anthropic.APIStatusError as e:
        if e.status_code in (408, 409, 429) or e.status_code >= 500:
            raise provedores.ErroTransitorio(f"{type(e).__name__}: {e}", _retry_after(e)) from e
        raise provedores.ErroDefinitivo(f"{type(e).__name__}: {e}") from e
    mensagem: dict[str, Any] = resp.to_dict()
    mensagem["_request_id"] = getattr(resp, "_request_id", None)
    return mensagem


def _retry_after(e: Exception) -> float | None:
    resp = getattr(e, "response", None)
    try:
        ra = resp.headers.get("retry-after") if resp is not None else None
        return min(float(ra), 120.0) if ra else None
    except (ValueError, AttributeError):
        return None


def _sessao(req: RequisicaoLLM) -> Any:
    if req.plataforma:
        return sync_reference_admin_session(TenantContext(org_id=None, platform_admin=True))
    return sync_tenant_session(TenantContext.sistema(req.org_id))


def _extrair_json(conteudo: list[Any]) -> dict[str, Any]:
    for bloco in conteudo:
        tipo = bloco.get("type") if isinstance(bloco, dict) else getattr(bloco, "type", None)
        if tipo == "text":
            texto = (bloco["text"] if isinstance(bloco, dict) else bloco.text).strip()
            if texto.startswith("```"):  # alguns modelos embrulham o JSON em bloco de código
                texto = texto.strip("`").removeprefix("json").strip()
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
    # Sem chave, falha antes de registrar a chamada (a auditoria para com uma mensagem clara).
    if catalogo.provedor_de(req.modelo) == "anthropic":
        cliente()
    else:
        verificar_chaves([req.modelo])

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
            mensagem = _chamar(req)
            break
        except provedores.ErroTransitorio as e:
            ultimo_erro = e
        except provedores.ErroDefinitivo as e:
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
            classe = IAIndisponivel if plataforma_indisponivel(ultimo_erro) else FalhaIA
            falha = classe(_mensagem_falha(ultimo_erro))
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


_SEM_CREDITO = ("credit balance", "insufficient_quota", "insufficient balance", "no credits", "billing")


def plataforma_indisponivel(erro: Exception | None) -> bool:
    """A falha foi da plataforma (não respondeu ou recusou a conta), e não da resposta sobre o item."""
    if isinstance(erro, provedores.ErroTransitorio):
        return True
    texto = str(erro or "").lower()
    return any(k in texto for k in _SEM_CREDITO) or "401" in texto or "authentication" in texto


def _mensagem_falha(erro: Exception | None) -> str:
    texto = str(erro or "").lower()
    if any(k in texto for k in _SEM_CREDITO):
        return "A plataforma de IA recusou por falta de créditos. Recarregue os créditos: a análise continua sozinha."
    if isinstance(erro, provedores.ErroDefinitivo) and ("401" in texto or "authentication" in texto):
        return "A plataforma de IA recusou a chave de API. Confira a chave em Chaves de API."
    return "Não foi possível obter resposta do modelo após várias tentativas."


def _espera(tentativa: int, erro: Exception | None) -> float:
    if isinstance(erro, provedores.ErroTransitorio) and erro.espera_s:
        return erro.espera_s + random.uniform(0, 1)
    return float(min(2**tentativa, 60)) + random.uniform(0, 1.5)
