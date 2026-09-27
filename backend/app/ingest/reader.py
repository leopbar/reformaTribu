"""Leitura segura de planilhas enviadas (XLSX, XLS, CSV).

- O tipo real é detectado pelo conteúdo (assinatura do arquivo), não pela extensão.
- Planilhas com macros (VBA) são rejeitadas.
- Todas as células são lidas como texto para preservar zeros à esquerda e códigos longos.
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
import zipfile
from dataclasses import dataclass, field
from typing import Any

import polars as pl


class ArquivoInvalido(Exception):
    def __init__(self, mensagem: str, acao: str | None = None) -> None:
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.acao = acao


ASSINATURA_ZIP = b"PK\x03\x04"
ASSINATURA_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


@dataclass
class Planilha:
    formato: str
    colunas: list[str]
    linhas: list[list[str]]
    encoding: str | None = None
    separador: str | None = None
    planilha: str | None = None
    planilhas: list[str] = field(default_factory=list)
    linha_cabecalho: int = 0

    @property
    def total(self) -> int:
        return len(self.linhas)

    def registros(self) -> list[dict[str, str]]:
        return [dict(zip(self.colunas, linha, strict=False)) for linha in self.linhas]


def detectar_formato(dados: bytes, nome: str) -> str:
    if dados.startswith(ASSINATURA_ZIP):
        try:
            with zipfile.ZipFile(io.BytesIO(dados)) as z:
                nomes = set(z.namelist())
                if "xl/vbaProject.bin" in nomes or any(n.lower().endswith("vbaproject.bin") for n in nomes):
                    raise ArquivoInvalido(
                        "A planilha contém macros e foi recusada por segurança.",
                        "Salve o arquivo como .xlsx (Pasta de Trabalho do Excel, sem macros) e envie novamente.",
                    )
                if "xl/workbook.xml" not in nomes:
                    raise ArquivoInvalido("O arquivo compactado não é uma planilha do Excel.")
                tipos = (
                    z.read("[Content_Types].xml").decode("utf-8", "ignore") if "[Content_Types].xml" in nomes else ""
                )
                if "macroEnabled" in tipos:
                    raise ArquivoInvalido(
                        "A planilha contém macros e foi recusada por segurança.",
                        "Salve como .xlsx sem macros e envie novamente.",
                    )
        except zipfile.BadZipFile as e:
            raise ArquivoInvalido("O arquivo está corrompido ou incompleto.") from e
        return "xlsx"
    if dados.startswith(ASSINATURA_OLE):
        if b"_VBA_PROJECT" in dados or b"V\x00B\x00A\x00" in dados:
            raise ArquivoInvalido(
                "A planilha contém macros e foi recusada por segurança.",
                "Salve como .xlsx sem macros e envie novamente.",
            )
        return "xls"
    amostra = dados[:4096]
    if b"\x00" in amostra:
        raise ArquivoInvalido("Formato de arquivo não suportado.", "Envie uma planilha .xlsx, .xls ou .csv.")
    if nome.lower().endswith((".xlsx", ".xls", ".xlsm")):
        raise ArquivoInvalido("O conteúdo do arquivo não corresponde a uma planilha do Excel.")
    return "csv"


def _decodificar(dados: bytes) -> tuple[str, str]:
    for enc in ("utf-8-sig", "utf-8"):
        try:
            return dados.decode(enc), "utf-8"
        except UnicodeDecodeError:
            continue
    # Latin-1/Windows-1252 decodificam qualquer byte; cp1252 cobre aspas e travessões do Excel.
    try:
        return dados.decode("cp1252"), "windows-1252"
    except UnicodeDecodeError:
        return dados.decode("latin-1"), "latin-1"


def _detectar_separador(texto: str) -> str:
    amostra = "\n".join(texto.splitlines()[:30])
    try:
        return csv.Sniffer().sniff(amostra, delimiters=";,\t|").delimiter
    except csv.Error:
        contagens = {s: amostra.count(s) for s in (";", ",", "\t", "|")}
        return max(contagens, key=lambda k: contagens[k])


def _texto_celula(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        if v.is_integer():
            return str(int(v))
        return repr(v)
    return str(v).strip()


SINONIMOS_CABECALHO = (
    "descr",
    "produto",
    "item",
    "ncm",
    "codigo",
    "cod",
    "ean",
    "gtin",
    "nbs",
    "servico",
    "cest",
    "unid",
    "marca",
)


def _norm(t: str) -> str:
    return unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower().strip()


def detectar_cabecalho(linhas: list[list[str]]) -> int:
    melhor, nota_melhor = 0, -1.0
    for i, linha in enumerate(linhas[:25]):
        preenchidas = [c for c in linha if c]
        if len(preenchidas) < 2:
            continue
        textuais = sum(1 for c in preenchidas if not re.fullmatch(r"[\d.,/\- ]+", c))
        conhecidas = sum(1 for c in preenchidas if any(s in _norm(c) for s in SINONIMOS_CABECALHO))
        nota = conhecidas * 3 + textuais / len(preenchidas)
        if nota > nota_melhor:
            melhor, nota_melhor = i, nota
        if conhecidas >= 2:
            return i
    return melhor


def _nomes_unicos(nomes: list[str]) -> list[str]:
    vistos: dict[str, int] = {}
    saida = []
    for i, n in enumerate(nomes):
        base = n.strip() or f"Coluna {i + 1}"
        if base in vistos:
            vistos[base] += 1
            base = f"{base} ({vistos[base]})"
        else:
            vistos[base] = 1
        saida.append(base)
    return saida


def ler_planilha(
    dados: bytes, nome: str, planilha: str | None = None, linha_cabecalho: int | None = None, max_linhas: int = 100_000
) -> Planilha:
    formato = detectar_formato(dados, nome)
    planilhas: list[str] = []
    encoding = separador = None
    if formato in ("xlsx", "xls"):
        import fastexcel

        try:
            leitor = fastexcel.read_excel(dados)
        except Exception as e:
            raise ArquivoInvalido("Não foi possível abrir a planilha. O arquivo pode estar corrompido.") from e
        planilhas = list(leitor.sheet_names)
        if not planilhas:
            raise ArquivoInvalido("A planilha não tem abas.")
        aba = planilha if planilha in planilhas else planilhas[0]
        planilha = aba
        folha = leitor.load_sheet(aba, header_row=None, dtypes="string", schema_sample_rows=None)
        df = folha.to_polars()
        bruto = [[_texto_celula(v) for v in row] for row in df.iter_rows()]
    else:
        texto, encoding = _decodificar(dados)
        separador = _detectar_separador(texto)
        leitor_csv = csv.reader(io.StringIO(texto), delimiter=separador)
        bruto = [[c.strip() for c in row] for row in leitor_csv]
    # remove linhas completamente vazias do fim
    while bruto and not any(bruto[-1]):
        bruto.pop()
    if not bruto:
        raise ArquivoInvalido("A planilha está vazia.")
    cab = detectar_cabecalho(bruto) if linha_cabecalho is None else linha_cabecalho
    largura = max(len(r) for r in bruto[: cab + 200])
    colunas = _nomes_unicos([(bruto[cab][i] if i < len(bruto[cab]) else "") for i in range(largura)])
    linhas = [(r + [""] * largura)[:largura] for r in bruto[cab + 1 :]]
    if len(linhas) > max_linhas:
        raise ArquivoInvalido(
            f"A planilha tem {len(linhas):,} linhas; o limite é {max_linhas:,}.".replace(",", "."),
            "Divida o arquivo em partes menores e crie uma auditoria para cada parte.",
        )
    return Planilha(
        formato=formato,
        colunas=colunas,
        linhas=linhas,
        encoding=encoding,
        separador=separador,
        planilha=planilha,
        planilhas=planilhas,
        linha_cabecalho=cab,
    )


def para_dataframe(p: Planilha) -> pl.DataFrame:
    return pl.DataFrame(p.linhas, schema=p.colunas, orient="row")
