"""Calendário da transição da Reforma Tributária do consumo (EC 132/2023, ADCT arts. 125 a 133).

A "classificação correta" depende da data: o analista sempre raciocina para uma data de vigência.
Os textos aqui são o resumo exibido ao usuário e enviado ao modelo como contexto; o fundamento
citado em cada decisão vem sempre dos trechos normativos da base versionada.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Periodo:
    inicio: date
    fim: date | None
    nome: str
    resumo: str
    dispositivos: str


PERIODOS: tuple[Periodo, ...] = (
    Periodo(
        date(1900, 1, 1),
        date(2025, 12, 31),
        "Antes da reforma",
        "IBS e CBS ainda não incidem. Vigoram PIS/Cofins, IPI, ICMS e ISS.",
        "EC 132/2023",
    ),
    Periodo(
        date(2026, 1, 1),
        date(2026, 12, 31),
        "2026 — ano de teste",
        "CBS de 0,9% e IBS de 0,1%, compensáveis com PIS/Cofins; destaque em documento fiscal para teste.",
        "ADCT, art. 125 (EC 132/2023)",
    ),
    Periodo(
        date(2027, 1, 1),
        date(2028, 12, 31),
        "2027–2028 — CBS em vigor",
        "Cobrança da CBS, extinção de PIS/Cofins, início do Imposto Seletivo e IBS de 0,1 ponto percentual "
        "(0,05 estadual e 0,05 municipal). ICMS e ISS continuam integrais.",
        "ADCT, arts. 126 e 127 (EC 132/2023)",
    ),
    Periodo(
        date(2029, 1, 1),
        date(2032, 12, 31),
        "2029–2032 — transição ICMS/ISS",
        "Redução gradual de ICMS e ISS (90%, 80%, 70% e 60% das alíquotas) e aumento proporcional do IBS.",
        "ADCT, arts. 128 e 129 (EC 132/2023)",
    ),
    Periodo(
        date(2033, 1, 1),
        None,
        "2033 em diante — vigência integral",
        "ICMS e ISS extintos; IBS e CBS em vigor integral.",
        "ADCT, art. 129 (EC 132/2023)",
    ),
)


def periodo(data: date) -> Periodo:
    for p in PERIODOS:
        if p.inicio <= data and (p.fim is None or data <= p.fim):
            return p
    return PERIODOS[-1]


def como_dict(data: date) -> dict[str, str]:
    p = periodo(data)
    return {"data": data.isoformat(), "periodo": p.nome, "resumo": p.resumo, "dispositivos": p.dispositivos}
