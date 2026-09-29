"""Grafo LangGraph do pipeline de auditoria de um item, com checkpoint no PostgreSQL."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config import get_settings
from app.pipeline import analista, arvore, nodes
from app.pipeline.context import Contexto
from app.pipeline.state import ItemState


def _apos_validacao(state: ItemState) -> str:
    return "concluir" if state.base_incompleta else "buscar_memoria"


def _apos_memoria(state: ItemState) -> str:
    return "investigar" if state.memoria else "recuperar_candidatos"


def _apos_candidatos(state: ItemState) -> str:
    if state.confirmado_sem_ia:
        return "investigar"
    return "julgar_coerencia" if state.candidatos else "navegar_arvore"


def _apos_julgamento(state: ItemState) -> str:
    if state.julgamento_valido and state.precisa_escalar:
        return "escalar"
    # Sem código (nenhuma alternativa serve ou resposta descartada): busca guiada na árvore oficial.
    return "navegar_arvore" if arvore.precisa_navegar(state) else "investigar"


def _apos_escalonamento(state: ItemState) -> str:
    return "navegar_arvore" if arvore.precisa_navegar(state) else "investigar"


def _apos_arvore(state: ItemState) -> str:
    return "concluir" if arvore.precisa_navegar(state) else "investigar"


def _apos_investigacao(state: ItemState) -> str:
    return "levantar_fatos" if state.tese_id else "concluir"


def construir_grafo() -> StateGraph[Any, Any, Any, Any]:
    """Identificação do item → investigação jurídica da família → fatos do item → conclusão."""
    g: StateGraph[Any, Any, Any, Any] = StateGraph(ItemState, context_schema=Contexto)
    g.add_node("normalizar", nodes.normalizar)
    g.add_node("validar_estrutura", nodes.validar_estrutura)
    g.add_node("buscar_memoria", nodes.buscar_memoria)
    g.add_node("recuperar_candidatos", nodes.recuperar_candidatos)
    g.add_node("julgar_coerencia", nodes.julgar_coerencia)
    g.add_node("escalar", nodes.escalar)
    g.add_node("navegar_arvore", arvore.navegar_arvore)
    g.add_node("investigar", analista.investigar)
    g.add_node("levantar_fatos", analista.levantar_fatos)
    g.add_node("concluir", analista.concluir)

    g.add_edge(START, "normalizar")
    g.add_edge("normalizar", "validar_estrutura")
    g.add_conditional_edges("validar_estrutura", _apos_validacao, ["concluir", "buscar_memoria"])
    g.add_conditional_edges("buscar_memoria", _apos_memoria, ["investigar", "recuperar_candidatos"])
    g.add_conditional_edges(
        "recuperar_candidatos", _apos_candidatos, ["julgar_coerencia", "investigar", "navegar_arvore"]
    )
    g.add_conditional_edges("julgar_coerencia", _apos_julgamento, ["escalar", "investigar", "navegar_arvore"])
    g.add_conditional_edges("escalar", _apos_escalonamento, ["navegar_arvore", "investigar"])
    g.add_conditional_edges("navegar_arvore", _apos_arvore, ["investigar", "concluir"])
    g.add_conditional_edges("investigar", _apos_investigacao, ["levantar_fatos", "concluir"])
    g.add_edge("levantar_fatos", "concluir")
    g.add_edge("concluir", END)
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
