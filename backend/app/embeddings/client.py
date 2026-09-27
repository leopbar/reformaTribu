"""Cliente do serviço local de embeddings (Hugging Face Text Embeddings Inference + bge-m3).

Nenhum texto sai da infraestrutura: o modelo roda no contêiner `embeddings`.
"""

from __future__ import annotations

import time
from functools import lru_cache

import httpx
import structlog

from app.config import get_settings

log = structlog.get_logger()


class EmbeddingsIndisponivel(Exception):
    pass


@lru_cache
def _http() -> httpx.Client:
    return httpx.Client(base_url=get_settings().embeddings_url, timeout=httpx.Timeout(120.0, connect=5.0))


def disponivel() -> bool:
    try:
        return _http().get("/health").status_code == 200
    except httpx.HTTPError:
        return False


def embed(textos: list[str], tentativas: int = 4, tipo: str = "consulta") -> list[list[float]]:
    """Gera embeddings normalizados (norma 1). `tipo`: "consulta" (busca) ou "documento" (índice)."""
    if not textos:
        return []
    s = get_settings()
    prefixo = s.embeddings_prefixo_consulta if tipo == "consulta" else s.embeddings_prefixo_documento
    textos = [prefixo + t for t in textos]
    saida: list[list[float]] = []
    for i in range(0, len(textos), s.embeddings_lote):
        lote = textos[i : i + s.embeddings_lote]
        for tentativa in range(1, tentativas + 1):
            try:
                r = _http().post("/embed", json={"inputs": lote, "normalize": True, "truncate": True})
                r.raise_for_status()
                vetores = r.json()
                if len(vetores) != len(lote) or (vetores and len(vetores[0]) != s.embeddings_dim):
                    raise EmbeddingsIndisponivel(
                        f"Serviço de embeddings devolveu dimensão inesperada (esperado {s.embeddings_dim})."
                    )
                saida.extend(vetores)
                break
            except (httpx.HTTPError, ValueError) as e:
                if tentativa == tentativas:
                    raise EmbeddingsIndisponivel(
                        "O serviço local de embeddings não respondeu. Verifique o contêiner `embeddings`."
                    ) from e
                time.sleep(2**tentativa)
    return saida
