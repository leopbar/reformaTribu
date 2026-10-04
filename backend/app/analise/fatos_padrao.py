"""Fatos padronizados (ADR 0030): as condições que se repetem nas teses têm um nome, uma pergunta e, quando a
lei presume ou o cadastro já diz, um valor sem perguntar.

Cada tese é escrita pelo Jurista, que nomeava os fatos livremente: "medicamento_lista_art146",
"consta_lista_aliquota_zero", "destinacao_art146"… O operador respondia a mesma coisa várias vezes, às
vezes de formas contraditórias, e o sistema perguntava até o que a lei presume (um remédio vendido em farmácia
é registrado na Anvisa). O catálogo vai ao Jurista com a instrução de reusar as chaves e é aplicado na
avaliação:

- `presumido`: a lei presume o valor na venda ao consumidor (o operador não é perguntado);
- `pelo_erp`: o tipo do item no ERP decide (ex.: "Medicamento sob prescrição" não é dispositivo médico);
- `pelo_dossie`: a resposta da empresa decide (quem não manipula não vende manipulado por ela).

Esses valores entram como fatos implícitos, com a origem e a explicação à mostra; uma resposta de pessoa em
contrário prevalece.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class FatoPadrao:
    chave: str
    sentido: str  # o que o fato significa: o Jurista reconhece a condição pelo sentido
    pergunta: str  # texto da pergunta ao operador, o mesmo em todas as teses
    presumido: str | None = None
    explicacao: str = ""
    pelo_erp: tuple[tuple[str, str, str], ...] = ()  # (padrão no tipo do ERP, valor, explicação)
    pelo_dossie: tuple[tuple[str, str, str], ...] = ()  # (fato da empresa, valor da empresa, valor do item)


FATOS: tuple[FatoPadrao, ...] = (
    FatoPadrao(
        "medicamento_aliquota_zero_art146",
        "o medicamento é destinado, pelo registro sanitário, a doenças raras ou negligenciadas, oncologia, "
        "diabetes, HIV/aids e outras IST, doenças cardiovasculares ou ao Programa Farmácia Popular (art. 146)",
        "O medicamento é destinado, pelo registro na Anvisa, a doenças raras ou negligenciadas, oncologia, "
        "diabetes, HIV/aids e outras IST, doenças cardiovasculares ou ao Programa Farmácia Popular (alíquota "
        "zero, art. 146)?",
    ),
    FatoPadrao(
        "medicamento_registrado_anvisa",
        "o medicamento é registrado na Anvisa",
        "O medicamento é registrado na Anvisa?",
        presumido="sim",
        explicacao="presunção legal: só se vende no varejo medicamento registrado na Anvisa",
    ),
    FatoPadrao(
        "fabricante_cumpre_cmed_ou_compromisso",
        "o fabricante ou importador cumpre a sistemática da CMED ou tem compromisso com a União e o CGIBS "
        "(art. 133, § 2º)",
        "O fabricante ou importador cumpre a sistemática da CMED (art. 133, § 2º)?",
        presumido="sim",
        explicacao="presunção legal: a CMED é obrigação do fabricante ou importador, que o varejo não confere",
    ),
    FatoPadrao(
        "dispositivo_medico",
        "o item é um dispositivo médico (e não um medicamento)",
        "O item é um dispositivo médico (e não um medicamento)?",
        # "Medicamentos e correlatos" (produtos para saúde) pode ser dispositivo: aí o ERP não decide.
        pelo_erp=(
            (
                r"^(?!.*(correlat|dispositiv|produto.? para (a )?saude)).*\bmedicament",
                "nao",
                "o ERP informa que o item é medicamento, não dispositivo médico",
            ),
        ),
    ),
    FatoPadrao(
        "dispositivo_registrado_anvisa",
        "o dispositivo médico está regularizado (registro ou notificação) na Anvisa",
        "O dispositivo médico está regularizado na Anvisa?",
        presumido="sim",
        explicacao="presunção legal: só se vende no varejo dispositivo médico regularizado na Anvisa",
    ),
    FatoPadrao(
        "produto_produzido_por_farmacia_manipulacao",
        "o produto foi manipulado pela própria farmácia (farmácia de manipulação)",
        "O produto foi manipulado pela própria farmácia?",
        pelo_dossie=(("manipula_medicamentos", "nao", "nao"),),
    ),
    FatoPadrao(
        "comprador_eh_orgao_publico_autarquia_fundacao_ou_entidade_cebas",
        "o comprador é órgão da administração pública, autarquia, fundação pública ou entidade de saúde com Cebas",
        "O comprador é órgão público, autarquia, fundação pública ou entidade de saúde com Cebas?",
        presumido="nao",
        explicacao="na venda ao consumidor final, o comprador não é órgão público nem entidade Cebas",
    ),
    FatoPadrao(
        "uso_veterinario",
        "o produto é de uso veterinário",
        "O produto é de uso veterinário?",
        pelo_erp=((r"\bmedicament.*\bhuman|\bhuman.*\bmedicament", "nao", "o ERP informa medicamento humano"),),
    ),
    FatoPadrao("adicao_acucar", "há adição de açúcar ao produto", "O produto tem adição de açúcar?"),
    FatoPadrao(
        "adicao_edulcorante", "há adição de edulcorante (adoçante) ao produto", "O produto tem adição de adoçante?"
    ),
    FatoPadrao("adicao_conservante", "o produto contém conservantes", "O produto contém conservantes?"),
    FatoPadrao(
        "destinado_alimentacao_humana",
        "o produto é vendido para alimentação humana",
        "O produto é vendido para alimentação humana?",
    ),
)
_POR_CHAVE = {f.chave: f for f in FATOS}


def _norm(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()


def pergunta(chave: str) -> str | None:
    f = _POR_CHAVE.get(chave)
    return f.pergunta if f else None


def para_o_jurista() -> list[dict[str, str]]:
    """O catálogo como instrução ao Jurista (fora do material da tese: não muda a chave das teses)."""
    saida = []
    for f in FATOS:
        linha = {"chave": f.chave, "sentido": f.sentido, "pergunta": f.pergunta}
        if f.presumido:
            linha["presumido"] = f"{f.presumido} ({f.explicacao})"
        elif f.pelo_erp or f.pelo_dossie:
            linha["resolvido_pelo_sistema"] = "quando o ERP ou o dossiê da empresa informam"
        saida.append(linha)
    return saida


def implicitos(tipo_erp: str | None, fatos: dict[str, str]) -> dict[str, tuple[str, str, str]]:
    """Fatos que a lei presume ou que o cadastro decide: chave → (valor, origem, explicação). `fatos` são os
    valores já conhecidos (os da empresa decidem os `pelo_dossie`). A origem é "cadastro" (presunção legal e
    dossiê) ou "erp"."""
    saida: dict[str, tuple[str, str, str]] = {}
    tipo = _norm(tipo_erp or "")
    for f in FATOS:
        if f.presumido:
            saida[f.chave] = (f.presumido, "cadastro", f.explicacao)
            continue
        for padrao, v, explicacao in f.pelo_erp:
            if tipo and re.search(padrao, tipo):
                saida[f.chave] = (v, "erp", f"{explicacao} (“{tipo_erp}”)")
                break
        for da_empresa, valor_empresa, v in f.pelo_dossie:
            if f.chave not in saida and fatos.get(da_empresa) == valor_empresa:
                saida[f.chave] = (v, "cadastro", f"decorre do dossiê da empresa ({da_empresa} = {valor_empresa})")
    return saida
