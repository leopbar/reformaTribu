"""Confiança final calibrada: combina sinais das etapas em vez de copiar o número do modelo.

Os pesos ficam em `calibracao.json` e são ajustados pelo harness de avaliação (make eval).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

CALIBRACAO = Path(__file__).with_name("calibracao.json")


@lru_cache
def pesos() -> dict[str, Any]:
    return json.loads(CALIBRACAO.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


@dataclass
class Componentes:
    modelo: float
    busca: float
    concordancia: float
    regra: float
    descricao: float
    estrutura: float

    def final(self) -> float:
        p = pesos()["pesos"]
        base = (
            p["modelo"] * self.modelo
            + p["busca"] * self.busca
            + p["regra"] * self.regra
            + p["descricao"] * self.descricao
            + p["estrutura"] * self.estrutura
        )
        base /= sum(p.values())
        # A confiança final nunca ultrapassa muito a do modelo, e é zerada se as etapas discordam.
        valor = min(base, self.modelo + pesos()["folga_sobre_modelo"]) * self.concordancia
        return float(round(max(0.0, min(1.0, valor)), 3))

    def como_dict(self) -> dict[str, float]:
        return {
            "modelo": round(self.modelo, 3),
            "busca": round(self.busca, 3),
            "concordancia": round(self.concordancia, 3),
            "regra": round(self.regra, 3),
            "descricao": round(self.descricao, 3),
            "estrutura": round(self.estrutura, 3),
            "final": self.final(),
        }


def sinal_busca(posicao: int | None) -> float:
    faixas = pesos()["busca_por_posicao"]
    if posicao is None:
        return float(faixas["fora_da_lista"])
    if posicao <= 3:
        return float(faixas["top3"])
    if posicao <= 10:
        return float(faixas["top10"])
    return float(faixas["demais"])
