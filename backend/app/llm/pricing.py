"""Preços por modelo (US$ por milhão de tokens) e cálculo de custo.

Os preços vêm do catálogo da plataforma (tela "Modelos de IA", tabela `llm_modelos`), que o
superadministrador mantém atualizado. Cache: a leitura custa `preco_cache_leitura`; a escrita custa
`mult_cache_escrita` × entrada (1,25 na Anthropic; 1 onde o cache é automático). O lote (50%) só
vale para modelos com `suporta_lote`.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.llm import catalogo


@dataclass(frozen=True)
class Preco:
    entrada: Decimal
    saida: Decimal
    cache_leitura: Decimal | None = None  # quando diferente de 0,1x da entrada
    mult_cache_escrita: Decimal = Decimal("1.25")
    suporta_lote: bool = True

    def custo(self, entrada: int, saida: int, cache_escrita: int, cache_leitura: int, lote: bool) -> Decimal:
        milhao = Decimal(1_000_000)
        leitura = self.cache_leitura if self.cache_leitura is not None else self.entrada * Decimal("0.1")
        total = (
            Decimal(entrada) * self.entrada
            + Decimal(saida) * self.saida
            + Decimal(cache_escrita) * self.entrada * self.mult_cache_escrita
            + Decimal(cache_leitura) * leitura
        ) / milhao
        if lote and self.suporta_lote:
            total *= Decimal("0.5")
        return total.quantize(Decimal("0.000001"))


def preco(modelo: str) -> Preco:
    info = catalogo.info_modelo(modelo)
    if info is None:
        # Sem preço cadastrado: usa o mais caro do catálogo para não subestimar custos.
        info = max(catalogo.modelos().values(), key=lambda m: m.saida)
    return Preco(info.entrada, info.saida, info.cache_leitura, info.mult_cache_escrita, info.suporta_lote)


def custo_chamada(
    modelo: str, entrada: int, saida: int, cache_escrita: int, cache_leitura: int, lote: bool = False
) -> Decimal:
    return preco(modelo).custo(entrada, saida, cache_escrita, cache_leitura, lote)
