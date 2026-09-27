"""Busca híbrida de códigos NCM/NBS: vetorial (pgvector) + textual em português, combinadas por RRF."""

from __future__ import annotations

import re
import unicodedata
import uuid
from dataclasses import dataclass
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

RRF_K = 60
_STOP = {
    "de",
    "da",
    "do",
    "das",
    "dos",
    "com",
    "sem",
    "para",
    "em",
    "e",
    "o",
    "a",
    "os",
    "as",
    "un",
    "und",
    "cx",
    "pct",
    "pc",
    "kg",
    "g",
    "ml",
    "l",
    "lt",
    "c",
    "x",
}


@dataclass
class Candidato:
    tipo_codigo: str
    codigo: str
    descricao_completa: str
    rank_semantico: int | None
    rank_textual: int | None
    score: float
    posicao: int = 0

    def como_dict(self) -> dict[str, Any]:
        return {
            "tipo_codigo": self.tipo_codigo,
            "codigo": self.codigo,
            "descricao_completa": self.descricao_completa,
            "rank_semantico": self.rank_semantico,
            "rank_textual": self.rank_textual,
            "score": round(self.score, 6),
            "posicao": self.posicao,
        }


def termos_busca(texto_: str) -> list[str]:
    t = unicodedata.normalize("NFKD", texto_ or "").encode("ascii", "ignore").decode().lower()
    termos = [w for w in re.findall(r"[a-z]{2,}", t) if w not in _STOP]
    return list(dict.fromkeys(termos))[:24]


def _tabela(tipo: str) -> str:
    return "nbs_nodes" if tipo == "nbs" else "ncm_nodes"


_SQL_VETORIAL = """
SELECT codigo, descricao_completa FROM {tabela}
 WHERE version_id = :v AND folha AND embedding IS NOT NULL
 ORDER BY embedding <=> :q LIMIT :lim
"""

_SQL_TEXTUAL = """
SELECT codigo, descricao_completa, ts_rank_cd(tsv, q) AS r
  FROM {tabela}, to_tsquery('portuguese', :tsq) q
 WHERE version_id = :v AND folha AND tsv @@ q
 ORDER BY r DESC, codigo LIMIT :lim
"""


def buscar_candidatos(
    session: Session,
    consultas: list[tuple[str, uuid.UUID]],
    texto_consulta: str,
    embedding: list[float] | None,
    k: int = 15,
    por_fonte: int = 40,
) -> tuple[list[Candidato], dict[str, Any]]:
    """`consultas` = [(tipo_codigo, version_id)]. Devolve candidatos e informações da busca."""
    session.execute(text("SET LOCAL hnsw.ef_search = 200"))
    session.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
    pontuacao: dict[tuple[str, str], Candidato] = {}
    info: dict[str, Any] = {"semantica": embedding is not None, "termos": termos_busca(texto_consulta)}
    tsq = " | ".join(info["termos"])

    for tipo, version_id in consultas:
        tabela = _tabela(tipo)
        if embedding is not None:
            stmt = text(_SQL_VETORIAL.format(tabela=tabela)).bindparams(bindparam("q", type_=Vector(len(embedding))))
            rows = session.execute(stmt, {"v": version_id, "q": embedding, "lim": por_fonte}).all()
            for rank, (codigo, desc) in enumerate(rows, start=1):
                c = pontuacao.setdefault((tipo, codigo), Candidato(tipo, codigo, desc, None, None, 0.0))
                c.rank_semantico = rank
                c.score += 1.0 / (RRF_K + rank)
        if tsq:
            rows = session.execute(
                text(_SQL_TEXTUAL.format(tabela=tabela)), {"v": version_id, "tsq": tsq, "lim": por_fonte}
            ).all()
            for rank, (codigo, desc, _r) in enumerate(rows, start=1):
                c = pontuacao.setdefault((tipo, codigo), Candidato(tipo, codigo, desc, None, None, 0.0))
                c.rank_textual = rank
                c.score += 1.0 / (RRF_K + rank)

    ordenados = sorted(pontuacao.values(), key=lambda c: (-c.score, c.codigo))[:k]
    for i, c in enumerate(ordenados, start=1):
        c.posicao = i
    return ordenados, info


def obter_no(session: Session, tipo: str, version_id: uuid.UUID, codigo: str) -> dict[str, Any] | None:
    row = session.execute(
        text(
            f"SELECT codigo, descricao_completa, folha, data_inicio, data_fim FROM {_tabela(tipo)} "
            "WHERE version_id = :v AND codigo = :c"
        ),
        {"v": version_id, "c": codigo},
    ).first()
    return dict(row._mapping) if row else None


async def autocompletar(
    session: AsyncSession, tipo: str, version_id: uuid.UUID, consulta: str, limite: int = 20
) -> list[dict[str, Any]]:
    """Busca para a edição assistida: por código (prefixo) ou por texto."""
    digitos = re.sub(r"\D", "", consulta)
    tabela = _tabela(tipo)
    if digitos and len(digitos) >= 2 and len(digitos) >= len(consulta.replace(".", "").replace(" ", "")) - 1:
        rows = await session.execute(
            text(
                f"SELECT codigo, codigo_formatado, descricao, descricao_completa, folha FROM {tabela} "
                "WHERE version_id = :v AND codigo LIKE :p ORDER BY length(codigo), codigo LIMIT :lim"
            ),
            {"v": version_id, "p": digitos + "%", "lim": limite},
        )
    else:
        termos = termos_busca(consulta)
        if not termos:
            return []
        tsq = " & ".join(f"{t}:*" for t in termos)
        rows = await session.execute(
            text(
                f"SELECT codigo, codigo_formatado, descricao, descricao_completa, folha FROM {tabela}, "
                "to_tsquery('portuguese', :tsq) q WHERE version_id = :v AND folha AND tsv @@ q "
                "ORDER BY ts_rank_cd(tsv, q) DESC, codigo LIMIT :lim"
            ),
            {"v": version_id, "tsq": tsq, "lim": limite},
        )
    return [dict(r._mapping) for r in rows]
