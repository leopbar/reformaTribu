"""Importador do texto da LC 214/2025 (página compilada do Planalto).

- Descarta o texto revogado (riscado com <strike>, <s> ou <del> na versão compilada).
- Extrai os artigos e, para os Anexos I a XVII, cada item com descrição e códigos citados.
- Os Anexos XVIII em diante alteram tabelas do Simples Nacional (LC 123) e são guardados
  apenas como texto, sem itens.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from bs4 import BeautifulSoup, Tag
from sqlalchemy import insert
from sqlalchemy.orm import Session

from app.core.codes import somente_digitos
from app.models import LegalProvision, RefVersion
from app.models.enums import FonteReferencia
from app.reference.importers.common import Coleta, FormatoInvalido, ativar_versao, criar_versao

ROMANOS = [
    "I",
    "II",
    "III",
    "IV",
    "V",
    "VI",
    "VII",
    "VIII",
    "IX",
    "X",
    "XI",
    "XII",
    "XIII",
    "XIV",
    "XV",
    "XVI",
    "XVII",
    "XVIII",
    "XIX",
    "XX",
    "XXI",
    "XXII",
    "XXIII",
]
ULTIMO_ANEXO_COM_ITENS = 17

_ANEXO = re.compile(r"^ANEXO\s+([IVXL]+)\b", re.I)
_ARTIGO = re.compile(r"^Art\s*\.\s*(\d+)\s*[º°o]?(?:\s*-\s*([A-Z])\b)?", re.U)
_ESPACOS = re.compile(r"\s+")

# Padrões de códigos citados nos anexos (para testes de existência e referência cruzada).
_NBS = re.compile(r"\b\d\.\d{4}(?:\.\d{1,2}){0,2}\b")
_NCM8 = re.compile(r"\b\d{4}\.\d{2}\.\d{2}\b")
_NCM7 = re.compile(r"\b\d{4}\.\d{2}\.\d\b(?!\d)")
# Grafia irregular encontrada na lei: "07.02.00.00" = 0702.00.00.
_NCM8_PONTOS = re.compile(r"\b(\d{2})\.(\d{2})\.(\d{2})\.(\d{2})\b")
_NCM6 = re.compile(r"\b\d{4}\.\d{2}\b(?!\.\d)")
_NCM5 = re.compile(r"\b\d{4}\.\d\b(?!\d)")
_POS = re.compile(r"\b\d{2}\.\d{2}\b(?!\.\d)")
_CAP = re.compile(r"Cap[íi]tulo\s+(\d{1,2})\b", re.I)
_POS4 = re.compile(r"(?<![\d.])\d{4}(?![\d.])")


def romano_para_int(r: str) -> int:
    return ROMANOS.index(r.upper()) + 1 if r.upper() in ROMANOS else 0


def texto(el: Tag) -> str:
    return _ESPACOS.sub(" ", el.get_text(" ", strip=True)).strip()


def extrair_codigos(t: str, coluna_codigos: bool) -> list[str]:
    """Extrai códigos NCM/NBS citados. Posições de 4 dígitos soltas só na coluna de códigos."""
    achados: list[str] = []
    resto = _NCM8_PONTOS.sub(r"\1\2.\3.\4", t)
    for rx in (_NBS, _NCM8, _NCM7, _NCM6, _NCM5):
        for m in rx.finditer(resto):
            achados.append(somente_digitos(m.group(0)))
        resto = rx.sub(" ", resto)
    for m in _POS.finditer(resto):
        achados.append(somente_digitos(m.group(0)))
    resto = _POS.sub(" ", resto)
    for m in _CAP.finditer(resto):
        achados.append(m.group(1).zfill(2))
    if coluna_codigos:
        resto = _CAP.sub(" ", resto)
        for m in _POS4.finditer(resto):
            achados.append(m.group(0))
    return list(dict.fromkeys(achados))


@dataclass
class ItemAnexo:
    anexo: str
    titulo: str
    item: str
    descricao: str
    codigos_texto: str
    codigos: list[str] = field(default_factory=list)


@dataclass
class Artigo:
    numero: str
    texto: str


def parse_lc214(html: bytes) -> tuple[list[Artigo], list[ItemAnexo], dict[str, str]]:
    conteudo = None
    for enc in ("utf-8", "cp1252"):
        try:
            conteudo = html.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if conteudo is None:
        raise FormatoInvalido("Não foi possível ler a página da LC 214/2025.")
    soup = BeautifulSoup(conteudo, "lxml")
    for riscado in soup.find_all(["strike", "s", "del"]):
        riscado.decompose()
    if "214" not in soup.get_text()[:5000]:
        raise FormatoInvalido("A página não parece ser a Lei Complementar nº 214/2025.")

    artigos: list[Artigo] = []
    itens: list[ItemAnexo] = []
    titulos: dict[str, str] = {}
    anexo_atual: str | None = None
    aguardando_titulo = False
    apos_anexos_com_itens = False
    artigo_atual: Artigo | None = None

    for el in soup.find_all(["p", "table"]):
        if el.name == "p":
            if el.find_parent("table") is not None:
                continue
            t = texto(el)
            if not t:
                continue
            m = _ANEXO.match(t)
            if m and len(t) < 60:
                numero = romano_para_int(m.group(1))
                if apos_anexos_com_itens or numero > ULTIMO_ANEXO_COM_ITENS:
                    apos_anexos_com_itens = True
                    anexo_atual = None
                    continue
                anexo_atual = m.group(1).upper()
                aguardando_titulo = True
                artigo_atual = None
                continue
            if anexo_atual and aguardando_titulo:
                titulos[anexo_atual] = t
                aguardando_titulo = False
                continue
            if anexo_atual is None and not apos_anexos_com_itens:
                ma = _ARTIGO.match(t)
                if ma:
                    num_artigo = ma.group(1) + (f"-{ma.group(2)}" if ma.group(2) else "")
                    artigo_atual = Artigo(num_artigo, t)
                    artigos.append(artigo_atual)
                elif artigo_atual is not None:
                    artigo_atual.texto += "\n" + t
            continue

        # Tabela
        if anexo_atual is None or el.find_parent("table") is not None:
            continue
        itens.extend(_itens_da_tabela(el, anexo_atual, titulos.get(anexo_atual, "")))

    # A versão compilada repete artigos alterados; vale a última redação de cada número.
    unicos: dict[str, Artigo] = {}
    for a in artigos:
        unicos[a.numero] = a
    artigos = list(unicos.values())
    if len(artigos) < 100 or not itens:
        raise FormatoInvalido(
            f"Extração incompleta da LC 214/2025 ({len(artigos)} artigos, {len(itens)} itens de anexos). "
            "O formato da página pode ter mudado."
        )
    return artigos, itens, titulos


def _itens_da_tabela(tabela: Tag, anexo: str, titulo: str) -> list[ItemAnexo]:
    saida: list[ItemAnexo] = []
    linhas = tabela.find_all("tr")
    sequencial = 0
    linhas_celulas = [[texto(td) for td in tr.find_all(["td", "th"], recursive=False)] for tr in linhas]
    if linhas_celulas and all(len(c) == 1 for c in linhas_celulas if c):
        # Tabela de uma coluna com linhas alternadas: categoria, depois códigos (ex.: Anexo XVII).
        categoria: str | None = None
        for (c,) in (c for c in linhas_celulas if c):
            if categoria is None:
                categoria = c
                continue
            if re.match(r"^\d", c):
                sequencial += 1
                saida.append(
                    ItemAnexo(anexo, titulo, str(sequencial), categoria, c, extrair_codigos(c, coluna_codigos=True))
                )
                categoria = None
            else:
                # Categoria sem códigos (ex.: serviços): registra e segue.
                sequencial += 1
                saida.append(ItemAnexo(anexo, titulo, str(sequencial), categoria, "", []))
                categoria = c
        if categoria:
            sequencial += 1
            saida.append(ItemAnexo(anexo, titulo, str(sequencial), categoria, "", []))
        return saida
    for tr in linhas:
        celulas = [texto(td) for td in tr.find_all(["td", "th"], recursive=False)]
        celulas = [c for c in celulas if c is not None]
        if len(celulas) < 2 or not any(celulas):
            continue
        cab = " ".join(celulas).upper()
        if celulas[0].upper() in ("ITEM", "ITENS") or ("DESCRI" in cab and "NCM" in cab and len(cab) < 80):
            continue
        if re.fullmatch(r"\d{1,3}(\.\d+)?", celulas[0]):
            item = celulas[0]
            descricao = celulas[1]
            codigos_texto = " ".join(celulas[2:])
        else:
            # Tabelas sem coluna de número (ex.: Anexo XVII): categoria | códigos.
            sequencial += 1
            item = str(sequencial)
            descricao = celulas[0]
            codigos_texto = " ".join(celulas[1:])
        if not descricao:
            continue
        codigos = extrair_codigos(codigos_texto, coluna_codigos=True) if codigos_texto else []
        if not codigos:
            codigos = extrair_codigos(descricao, coluna_codigos=False)
        saida.append(ItemAnexo(anexo, titulo, item, descricao, codigos_texto, codigos))
    return saida


def importar_lc214(
    session: Session, coleta: Coleta, usuario_id: uuid.UUID | None = None, usuario_email: str | None = None
) -> tuple[RefVersion, bool]:
    artigos, itens, titulos = parse_lc214(coleta.dados)
    versao, criada = criar_versao(
        session,
        FonteReferencia.LC214,
        coleta,
        "html",
        "LC 214/2025 (texto compilado do Planalto)",
        usuario_id,
        usuario_email,
    )
    if not criada:
        return versao, False
    linhas: list[dict[str, Any]] = []
    for ordem, a in enumerate(artigos):
        linhas.append(
            {
                "id": uuid.uuid4(),
                "version_id": versao.id,
                "tipo": "artigo",
                "artigo": a.numero,
                "texto": a.texto,
                "codigos_citados": [],
                "ordem": ordem,
            }
        )
    base = len(linhas)
    for ordem, it in enumerate(itens):
        texto_item = it.descricao + (f"\nCódigos: {it.codigos_texto}" if it.codigos_texto else "")
        linhas.append(
            {
                "id": uuid.uuid4(),
                "version_id": versao.id,
                "tipo": "anexo_item",
                "anexo": it.anexo,
                "titulo_anexo": it.titulo,
                "item": it.item,
                "texto": texto_item,
                "codigos_citados": it.codigos,
                "ordem": base + ordem,
            }
        )
    for i in range(0, len(linhas), 1000):
        session.execute(insert(LegalProvision), linhas[i : i + 1000])
    por_anexo: dict[str, int] = {}
    for it in itens:
        por_anexo[it.anexo] = por_anexo.get(it.anexo, 0) + 1
    versao.embeddings_status = "pendente"  # busca por significado na base normativa
    ativar_versao(
        session,
        versao,
        {"artigos": len(artigos), "itens_anexos": len(itens), "por_anexo": por_anexo, "titulos": titulos},
        [],
    )
    return versao, True
