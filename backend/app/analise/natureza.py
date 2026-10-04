"""Ligações da lei entre a natureza do produto e o cClassTrib, onde a tabela oficial não as faz.

A correlação oficial cClassTrib × NCM/NBS (Portal da Conformidade Fácil) cobre os benefícios que a lei
dá por lista de códigos (anexos). Alguns benefícios, porém, a lei concede pela NATUREZA do produto, sem
lista de NCM, e esses cClassTrib não têm nenhuma correlação na tabela:

- medicamento registrado na Anvisa (art. 133, 60%) e os da lista de alíquota zero (art. 146);
- soros e vacinas (art. 146, § 1º, III);
- produto agropecuário, aquícola, pesqueiro, florestal ou extrativista vegetal in natura (art. 137, 60%);
- livros, jornais, periódicos e o papel destinado à sua impressão (art. 9º, IV, imunidade);
- fonogramas e videofonogramas musicais brasileiros (art. 9º, V, imunidade).

Sem esta ligação, o pacote de evidências do Jurista não trazia esses códigos, e a lista de cClassTrib que
ele pode usar é fechada: um remédio de farmácia saía com tributação integral (ADR 0027). Cada ligação aqui
diz a qual posição do NCM a natureza corresponde, a condição que a lei exige (vira condição da hipótese,
verificada por fato ou pergunta) e o artigo, cujo texto vem da base oficial do snapshot.

A ligação entra no pacote como mais uma linha de `correlacoes_oficiais`, marcada com a fonte "lei": o
Jurista precisa considerá-la como hipótese ou justificar por que a descartou, como faz com a tabela.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Ligacao:
    cclasstrib: str
    prefixos: tuple[str, ...]  # posições do NCM que têm essa natureza
    artigo: str
    natureza: str  # o que a lei alcança, em poucas palavras
    condicao: str  # o que precisa ser verdade para o item (vira condição da hipótese)
    excecao: str = ""
    observacao: str = ""
    norma: str = "LC 214/2025"
    tipo_codigo: str = "ncm"
    # Chave fixa do fato que a condição pede: todas as teses perguntam a mesma coisa com o mesmo nome, e
    # uma resposta vale para todas (antes, cada tese inventava a sua: "medicamento_lista_art146",
    # "consta_lista_aliquota_zero"… e o operador respondia cinco vezes, com respostas diferentes).
    fato: str = ""


# Posições do NCM em que há medicamentos registrados na Anvisa. A própria lista de medicamentos da lei
# (Anexo XIV) usa, além de 30.03 e 30.04, produtos imunológicos e soros (30.02) e meios de contraste
# (3006.30); os anticoncepcionais hormonais ficam em 3006.60. Fora delas, um remédio saía com tributação
# integral porque o Jurista nem recebia a hipótese de medicamento (anticoncepcional, 02/10/2026).
_MEDICAMENTOS = ("3002", "3003", "3004", "300630", "300660")

_IN_NATURA = ("01", "02", "03", "04", "06", "07", "08", "09", "10", "12", "14", "4401", "4403")

LIGACOES: tuple[Ligacao, ...] = (
    Ligacao(
        "200009",
        _MEDICAMENTOS,
        "146",
        "Medicamentos registrados na Anvisa da lista de alíquota zero",
        "O medicamento consta da lista oficial de alíquota zero (art. 146, § 3º): destinado, pelo registro "
        "sanitário, a doenças raras ou negligenciadas, oncologia, diabetes, HIV/aids e outras IST, doenças "
        "cardiovasculares ou ao Programa Farmácia Popular.",
        observacao="As hipóteses do § 1º, I e II (compra por órgão público ou entidade Cebas) dependem do "
        "comprador: não valem para a venda ao consumidor.",
        fato="medicamento_aliquota_zero_art146",
    ),
    Ligacao(
        "200032",
        _MEDICAMENTOS,
        "133",
        "Medicamentos registrados na Anvisa ou produzidos por farmácias de manipulação (redução de 60%)",
        "Medicamento registrado na Anvisa ou produzido por farmácia de manipulação.",
        excecao="Medicamentos da lista de alíquota zero do art. 146 (cClassTrib 200009).",
        observacao="Para medicamento industrializado ou importado, a redução exige que o fabricante cumpra a "
        "sistemática da CMED ou tenha compromisso com a União e o CGIBS (art. 133, § 2º); presuma a "
        "regularidade do produto vendido em farmácia, salvo indicação em contrário.",
        fato="medicamento_registrado_anvisa",
    ),
    Ligacao(
        "200053",
        ("3002",),
        "146",
        "Soros e vacinas registrados na Anvisa (alíquota zero)",
        "O item é soro ou vacina registrado na Anvisa (art. 146, § 1º, III).",
        fato="soro_ou_vacina_registrado_anvisa",
    ),
    Ligacao(
        "200036",
        _IN_NATURA,
        "137",
        "Produtos agropecuários, aquícolas, pesqueiros, florestais e extrativistas vegetais in natura (redução de 60%)",
        "O produto está in natura (art. 137, § 1º): sem processo de industrialização e sem embalagem de "
        "apresentação; admite secagem, limpeza, debulha, descaroçamento, congelamento, resfriamento ou simples "
        "acondicionamento só para transporte, armazenamento ou exposição.",
        observacao="Se o código também estiver num anexo com benefício maior (ex.: cesta básica, Anexo XV), "
        "o anexo prevalece.",
        fato="produto_in_natura",
    ),
    Ligacao(
        "410008",
        ("4901", "4902", "4903"),
        "9",
        "Livros, jornais e periódicos (imunidade)",
        "O item é livro, jornal ou periódico (art. 9º, IV).",
        fato="livro_jornal_ou_periodico",
    ),
    Ligacao(
        "410008",
        ("4801",),
        "9",
        "Papel destinado à impressão de livros, jornais e periódicos (imunidade)",
        "O papel é destinado à impressão de livros, jornais ou periódicos (art. 9º, IV).",
        fato="papel_para_impressao_de_livros",
    ),
    Ligacao(
        "410009",
        ("8523",),
        "9",
        "Fonogramas e videofonogramas musicais brasileiros (imunidade)",
        "O suporte contém fonograma ou videofonograma musical produzido no Brasil, com obras de autores "
        "brasileiros ou interpretadas por artistas brasileiros (art. 9º, V).",
        excecao="Etapa de replicação industrial de mídias ópticas de leitura a laser.",
        fato="fonograma_musical_brasileiro",
    ),
)


# Anexos cuja ligação com o cClassTrib a tabela oficial não registra (o código não traz o número do anexo):
# o Anexo XIV é "Medicamentos submetidos à redução a zero das alíquotas", o tratamento do 200009 (art. 146).
ANEXOS_SEM_CORRELACAO: dict[int, tuple[str, ...]] = {14: ("200009",)}


def ligacoes(tipo_codigo: str, codigo: str) -> list[Ligacao]:
    """Ligações que alcançam este código (pela posição do NCM), na ordem do catálogo."""
    return [lg for lg in LIGACOES if lg.tipo_codigo == tipo_codigo and codigo.startswith(lg.prefixos)]


def condicao_do_fato(fato: str) -> str | None:
    """A condição da lei que um fato de chave fixa verifica (serve de pergunta quando a tese não trouxe uma)."""
    for lg in LIGACOES:
        if lg.fato == fato:
            return lg.condicao
    return None
