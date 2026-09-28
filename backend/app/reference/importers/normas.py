"""Importador genérico de atos normativos publicados no Planalto (EC 132/2023, LC 227/2026, decretos...).

Cada ato é uma versão da fonte "normas" com o rótulo do ato; vários atos ficam ativos ao mesmo
tempo. O texto revogado (riscado) é descartado e cada artigo vira um ou mais trechos
(artigos longos são divididos em partes para a busca por significado).
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

from bs4 import BeautifulSoup
from sqlalchemy import insert
from sqlalchemy.orm import Session

from app.models import LegalProvision, RefVersion
from app.models.enums import FonteReferencia
from app.reference.importers.common import Coleta, FormatoInvalido, ativar_versao, criar_versao
from app.reference.importers.lc214 import _ARTIGO, _ESPACOS

TAMANHO_TRECHO = 2000


@dataclass(frozen=True)
class AtoNormativo:
    chave: str
    rotulo: str
    url: str
    ementa: str
    vigencia_inicio: date | None = None


# Atos da Reforma Tributária do consumo que compõem a base normativa (além da LC 214/2025).
CATALOGO: tuple[AtoNormativo, ...] = (
    AtoNormativo(
        "ec132",
        "EC 132/2023",
        "https://www.planalto.gov.br/ccivil_03/constituicao/emendas/emc/emc132.htm",
        "Emenda Constitucional da Reforma Tributária (inclui as regras de transição do ADCT).",
        date(2023, 12, 20),
    ),
    AtoNormativo(
        "lc227",
        "LC 227/2026",
        "https://www.planalto.gov.br/ccivil_03/leis/lcp/lcp227.htm",
        "Institui o Comitê Gestor do IBS (CGIBS), o processo administrativo do IBS e altera a LC 214/2025.",
        date(2026, 1, 13),
    ),
    AtoNormativo(
        "decreto12955",
        "Decreto 12.955/2026",
        "https://www.planalto.gov.br/ccivil_03/_ato2023-2026/2026/decreto/D12955.htm",
        "Regulamenta a CBS.",
        date(2026, 4, 29),
    ),
)


def ato_por_chave(chave: str) -> AtoNormativo:
    for a in CATALOGO:
        if a.chave == chave:
            return a
    raise ValueError(f"Ato normativo desconhecido: {chave}. Opções: {', '.join(a.chave for a in CATALOGO)}.")


def _decodificar(dados: bytes) -> str:
    cabeca = dados[:3000].decode("ascii", "ignore").lower()
    m = re.search(r"charset=[\"']?([a-z0-9_-]+)", cabeca)
    tentativas = [m.group(1)] if m else []
    for enc in [*tentativas, "utf-8", "cp1252"]:
        try:
            return dados.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    raise FormatoInvalido("Não foi possível ler a página do ato normativo.")


def dividir(texto: str, limite: int = TAMANHO_TRECHO) -> list[str]:
    """Divide por parágrafos, sem quebrar um parágrafo ao meio (a menos que ele sozinho passe do limite)."""
    partes: list[str] = []
    atual = ""
    for par in texto.split("\n"):
        while len(par) > limite:
            if atual:
                partes.append(atual)
                atual = ""
            partes.append(par[:limite])
            par = par[limite:]
        if len(atual) + len(par) + 1 > limite and atual:
            partes.append(atual)
            atual = par
        else:
            atual = f"{atual}\n{par}" if atual else par
    if atual:
        partes.append(atual)
    return partes


def parse_artigos(html: bytes) -> list[tuple[str, str]]:
    soup = BeautifulSoup(_decodificar(html), "lxml")
    for riscado in soup.find_all(["strike", "s", "del"]):
        riscado.decompose()
    artigos: dict[str, str] = {}
    atual: str | None = None
    for p in soup.find_all("p"):
        t = _ESPACOS.sub(" ", p.get_text(" ", strip=True)).strip()
        if not t:
            continue
        m = _ARTIGO.match(t)
        if m:
            atual = m.group(1) + (f"-{m.group(2)}" if m.group(2) else "")
            artigos[atual] = t  # a versão compilada repete artigos alterados: vale a última redação
        elif atual is not None:
            artigos[atual] += "\n" + t
    if len(artigos) < 3:
        raise FormatoInvalido("Não foram encontrados artigos na página. O formato pode ter mudado.")
    return list(artigos.items())


def importar_norma(
    session: Session,
    coleta: Coleta,
    ato: AtoNormativo,
    usuario_id: uuid.UUID | None = None,
    usuario_email: str | None = None,
) -> tuple[RefVersion, bool]:
    artigos = parse_artigos(coleta.dados)
    versao, criada = criar_versao(
        session, FonteReferencia.NORMAS, coleta, "html", ato.rotulo, usuario_id, usuario_email
    )
    if not criada:
        return versao, False
    linhas: list[dict[str, Any]] = []
    for numero, texto in artigos:
        partes = dividir(texto)
        for n, parte in enumerate(partes, start=1):
            linhas.append(
                {
                    "id": uuid.uuid4(),
                    "version_id": versao.id,
                    "tipo": "artigo",
                    "artigo": numero if len(partes) == 1 else f"{numero} ({n}/{len(partes)})",
                    "texto": parte,
                    "codigos_citados": [],
                    "ordem": len(linhas),
                    "norma": ato.rotulo,
                    "vigencia_inicio": ato.vigencia_inicio,
                }
            )
    for i in range(0, len(linhas), 1000):
        session.execute(insert(LegalProvision), linhas[i : i + 1000])
    versao.embeddings_status = "pendente"
    ativar_versao(session, versao, {"artigos": len(artigos), "trechos": len(linhas), "ato": ato.chave}, [])
    return versao, True
