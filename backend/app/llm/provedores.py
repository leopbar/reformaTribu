"""Conectores das plataformas de IA. Cada um recebe a mesma requisição e devolve a resposta no mesmo
formato (o da Messages API da Anthropic), para que registro, custo e validação sejam únicos.

- Anthropic: SDK oficial, saída estruturada por JSON Schema, cache do bloco de sistema e `effort`.
- OpenAI: Chat Completions com `response_format` json_schema (não estrito: os esquemas do sistema têm
  campos opcionais) e `reasoning_effort` nos modelos de raciocínio. Cache automático.
- DeepSeek: API compatível com a OpenAI, em modo JSON; o esquema vai no bloco de sistema. Cache automático.

Em todos os casos a resposta é validada pelo sistema (Pydantic) depois; formato errado vira falha.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING, Any

import anthropic
import httpx
import orjson

from app.config import get_settings
from app.llm import catalogo

if TYPE_CHECKING:
    from app.llm.gateway import RequisicaoLLM


class ErroTransitorio(Exception):
    """Vale tentar de novo (limite de taxa, servidor ocupado, rede)."""

    def __init__(self, mensagem: str, espera_s: float | None = None) -> None:
        super().__init__(mensagem)
        self.espera_s = espera_s


class ErroDefinitivo(Exception):
    """Não adianta repetir (chave inválida, sem crédito, requisição recusada)."""


class SemChave(Exception):
    pass


# ------------------------------------------------------------------------------- Anthropic --
@lru_cache(maxsize=8)
def _cliente_anthropic(chave: str, base_url: str, timeout: float) -> anthropic.Anthropic:
    # Retentativas próprias (no gateway) controlam backoff e registro; o SDK não repete sozinho.
    return anthropic.Anthropic(api_key=chave, base_url=base_url or None, timeout=timeout, max_retries=0)


def cliente_anthropic() -> anthropic.Anthropic:
    chave, base = catalogo.credencial("anthropic")
    if not chave:
        raise SemChave(
            "A chave da API da Anthropic não está cadastrada. O superadministrador deve cadastrá-la em Chaves de API."
        )
    return _cliente_anthropic(chave, base, get_settings().llm_timeout_s)


def params_anthropic(req: RequisicaoLLM) -> dict[str, Any]:
    """Parâmetros da Messages API. O bloco de sistema é estável e fica em cache."""
    return {
        "model": req.modelo,
        "max_tokens": req.max_tokens,
        "system": [{"type": "text", "text": req.prompt.texto, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": _conteudo(req)}],
        "output_config": {
            "format": {"type": "json_schema", "schema": req.schema},
            **({"effort": req.esforco} if catalogo.suporta_esforco(req.modelo) else {}),
        },
    }


# ------------------------------------------------------------------------ OpenAI e DeepSeek --
def _conteudo(req: RequisicaoLLM) -> str:
    return orjson.dumps(req.conteudo_usuario, option=orjson.OPT_SORT_KEYS).decode()


def _corpo_compativel(req: RequisicaoLLM, provedor: str) -> dict[str, Any]:
    if provedor == "deepseek":
        # Modo JSON (sem esquema estrito): o esquema vai escrito no sistema, depois das instruções.
        sistema = (
            req.prompt.texto
            + "\n\n## Formato obrigatório da resposta\n\nResponda somente com um objeto JSON válido que siga "
            "exatamente este JSON Schema:\n\n" + orjson.dumps(req.schema).decode()
        )
        return {
            "model": req.modelo,
            "max_tokens": req.max_tokens,
            "messages": [{"role": "system", "content": sistema}, {"role": "user", "content": _conteudo(req)}],
            "response_format": {"type": "json_object"},
        }
    corpo: dict[str, Any] = {
        "model": req.modelo,
        "max_completion_tokens": req.max_tokens,
        "messages": [{"role": "system", "content": req.prompt.texto}, {"role": "user", "content": _conteudo(req)}],
        "response_format": {
            "type": "json_schema",
            # Estrito quando o esquema permite (modelos pequenos às vezes devolvem o próprio esquema sem isso).
            "json_schema": {"name": req.no[:64], "schema": req.schema, "strict": esquema_estrito(req.schema)},
        },
    }
    if catalogo.suporta_esforco(req.modelo):
        corpo["reasoning_effort"] = req.esforco if req.esforco in ("low", "medium", "high") else "medium"
    return corpo


def esquema_estrito(schema: Any) -> bool:
    """O modo estrito da OpenAI exige objetos fechados com todos os campos obrigatórios."""
    if isinstance(schema, list):
        return all(esquema_estrito(x) for x in schema)
    if not isinstance(schema, dict):
        return True
    if schema.get("type") == "object" or "properties" in schema:
        props = schema.get("properties") or {}
        if schema.get("additionalProperties") is not False or set(schema.get("required") or []) != set(props):
            return False
        if not all(esquema_estrito(v) for v in props.values()):
            return False
    return all(esquema_estrito(schema[chave]) for chave in ("items", "anyOf") if chave in schema)


def _chamar_compativel(req: RequisicaoLLM, provedor: str) -> dict[str, Any]:
    chave, base = catalogo.credencial(provedor)
    if not chave:
        nome = catalogo.PROVEDORES.get(provedor, {}).get("nome", provedor)
        raise SemChave(f"A chave da API da {nome} não está cadastrada. Cadastre-a em Chaves de API.")
    url = base.rstrip("/") + "/chat/completions"
    try:
        r = httpx.post(
            url,
            json=_corpo_compativel(req, provedor),
            headers={"Authorization": f"Bearer {chave}"},
            timeout=get_settings().llm_timeout_s,
        )
    except (httpx.TimeoutException, httpx.NetworkError) as e:
        raise ErroTransitorio(f"{type(e).__name__}: {e}") from e
    if r.status_code in (408, 409, 429) or r.status_code >= 500:
        raise ErroTransitorio(f"HTTP {r.status_code}: {r.text[:300]}", _retry_after(r))
    if r.status_code >= 400:
        raise ErroDefinitivo(f"HTTP {r.status_code}: {r.text[:500]}")
    return normalizar_compativel(r.json(), provedor, r.headers.get("x-request-id"))


def normalizar_compativel(dados: dict[str, Any], provedor: str, request_id: str | None = None) -> dict[str, Any]:
    """Converte a resposta de Chat Completions para o formato da Messages API."""
    escolha = (dados.get("choices") or [{}])[0]
    msg = escolha.get("message") or {}
    fim = escolha.get("finish_reason")
    stop = {"length": "max_tokens", "content_filter": "refusal"}.get(fim or "", "end_turn")
    if msg.get("refusal"):
        stop = "refusal"
    u = dados.get("usage") or {}
    entrada = int(u.get("prompt_tokens") or 0)
    if provedor == "deepseek":
        lidos = int(u.get("prompt_cache_hit_tokens") or 0)
    else:
        lidos = int((u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0)
    return {
        "content": [{"type": "text", "text": msg.get("content") or ""}],
        "stop_reason": stop,
        "usage": {
            "input_tokens": max(0, entrada - lidos),
            "output_tokens": int(u.get("completion_tokens") or 0),
            "cache_read_input_tokens": lidos,
            "cache_creation_input_tokens": 0,
        },
        "model": dados.get("model"),
        "_request_id": request_id or dados.get("id"),
    }


def _retry_after(resp: Any) -> float | None:
    try:
        ra = resp.headers.get("retry-after") if resp is not None else None
        return min(float(ra), 120.0) if ra else None
    except (ValueError, AttributeError):
        return None


# ---------------------------------------------------------------------------------- entrada --
def chamar(req: RequisicaoLLM) -> dict[str, Any]:
    """Uma chamada a OpenAI ou DeepSeek (sem retentativa), no formato da Messages API."""
    provedor = catalogo.provedor_de(req.modelo)
    if provedor == "anthropic":
        raise ValueError("Modelos Claude são chamados pelo gateway (cliente Anthropic).")
    return _chamar_compativel(req, provedor)


def testar(provedor: str, chave: str, base_url: str) -> tuple[bool, str]:
    """Confere a chave listando os modelos da plataforma (não gasta tokens)."""
    try:
        if provedor == "anthropic":
            r = httpx.get(
                base_url.rstrip("/") + "/v1/models",
                headers={"x-api-key": chave, "anthropic-version": "2023-06-01"},
                timeout=20,
            )
        else:
            r = httpx.get(base_url.rstrip("/") + "/models", headers={"Authorization": f"Bearer {chave}"}, timeout=20)
    except httpx.HTTPError as e:
        return False, f"Não foi possível conectar: {type(e).__name__}."
    if r.status_code == 200:
        n = len((r.json() or {}).get("data") or [])
        return True, f"Conexão ok: a plataforma respondeu com {n} modelos disponíveis para esta chave."
    if r.status_code in (401, 403):
        return False, "A plataforma recusou a chave (inválida, revogada ou sem permissão)."
    return False, f"A plataforma respondeu HTTP {r.status_code}: {r.text[:200]}"
