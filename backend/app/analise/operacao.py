"""Regimes decididos pela operação, e não pelo código do produto (ADR 0026).

A maior parte do enquadramento sai do produto: o NCM/NBS aparece num anexo ou na correlação oficial e o
Jurista estuda a família. Alguns tratamentos, porém, dependem de QUEM vende e de COMO o item é fornecido,
qualquer que seja o NCM:

- bares, restaurantes e lanchonetes fornecendo alimentação preparada no local (LC 214, arts. 273–276);
- farmácia de manipulação fornecendo medicamento manipulado (LC 214, art. 133).

Esses regimes ficam num catálogo declarativo, igual para todas as empresas e todos os itens, em vez de
serem redescobertos a cada tese de família (o que dava respostas diferentes para itens iguais). Cada
regime vira uma hipótese no mesmo formato das hipóteses do Jurista, avaliada ANTES delas: se as condições
se confirmam, o cClassTrib sai mesmo sem NCM definido (o NCM segue em paralelo, para a nota fiscal); se
uma exceção se confirma, valem as hipóteses do produto.

Regras de ouro mantidas:
- um regime só entra quando o dossiê da empresa o ativa (fato informado ou cadastro);
- fato de item vem de pessoa, da descrição explícita ou do próprio código (derivação determinística,
  registrada com a origem); presunção pelo perfil só existe onde a lei a sustenta e fica documentada;
- a lista de cClassTrib e os artigos citados vêm da base oficial do snapshot da auditoria.

Fora deste catálogo, por decisão (ver ADR 0026): tratamentos que dependem do COMPRADOR ou do destino
(administração pública, pessoa com deficiência, produtor rural, exportação, Zona Franca) pertencem a
outros cenários de operação, não ao cadastro do item na venda comum ao consumidor.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.analise.fatos import DESCONHECIDO, ROTULOS_ORIGEM, chave, valor
from app.models import CClassTribCode
from app.models.enums import OrigemFato

ORIGEM = "operacao"  # marca das hipóteses criadas por este catálogo
PREFIXO_REF = "OP"  # referências aos artigos citados pelos regimes (OP273, OP275…)


# ------------------------------------------------------------------------------ catálogo --
@dataclass(frozen=True)
class CondicaoEmpresa:
    """Fato do dossiê: `valores` aceitos (ou prefixos, para CNAE)."""

    fato: str
    valores: tuple[str, ...]
    prefixo: bool = False
    descricao: str = ""

    def atende(self, fatos: dict[str, Any]) -> bool:
        v = _valor(fatos, self.fato)
        if v == DESCONHECIDO:
            return False
        if self.prefixo:
            digitos = "".join(c for c in v if c.isdigit())
            return any(digitos.startswith(p) for p in self.valores)
        return v in self.valores


@dataclass(frozen=True)
class Presuncao:
    """Valor de um fato de item que o perfil da empresa já determina, pela própria lei."""

    quando: CondicaoEmpresa
    valor: str
    explicacao: str


@dataclass(frozen=True)
class Derivacao:
    """Valor de um fato de item que o código do produto determina (primeira regra que casar vale).

    `valor` None = o código não decide (a descrição ou uma pessoa decidem)."""

    prefixos: tuple[str, ...]
    valor: str | None
    explicacao: str
    tipo_codigo: str = "ncm"


@dataclass(frozen=True)
class FatoOperacao:
    fato: str
    pergunta: str
    como_identificar: str
    opcoes: tuple[str, ...] = ("sim", "nao")
    presuncoes: tuple[Presuncao, ...] = ()
    derivacoes: tuple[Derivacao, ...] = ()


@dataclass(frozen=True)
class Regime:
    id: str  # curto: a hipótese gravada no item é "OP-<id>" (coluna de 20 caracteres)
    titulo: str
    tipo: str  # regime_especifico | beneficio (mesmos tipos das hipóteses do Jurista)
    cclasstrib: str
    norma: str
    artigos: tuple[str, ...]  # artigos citados como fundamento (o texto vem da base oficial)
    ativo_quando: tuple[CondicaoEmpresa, ...]  # basta uma
    condicoes: tuple[tuple[str, str, str], ...]  # (fato, valor exigido, explicação)
    excecoes: tuple[tuple[str, str, str], ...] = ()  # (fato, valor que exclui, descrição)
    afastado_quando: tuple[CondicaoEmpresa, ...] = ()  # exceções que valem para a empresa toda
    explicacao: str = ""
    # O enquadramento não depende do NCM/NBS: o cClassTrib sai mesmo sem código definido.
    independe_do_codigo: bool = True
    # O cClassTrib só existe por causa da operação (nenhum produto o alcança por si). Se False, o mesmo
    # código também vale pelo produto (ex.: 200032 serve ao medicamento industrializado registrado na
    # Anvisa) e continua disponível para a tese da família.
    exclusivo: bool = True


FATOS: dict[str, FatoOperacao] = {
    f.fato: f
    for f in (
        FatoOperacao(
            "preparado_no_estabelecimento",
            "Este item é preparado no próprio estabelecimento (feito na cozinha, no balcão ou na máquina), "
            "ou é comprado pronto de terceiros e só revendido?",
            "Explícito 'sim' quando a descrição nomeia um prato ou uma bebida feita na hora: PRATO, PORÇÃO, "
            "EXECUTIVO, MARMITA, GRELHADO, À ..., LANCHE, SANDUÍCHE, CAFÉ ESPRESSO/EXPRESSO, CAPPUCCINO, SUCO "
            "NATURAL, VITAMINA, LIMONADA, DRINQUE, 'DA CASA', 'CASEIRO'. Explícito 'nao' quando nomeia embalagem "
            "ou produto industrial pronto: LATA, LONG NECK, GARRAFA, PET, CAIXINHA, 'ÁGUA MINERAL', marca de "
            "fabricante com volume de embalagem.",
            presuncoes=(),
        ),
        FatoOperacao(
            "servido_como_alimentacao",
            "Este item é servido como refeição, lanche ou bebida pronta para consumo (no local, para viagem ou "
            "por entrega), e não vendido como mercadoria (pão por quilo, bolo inteiro de vitrine, pacote)?",
            "Explícito 'sim' quando a descrição indica porção, prato, lanche, dose, xícara, copo ou taça. "
            "Explícito 'nao' quando indica venda por peso ou unidade de vitrine: KG, 'POR QUILO', PACOTE, INTEIRO.",
            presuncoes=(
                Presuncao(
                    CondicaoEmpresa("segmento", ("restaurante",)),
                    "sim",
                    "O estabelecimento é bar, restaurante ou lanchonete: o que ele prepara e vende é fornecimento de "
                    "alimentação (LC 214, art. 273).",
                ),
            ),
        ),
        FatoOperacao(
            "bebida_alcoolica",
            "Este item é uma bebida alcoólica (cerveja, chope, vinho, destilado, drinque com álcool)?",
            "Explícito 'sim' quando nomeia cerveja, chope, vinho, espumante, cachaça, vodca, uísque, gim, licor ou "
            "drinque com álcool (caipirinha…). Explícito 'nao' quando nomeia comida, café, chá, suco, refrigerante, "
            "água, ou versão 'SEM ÁLCOOL'.",
            derivacoes=(
                Derivacao(
                    ("2203", "2204", "2205", "2207", "2208"),
                    "sim",
                    "o NCM é de bebida alcoólica (cerveja, vinho, vermute, álcool etílico ou destilado)",
                ),
                Derivacao(("2201", "2202", "2209"), "nao", "o NCM é de água, bebida não alcoólica ou vinagre"),
                Derivacao(("2206",), None, "o NCM 22.06 reúne bebidas fermentadas com e sem álcool"),
                Derivacao(("",), "nao", "o NCM não é de bebida (fora do capítulo 22)"),
                Derivacao(("",), "nao", "o código é de serviço (NBS), não de bebida", tipo_codigo="nbs"),
            ),
        ),
        FatoOperacao(
            "manipulado_no_estabelecimento",
            "Este item é manipulado na própria farmácia (fórmula manipulada), ou é produto industrializado revendido?",
            "Explícito 'sim' quando a descrição diz MANIPULADO, FÓRMULA, FORMULAÇÃO, cápsulas com dosagem da "
            "casa. Explícito 'nao' quando nomeia marca de laboratório, caixa, blíster, genérico ou similar.",
        ),
        FatoOperacao(
            "e_medicamento",
            "Este item é um medicamento (e não cosmético, suplemento ou produto de higiene)?",
            "Explícito 'sim' quando a descrição nomeia princípio ativo com dosagem para tratamento. Explícito "
            "'nao' quando nomeia creme hidratante, xampu, protetor solar, suplemento alimentar, vitamina de "
            "prateleira sem finalidade terapêutica declarada.",
            derivacoes=(
                Derivacao(("3003", "3004"), "sim", "o NCM é de medicamento (posições 30.03 e 30.04)"),
                Derivacao(("33", "2106"), "nao", "o NCM é de cosmético, higiene ou suplemento alimentar"),
            ),
        ),
    )
}


REGIMES: tuple[Regime, ...] = (
    Regime(
        id="restaurante",
        titulo="Regime específico de bares e restaurantes (redução de 40%)",
        tipo="regime_especifico",
        cclasstrib="200047",
        norma="LC 214/2025",
        artigos=("273", "274", "275"),
        ativo_quando=(
            CondicaoEmpresa("fornece_refeicoes", ("sim",), descricao="serve refeições ou lanches"),
            CondicaoEmpresa("segmento", ("restaurante",), descricao="bar, restaurante ou lanchonete"),
        ),
        condicoes=(
            (
                "preparado_no_estabelecimento",
                "sim",
                "Alimento ou bebida adquirido de terceiros e não preparado no local fica fora (art. 273, § 2º, II).",
            ),
            (
                "servido_como_alimentacao",
                "sim",
                "O regime alcança o fornecimento de alimentação, não a venda de mercadoria (art. 273, caput).",
            ),
        ),
        excecoes=(
            ("bebida_alcoolica", "sim", "Bebida alcoólica, ainda que preparada no local (art. 273, § 2º, III)."),
        ),
        afastado_quando=(
            CondicaoEmpresa(
                "cnae",
                ("5620101",),
                prefixo=True,
                descricao="fornecimento de alimentação para empresas sob contrato (art. 273, § 2º, I)",
            ),
        ),
        explicacao=(
            "Alimentação e bebidas não alcoólicas preparadas no estabelecimento por bar, restaurante ou lanchonete "
            "seguem o regime específico, com redução de 40% do IBS e da CBS, qualquer que seja o NCM do item."
        ),
    ),
    Regime(
        id="manipulacao",
        titulo="Medicamento produzido por farmácia de manipulação (redução de 60%)",
        tipo="beneficio",
        cclasstrib="200032",
        norma="LC 214/2025",
        artigos=("133",),
        ativo_quando=(CondicaoEmpresa("manipula_medicamentos", ("sim",), descricao="manipula medicamentos"),),
        condicoes=(
            ("manipulado_no_estabelecimento", "sim", "O benefício alcança o medicamento produzido pela farmácia."),
            ("e_medicamento", "sim", "Cosmético ou suplemento manipulado não é medicamento (art. 133, caput)."),
        ),
        explicacao=(
            "Medicamentos produzidos por farmácias de manipulação têm redução de 60% do IBS e da CBS, "
            "qualquer que seja o NCM."
        ),
        exclusivo=False,
    ),
)

POR_ID = {r.id: r for r in REGIMES}


def cclasstrib_da_operacao() -> set[str]:
    """cClassTrib que só este catálogo decide (hipóteses do Jurista com eles são ignoradas)."""
    return {r.cclasstrib for r in REGIMES if r.exclusivo}


# --------------------------------------------------------------------------- avaliação --
def _valor(fatos: dict[str, Any], f: str) -> str:
    r = fatos.get(chave(f))
    if r is None:
        return DESCONHECIDO
    if isinstance(r, dict):
        return valor(r.get("valor"))
    return valor(getattr(r, "valor", r))


@dataclass
class Aplicaveis:
    regimes: list[Regime] = field(default_factory=list)
    afastados: list[tuple[Regime, str]] = field(default_factory=list)  # (regime, motivo) para a empresa toda


def regimes_da_empresa(fatos_empresa: dict[str, Any]) -> Aplicaveis:
    """Regimes que o dossiê ativa para esta empresa (e os que ele afasta, com o motivo)."""
    saida = Aplicaveis()
    for r in REGIMES:
        if not any(c.atende(fatos_empresa) for c in r.ativo_quando):
            continue
        barreira = next((c for c in r.afastado_quando if c.atende(fatos_empresa)), None)
        if barreira is not None:
            saida.afastados.append((r, barreira.descricao))
        else:
            saida.regimes.append(r)
    return saida


def hipoteses(regimes: list[Regime]) -> list[dict[str, Any]]:
    """Hipóteses no formato das teses, com a marca `origem = operacao`."""
    saida = []
    for r in regimes:
        saida.append(
            {
                "id": f"OP-{r.id}",
                "titulo": r.titulo,
                "tipo": r.tipo,
                "cclasstrib": r.cclasstrib,
                "condicoes": [{"fato": f, "valor_exigido": v, "explicacao": e} for f, v, e in r.condicoes],
                "excecoes": [{"descricao": d, "fato": f, "valor_que_exclui": v} for f, v, d in r.excecoes],
                "fundamentos": [{"ref": f"{PREFIXO_REF}{a}", "trecho": ""} for a in r.artigos]
                + [{"ref": f"T{r.cclasstrib}", "trecho": ""}],
                "explicacao": r.explicacao,
                "origem": ORIGEM,
                "independe_do_codigo": r.independe_do_codigo,
            }
        )
    return saida


def fatos_de_item(regimes: list[Regime]) -> list[FatoOperacao]:
    nomes = dict.fromkeys(f for r in regimes for f, *_ in (*r.condicoes, *r.excecoes))
    return [FATOS[n] for n in nomes if n in FATOS]


def fatos_necessarios(regimes: list[Regime]) -> list[dict[str, Any]]:
    """Mesmo formato de `fatos_necessarios` das teses (perguntas e Leitor de fatos)."""
    return [
        {
            "fato": f.fato,
            "escopo": "item",
            "pergunta": f.pergunta,
            "opcoes": list(f.opcoes),
            "como_identificar_na_descricao": f.como_identificar,
        }
        for f in fatos_de_item(regimes)
    ]


def fatos_implicitos(
    regimes: list[Regime], fatos_empresa: dict[str, Any], tipo_codigo: str | None, codigo: str | None
) -> dict[str, dict[str, Any]]:
    """Fatos de item que o perfil da empresa (presunção legal) ou o código (derivação) já determinam.

    Não são gravados: são recalculados a cada avaliação, com a origem à mostra. Um fato informado por
    pessoa ou explícito na descrição prevalece sobre eles."""
    saida: dict[str, dict[str, Any]] = {}
    for f in fatos_de_item(regimes):
        for p in f.presuncoes:
            if p.quando.atende(fatos_empresa):
                saida[f.fato] = _registro(f.fato, p.valor, OrigemFato.CADASTRO, p.explicacao)
                break
        if f.fato in saida or not codigo:
            continue
        for d in f.derivacoes:
            if d.tipo_codigo == tipo_codigo and any(codigo.startswith(p) for p in d.prefixos):
                if d.valor is not None:
                    saida[f.fato] = _registro(f.fato, d.valor, OrigemFato.CODIGO, f"{d.explicacao} ({codigo})")
                break
    return saida


def _registro(fato: str, v: str, origem: str, evidencia: str) -> dict[str, Any]:
    return {
        "atributo": fato,
        "valor": v,
        "origem": origem,
        "origem_rotulo": ROTULOS_ORIGEM.get(origem, origem),
        "escopo": "item",
        "grupo": None,
        "evidencia": evidencia,
        "id": None,
        "autor": None,
    }


# ------------------------------------------------------------------ material da base oficial --
@dataclass
class Material:
    refs: dict[str, dict[str, Any]] = field(default_factory=dict)
    cclasstrib: dict[str, dict[str, Any]] = field(default_factory=dict)


def _vigente(inicio: date | None, fim: date | None, d: date) -> bool:
    return (inicio is None or inicio <= d) and (fim is None or fim >= d)


def material(
    session: Session,
    regimes: list[Regime],
    versoes: dict[str, Any],
    data_referencia: date,
    tipo_codigo: str | None,
) -> Material:
    """Artigos citados e entradas cClassTrib dos regimes, lidos da base do snapshot (nada de memória)."""
    m = Material()
    if not regimes:
        return m
    v_lc, v_cct = versoes.get("lc214"), versoes.get("cclasstrib")
    artigos = sorted({a for r in regimes for a in r.artigos})
    if v_lc:
        for p in session.execute(
            text(
                "SELECT DISTINCT ON (artigo) id, artigo, texto, norma, vigencia_inicio, vigencia_fim "
                "FROM legal_provisions WHERE version_id = :v AND tipo = 'artigo' AND artigo = ANY(:a) "
                "ORDER BY artigo, ordem"
            ),
            {"v": uuid.UUID(str(v_lc)), "a": artigos},
        ):
            if not _vigente(p.vigencia_inicio, p.vigencia_fim, data_referencia):
                continue
            m.refs[f"{PREFIXO_REF}{p.artigo}"] = {
                "tipo": "trecho",
                "id": str(p.id),
                "norma": p.norma,
                "local": f"Art. {p.artigo}",
                "texto": (p.texto or "")[:1500],
            }
    if v_cct:
        doc = "ind_nfse" if tipo_codigo == "nbs" else "ind_nfce"
        for c in session.scalars(
            select(CClassTribCode).where(
                CClassTribCode.version_id == uuid.UUID(str(v_cct)),
                CClassTribCode.codigo.in_(sorted({r.cclasstrib for r in regimes})),
            )
        ):
            info = {
                "ref": f"T{c.codigo}",
                "codigo": c.codigo,
                "cst": c.cst,
                "nome": c.nome,
                "reducao_ibs_pct": float(c.perc_red_ibs or 0),
                "reducao_cbs_pct": float(c.perc_red_cbs or 0),
                "tipo_aliquota": c.tipo_aliquota,
                "vigente_na_data": _vigente(c.data_inicio, c.data_fim, data_referencia),
                "permitido_no_documento": bool(getattr(c, doc) or c.ind_nfe),
            }
            m.cclasstrib[c.codigo] = info
            m.refs[f"T{c.codigo}"] = {"tipo": "cclasstrib", **info}
    return m


def fundamentar(hips: list[dict[str, Any]], m: Material) -> list[dict[str, Any]]:
    """Preenche o trecho citado de cada fundamento com o texto da base (só as referências que existem)."""
    saida = []
    for h in hips:
        fund = []
        for f in h["fundamentos"]:
            r = m.refs.get(f["ref"])
            if r is None:
                continue
            trecho = r.get("texto") or r.get("nome") or ""
            fund.append({"ref": f["ref"], "trecho": trecho[:300]})
        saida.append({**h, "fundamentos": fund})
    return saida
