"""Execução do grafo por item, com retomada a partir do checkpoint."""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from langgraph.types import Command

from app.pipeline.context import Contexto
from app.pipeline.graph import checkpointer, grafo
from app.pipeline.state import ItemState

log = structlog.get_logger()

CONCLUIDO = "concluido"
AGUARDANDO_LOTE = "aguardando_lote"


def thread_id(item_id: uuid.UUID | str, tentativa: int) -> str:
    return f"item:{item_id}:t{tentativa}"


def processar_item(item_id: uuid.UUID, tentativa: int, ctx: Contexto) -> str:
    """Executa (ou retoma) o grafo do item. Devolve 'concluido' ou 'aguardando_lote'."""
    g = grafo()
    config: dict[str, Any] = {"configurable": {"thread_id": thread_id(item_id, tentativa)}}
    estado = g.get_state(config)
    if estado.next:
        # Execução anterior parou no meio (queda do worker ou espera de lote): retoma.
        entrada: Any = Command(resume=True) if estado.interrupts else None
    else:
        entrada = ItemState(
            item_id=str(item_id), audit_id=str(ctx.audit_id), org_id=str(ctx.org_id), tentativa=tentativa
        )
    resultado = g.invoke(entrada, config, context=ctx, durability="async")
    if isinstance(resultado, dict) and resultado.get("__interrupt__"):
        return AGUARDANDO_LOTE
    try:
        checkpointer().delete_thread(thread_id(item_id, tentativa))
    except Exception as e:  # limpeza é melhor-esforço
        log.warning("limpeza_checkpoint_falhou", erro=str(e))
    return CONCLUIDO
