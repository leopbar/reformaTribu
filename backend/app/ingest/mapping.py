"""Mapeamento de colunas: detecção automática por nome e por conteúdo."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass

from app.core.codes import gtin_valido, somente_digitos


@dataclass(frozen=True)
class Campo:
    chave: str
    rotulo: str
    obrigatorio: bool
    sinonimos: tuple[str, ...]
    descricao: str


CAMPOS: tuple[Campo, ...] = (
    Campo(
        "descricao",
        "Descrição do item",
        True,
        (
            "descricao",
            "descricao do produto",
            "descricao produto",
            "desc",
            "produto",
            "nome do produto",
            "nome",
            "item",
            "descricao item",
            "mercadoria",
            "servico",
            "descricao servico",
        ),
        "Texto que descreve o produto ou serviço.",
    ),
    Campo(
        "codigo_interno",
        "Código interno",
        True,
        (
            "codigo",
            "cod",
            "codigo interno",
            "cod interno",
            "sku",
            "referencia",
            "ref",
            "id",
            "cod produto",
            "codigo produto",
            "cod item",
            "codigo item",
            "plu",
        ),
        "Código do item no sistema da empresa. Se não houver, o sistema gera um.",
    ),
    Campo(
        "ncm",
        "NCM atual",
        False,
        ("ncm", "cod ncm", "codigo ncm", "classificacao fiscal", "class fiscal", "ncm sh", "ncm/sh"),
        "NCM cadastrado hoje (8 dígitos).",
    ),
    Campo("nbs", "NBS atual", False, ("nbs", "codigo nbs", "cod nbs"), "NBS cadastrada (serviços)."),
    Campo(
        "tipo",
        "Tipo (produto ou serviço)",
        False,
        ("tipo", "tipo item", "produto servico", "prod serv", "natureza"),
        "Produto ou serviço.",
    ),
    Campo(
        "gtin",
        "GTIN / código de barras",
        False,
        ("ean", "gtin", "codigo de barras", "cod barras", "barras", "ean13", "cod ean", "codigo ean"),
        "",
    ),
    Campo("cest", "CEST", False, ("cest", "codigo cest"), ""),
    Campo("unidade", "Unidade", False, ("un", "unid", "unidade", "und", "um", "unidade medida"), ""),
    Campo("marca", "Marca", False, ("marca", "fabricante"), ""),
    Campo(
        "categoria",
        "Categoria interna",
        False,
        ("categoria", "grupo", "departamento", "secao", "familia", "subgrupo", "linha"),
        "",
    ),
    Campo(
        "cst_atual",
        "CST do IBS/CBS atual",
        False,
        ("cst ibs cbs", "cst ibscbs", "cst ibs", "cst cbs", "cst_ibs_cbs", "cst reforma"),
        "",
    ),
    Campo(
        "cclasstrib_atual",
        "cClassTrib atual",
        False,
        ("cclasstrib", "classtrib", "class trib", "c class trib", "classificacao tributaria"),
        "",
    ),
)

CAMPOS_POR_CHAVE = {c.chave: c for c in CAMPOS}


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", t)).strip()


def _nota_nome(campo: Campo, coluna: str) -> float:
    n = _norm(coluna)
    if not n:
        return 0.0
    if n in (_norm(s) for s in campo.sinonimos):
        return 1.0
    palavras = set(n.split())
    melhor = 0.0
    for s in campo.sinonimos:
        sn = _norm(s)
        if len(sn) >= 3 and sn in n:
            melhor = max(melhor, 0.7)
        elif set(sn.split()) <= palavras:
            melhor = max(melhor, 0.6)
    # "cst" isolado costuma ser o CST do ICMS: não mapear como CST do IBS/CBS.
    if campo.chave == "cst_atual" and not ({"ibs", "cbs"} & palavras):
        return 0.0
    return melhor


def _nota_conteudo(campo: Campo, valores: list[str]) -> float:
    vals = [v for v in valores if v][:200]
    if not vals:
        return 0.0
    d = [somente_digitos(v) for v in vals]

    def frac(cond: list[bool]) -> float:
        return sum(cond) / len(cond)

    if campo.chave == "ncm":
        return 0.8 * frac([len(x) in (7, 8) and not re.search(r"[a-zA-Z]", v) for x, v in zip(d, vals, strict=True)])
    if campo.chave == "nbs":
        return 0.8 * frac([len(x) == 9 and v.count(".") >= 2 for x, v in zip(d, vals, strict=True)])
    if campo.chave == "gtin":
        return 0.9 * frac([gtin_valido(x) for x in d])
    if campo.chave == "cest":
        return 0.5 * frac([len(x) == 7 for x in d])
    if campo.chave == "descricao":
        return 0.6 * frac([len(v) >= 6 and len(re.findall(r"[A-Za-zÀ-ú]", v)) >= 4 for v in vals])
    if campo.chave == "cclasstrib_atual":
        return 0.6 * frac([len(x) == 6 for x in d])
    if campo.chave == "codigo_interno":
        unicos = len(set(vals)) / len(vals)
        return 0.35 * unicos * frac([len(v) <= 20 for v in vals])
    return 0.0


def sugerir_mapeamento(colunas: list[str], linhas: list[list[str]]) -> dict[str, str | None]:
    """Devolve {campo: nome da coluna | None}, escolhendo o melhor par (campo, coluna) sem repetição."""
    amostra = linhas[:300]
    notas: list[tuple[float, str, str]] = []
    for i, col in enumerate(colunas):
        valores = [linha[i] if i < len(linha) else "" for linha in amostra]
        for campo in CAMPOS:
            nota = _nota_nome(campo, col) * 1.2 + _nota_conteudo(campo, valores)
            if nota >= 0.55:
                notas.append((nota, campo.chave, col))
    resultado: dict[str, str | None] = {c.chave: None for c in CAMPOS}
    usadas: set[str] = set()
    for _nota, chave, col in sorted(notas, reverse=True):
        if resultado[chave] is None and col not in usadas:
            resultado[chave] = col
            usadas.add(col)
    return resultado


def assinatura_colunas(colunas: list[str]) -> str:
    return hashlib.sha256("|".join(_norm(c) for c in colunas).encode()).hexdigest()


def validar_mapeamento(mapeamento: dict[str, str | None], colunas: list[str]) -> list[str]:
    erros = []
    if not mapeamento.get("descricao"):
        erros.append("Indique a coluna com a descrição do item.")
    for campo, col in mapeamento.items():
        if campo not in CAMPOS_POR_CHAVE:
            erros.append(f"Campo desconhecido: {campo}.")
        elif col and col not in colunas:
            erros.append(f"A coluna “{col}” não existe na planilha.")
    usadas = [c for c in mapeamento.values() if c]
    if len(usadas) != len(set(usadas)):
        erros.append("A mesma coluna foi usada para mais de um campo.")
    return erros
