"""Grafo LangGraph do pipeline de auditoria de um item, com checkpoint no PostgreSQL."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config import get_settings
from app.pipeline import nodes
from app.pipeline.context import Contexto
from app.pipeline.state import ItemState


def _apos_validacao(state: ItemState) -> str:
    return "decidir_status" if state.base_incompleta else "buscar_memoria"


def _apos_memoria(state: ItemState) -> str:
    return "enquadrar" if state.memoria else "recuperar_candidatos"


def _apos_candidatos(state: ItemState) -> str:
    return "julgar_coerencia" if state.candidatos else "decidir_status"


def _apos_julgamento(state: ItemState) -> str:
    if not state.julgamento_valido:
        return "decidir_status"
    return "escalar" if state.precisa_escalar else "enquadrar"


def construir_grafo() -> StateGraph[Any, Any, Any, Any]:
    g: StateGraph[Any, Any, Any, Any] = StateGraph(ItemState, context_schema=Contexto)
    g.add_node("normalizar", nodes.normalizar)
    g.add_node("validar_estrutura", nodes.validar_estrutura)
    g.add_node("buscar_memoria", nodes.buscar_memoria)
    g.add_node("recuperar_candidatos", nodes.recuperar_candidatos)
    g.add_node("julgar_coerencia", nodes.julgar_coerencia)
    g.add_node("escalar", nodes.escalar)
    g.add_node("enquadrar", nodes.enquadrar)
    g.add_node("decidir_status", nodes.decidir_status)

    g.add_edge(START, "normalizar")
    g.add_edge("normalizar", "validar_estrutura")
    g.add_conditional_edges("validar_estrutura", _apos_validacao, ["decidir_status", "buscar_memoria"])
    g.add_conditional_edges("buscar_memoria", _apos_memoria, ["enquadrar", "recuperar_candidatos"])
    g.add_conditional_edges("recuperar_candidatos", _apos_candidatos, ["julgar_coerencia", "decidir_status"])
    g.add_conditional_edges("julgar_coerencia", _apos_julgamento, ["escalar", "enquadrar", "decidir_status"])
    g.add_edge("escalar", "enquadrar")
    g.add_edge("enquadrar", "decidir_status")
    g.add_edge("decidir_status", END)
    return g


def _dsn() -> str:
    return get_settings().database_url.replace("postgresql+psycopg://", "postgresql://")


@lru_cache
def pool() -> ConnectionPool:
    return ConnectionPool(
        _dsn(),
        min_size=1,
        max_size=8,
        open=True,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )


@lru_cache
def checkpointer() -> PostgresSaver:
    return PostgresSaver(pool())  # type: ignore[arg-type]


@lru_cache
def grafo() -> Any:
    return construir_grafo().compile(checkpointer=checkpointer())


def mermaid() -> str:
    """Diagrama do grafo (usado na documentação)."""
    return str(construir_grafo().compile().get_graph().draw_mermaid())
