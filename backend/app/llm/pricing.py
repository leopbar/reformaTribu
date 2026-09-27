"""Preços por modelo (US$ por milhão de tokens) e cálculo de custo.

Fonte: tabela de preços da Anthropic consultada em 26/09/2026. Confira em
https://www.anthropic.com/pricing antes de alterar. Escrita em cache custa 1,25x a entrada;
leitura de cache custa 0,1x; a Batch API custa 50% de todo o uso.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Preco:
    entrada: Decimal
    saida: Decimal
    cache_leitura: Decimal | None = None  # quando diferente de 0,1x da entrada

    def custo(self, entrada: int, saida: int, cache_escrita: int, cache_leitura: int, lote: bool) -> Decimal:
        milhao = Decimal(1_000_000)
        leitura = self.cache_leitura if self.cache_leitura is not None else self.entrada * Decimal("0.1")
        total = (
            Decimal(entrada) * self.entrada
            + Decimal(saida) * self.saida
            + Decimal(cache_escrita) * self.entrada * Decimal("1.25")
            + Decimal(cache_leitura) * leitura
        ) / milhao
        if lote:
            total *= Decimal("0.5")
        return total.quantize(Decimal("0.000001"))


PRECOS: dict[str, Preco] = {
    "claude-sonnet-5": Preco(Decimal("2.00"), Decimal("10.00")),
    "claude-opus-5-5": Preco(Decimal("4.00"), Decimal("20.00"), Decimal("0.20")),
    "claude-opus-5": Preco(Decimal("5.00"), Decimal("25.00")),
    "claude-haiku-4-5": Preco(Decimal("1.00"), Decimal("5.00")),
    "claude-haiku-4-5-20251001": Preco(Decimal("1.00"), Decimal("5.00")),
    "claude-fable-5-1": Preco(Decimal("10.00"), Decimal("50.00"), Decimal("0.25")),
}

MODELOS_SUPORTADOS = frozenset(PRECOS)


def preco(modelo: str) -> Preco:
    try:
        return PRECOS[modelo]
    except KeyError:
        # Modelo novo sem preço cadastrado: usa o mais caro conhecido para não subestimar custos.
        return max(PRECOS.values(), key=lambda p: p.saida)


def custo_chamada(
    modelo: str, entrada: int, saida: int, cache_escrita: int, cache_leitura: int, lote: bool = False
) -> Decimal:
    return preco(modelo).custo(entrada, saida, cache_escrita, cache_leitura, lote)
