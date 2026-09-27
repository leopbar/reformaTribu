"""Estado tipado do grafo de auditoria de um item.

Os campos são tipos simples (str, números, listas e dicts de JSON) para que o checkpoint no
PostgreSQL seja portátil entre versões do código.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ItemState(BaseModel):
    item_id: str
    audit_id: str
    org_id: str
    tentativa: int = 1

    # normalizar
    descricao: str = ""
    descricao_normalizada: str = ""
    expansoes: list[dict[str, str]] = Field(default_factory=list)
    tipo: str = "desconhecido"

    # validar_estrutura
    estrutura: dict[str, Any] = Field(default_factory=dict)
    motivos: list[str] = Field(default_factory=list)
    base_incompleta: bool = False

    # buscar_memoria
    memoria: dict[str, Any] | None = None

    # recuperar_candidatos
    candidatos: list[dict[str, Any]] = Field(default_factory=list)
    busca: dict[str, Any] = Field(default_factory=dict)

    # julgar_coerencia / escalar
    julgamento: dict[str, Any] | None = None
    julgamento_valido: bool = False
    precisa_escalar: bool = False
    gatilhos_escalonamento: list[str] = Field(default_factory=list)
    escalonamento: dict[str, Any] | None = None
    escalonamento_valido: bool = False
    llm_calls: list[str] = Field(default_factory=list)
    falha_ia: str | None = None

    # enquadrar
    tipo_codigo_final: str | None = None
    codigo_final: str | None = None
    atributos: dict[str, str] = Field(default_factory=dict)
    enquadramento: dict[str, Any] = Field(default_factory=dict)

    # decidir_status
    status: str | None = None
    confianca: float | None = None
    confianca_componentes: dict[str, Any] = Field(default_factory=dict)
    concluido: bool = False
