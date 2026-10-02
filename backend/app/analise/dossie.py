"""Dossiê do estabelecimento: o que o analista precisa saber sobre quem vende antes de olhar os itens.

As respostas viram fatos de escopo "empresa" e valem para todos os itens (e todas as auditorias
seguintes), até serem alteradas. O agente pode pedir outros fatos de empresa durante a investigação;
eles aparecem como perguntas da auditoria.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class PerguntaDossie:
    atributo: str
    pergunta: str
    ajuda: str
    opcoes: tuple[tuple[str, str], ...] = (("sim", "Sim"), ("nao", "Não"))
    segmentos: tuple[str, ...] = field(default_factory=tuple)  # vazio = todos

    def como_dict(self) -> dict[str, Any]:
        return {
            "atributo": self.atributo,
            "pergunta": self.pergunta,
            "ajuda": self.ajuda,
            "opcoes": [{"valor": v, "rotulo": r} for v, r in self.opcoes],
        }


SEGMENTOS: tuple[tuple[str, str], ...] = (
    ("supermercado", "Supermercado / varejo alimentar"),
    ("padaria", "Padaria e confeitaria"),
    ("restaurante", "Bar, restaurante ou lanchonete"),
    ("farmacia", "Farmácia / drogaria"),
    ("varejo_geral", "Varejo em geral (não alimentar)"),
    ("industria", "Indústria"),
    ("servicos", "Prestação de serviços"),
    ("outro", "Outro"),
)

ALIMENTAR = ("supermercado", "padaria", "restaurante")

PERGUNTAS: tuple[PerguntaDossie, ...] = (
    PerguntaDossie(
        "vende_consumidor_final",
        "A maior parte das vendas é para consumidor final (pessoa física)?",
        "Define o cenário padrão analisado: venda ao consumidor com NFC-e/NF-e.",
    ),
    PerguntaDossie(
        "produz_alimentos",
        "O estabelecimento produz ou manipula alimentos (padaria, confeitaria, açougue, rotisseria)?",
        "Produtos feitos na loja podem ter enquadramento diferente dos comprados prontos.",
        segmentos=ALIMENTAR,
    ),
    PerguntaDossie(
        "fornece_refeicoes",
        "Serve refeições ou lanches para consumo no local (restaurante, lanchonete, praça de alimentação)?",
        "O fornecimento de alimentação tem regime específico na LC 214/2025.",
        segmentos=ALIMENTAR,
    ),
    PerguntaDossie(
        "fraciona_hortifruti",
        "Fraciona, embala ou processa frutas, legumes e verduras na loja?",
        "Produtos hortícolas in natura e processados podem ter tratamentos diferentes.",
        segmentos=("supermercado",),
    ),
    PerguntaDossie(
        "vende_combustiveis",
        "Vende combustíveis (posto próprio, gás de cozinha)?",
        "Combustíveis seguem o regime monofásico.",
        segmentos=("supermercado", "varejo_geral"),
    ),
    PerguntaDossie(
        "manipula_medicamentos",
        "Manipula medicamentos (farmácia de manipulação)?",
        "Medicamentos manipulados têm tratamento próprio.",
        segmentos=("farmacia",),
    ),
    PerguntaDossie(
        "fabrica_ou_importa_seletivo",
        "A empresa fabrica ou importa algum produto sujeito ao Imposto Seletivo (bebidas alcoólicas, bebidas "
        "açucaradas, cigarros, veículos, embarcações, armas)?",
        "O Imposto Seletivo é cobrado uma única vez, na fabricação ou na importação (LC 214/2025, arts. 409 e 412). "
        "Quem só revende não recolhe: os itens sujeitos ao IS deixam de ir para o contador.",
    ),
    PerguntaDossie(
        "zona_franca",
        "O estabelecimento fica na Zona Franca de Manaus ou em área de livre comércio?",
        "Há regimes diferenciados para essas regiões.",
    ),
)


def perguntas_do_segmento(segmento: str | None) -> list[PerguntaDossie]:
    return [p for p in PERGUNTAS if not p.segmentos or (segmento in p.segmentos)]


def rotulo_segmento(segmento: str | None) -> str | None:
    return dict(SEGMENTOS).get(segmento or "")
