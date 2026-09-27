"""Importadores das nomenclaturas oficiais: NCM (JSON do Portal Único Siscomex) e NBS (CSV do MDIC)."""

from __future__ import annotations

import csv
import io
import re
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

import orjson
from sqlalchemy import insert
from sqlalchemy.orm import Session

from app.core.codes import formatar_nbs, formatar_ncm, nivel_nbs, nivel_ncm, somente_digitos
from app.models import NbsNode, NcmNode, RefVersion
from app.models.enums import FonteReferencia
from app.reference.importers.common import (
    Coleta,
    FormatoInvalido,
    ativar_versao,
    criar_versao,
    parse_data_br,
)

_TRACOS = re.compile(r"^[\s\-–—]+")
_TAGS = re.compile(r"<[^>]+>")  # a tabela oficial traz marcação HTML (ex.: nomes científicos em <i>)


@dataclass
class No:
    codigo: str
    descricao: str
    data_inicio: date | None = None
    data_fim: date | None = None
    ato: str | None = None


def limpar_descricao(texto: str) -> str:
    t = re.sub(r"\s+", " ", _TAGS.sub("", texto or "")).strip()
    t = _TRACOS.sub("", t).strip()
    return t.rstrip(":").strip()


def _pai(codigo: str, existentes: set[str], tamanhos: tuple[int, ...]) -> str | None:
    for n in sorted((t for t in tamanhos if t < len(codigo)), reverse=True):
        if codigo[:n] in existentes:
            return codigo[:n]
    return None


def montar_hierarquia(nos: list[No], tamanhos: tuple[int, ...], tamanho_folha: int) -> list[dict[str, Any]]:
    """Calcula pai, descrição completa (capítulo › … › item) e se é folha."""
    por_codigo = {n.codigo: n for n in nos}
    existentes = set(por_codigo)
    linhas: list[dict[str, Any]] = []
    cache: dict[str, str] = {}

    def completa(c: str) -> str:
        if c in cache:
            return cache[c]
        n = por_codigo[c]
        pai = _pai(c, existentes, tamanhos)
        texto = limpar_descricao(n.descricao)
        cache[c] = f"{completa(pai)} › {texto}" if pai else texto
        return cache[c]

    for n in nos:
        linhas.append(
            {
                "codigo": n.codigo,
                "codigo_pai": _pai(n.codigo, existentes, tamanhos),
                "descricao": limpar_descricao(n.descricao),
                "descricao_completa": completa(n.codigo),
                "folha": len(n.codigo) == tamanho_folha,
                "data_inicio": n.data_inicio,
                "data_fim": n.data_fim,
                "ato_legal": n.ato,
            }
        )
    return linhas


# ============================================================================== NCM ======
def parse_ncm_json(dados: bytes) -> tuple[list[No], dict[str, Any]]:
    try:
        doc = orjson.loads(dados)
    except orjson.JSONDecodeError as e:
        raise FormatoInvalido(
            "O arquivo não é um JSON válido. Baixe a tabela NCM em formato JSON no Portal Único Siscomex."
        ) from e
    if isinstance(doc, dict):
        lista = next((v for k, v in doc.items() if k.lower() == "nomenclaturas"), None)
        meta = {k: v for k, v in doc.items() if not isinstance(v, list)}
    else:
        lista, meta = doc, {}
    if not isinstance(lista, list) or not lista:
        raise FormatoInvalido("O JSON não contém a lista 'Nomenclaturas' esperada da tabela NCM.")
    nos: list[No] = []
    for reg in lista:
        r = {k.lower(): v for k, v in reg.items()}
        cod = somente_digitos(r.get("codigo"))
        desc = r.get("descricao") or ""
        if not cod or not desc:
            continue
        ato = " ".join(str(r.get(k) or "") for k in ("tipo_ato_ini", "numero_ato_ini", "ano_ato_ini")).strip()
        nos.append(
            No(cod, str(desc), parse_data_br(r.get("data_inicio")), parse_data_br(r.get("data_fim")), ato or None)
        )
    if len(nos) < 1000:
        raise FormatoInvalido(f"A tabela NCM parece incompleta ({len(nos)} códigos). Confira o arquivo.")
    return nos, meta


def importar_ncm(
    session: Session, coleta: Coleta, usuario_id: uuid.UUID | None = None, usuario_email: str | None = None
) -> tuple[RefVersion, bool]:
    nos, meta = parse_ncm_json(coleta.dados)
    rotulo = str(meta.get("Data_Ultima_Atualizacao_NCM") or meta.get("data_ultima_atualizacao_ncm") or "Tabela NCM")
    versao, criada = criar_versao(session, FonteReferencia.NCM, coleta, "json", rotulo, usuario_id, usuario_email)
    if not criada:
        return versao, False
    linhas = montar_hierarquia(nos, (2, 4, 5, 6, 7), 8)
    for linha in linhas:
        linha.update(
            version_id=versao.id, codigo_formatado=formatar_ncm(linha["codigo"]), nivel=nivel_ncm(linha["codigo"])
        )
    for i in range(0, len(linhas), 2000):
        session.execute(insert(NcmNode), linhas[i : i + 2000])
    folhas = sum(1 for linha in linhas if linha["folha"])
    avisos = []
    if folhas < 9000:
        avisos.append({"codigo": "POUCAS_FOLHAS", "mensagem": f"Apenas {folhas} códigos de 8 dígitos."})
    ativar_versao(session, versao, {"total": len(linhas), "folhas": folhas, "ato": meta.get("Ato")}, avisos)
    versao.embeddings_status = "pendente"
    return versao, True


# ============================================================================== NBS ======
def parse_nbs_csv(dados: bytes) -> list[No]:
    texto = None
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            texto = dados.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if texto is None:
        raise FormatoInvalido("Não foi possível ler o arquivo da NBS (codificação desconhecida).")
    amostra = texto[:2000]
    sep = ";" if amostra.count(";") >= amostra.count(",") else ","
    leitor = csv.reader(io.StringIO(texto), delimiter=sep)
    nos: list[No] = []
    for linha in leitor:
        if len(linha) < 2:
            continue
        cod = somente_digitos(linha[0])
        if not cod or not re.match(r"^\d[\d.]*$", linha[0].strip()):
            continue  # cabeçalho
        nos.append(No(cod, linha[1]))
    if len(nos) < 500:
        raise FormatoInvalido(f"A tabela NBS parece incompleta ({len(nos)} códigos). Confira o arquivo.")
    return nos


def importar_nbs(
    session: Session, coleta: Coleta, usuario_id: uuid.UUID | None = None, usuario_email: str | None = None
) -> tuple[RefVersion, bool]:
    nos = parse_nbs_csv(coleta.dados)
    versao, criada = criar_versao(session, FonteReferencia.NBS, coleta, "csv", "NBS 2.0", usuario_id, usuario_email)
    if not criada:
        return versao, False
    linhas = montar_hierarquia(nos, (1, 3, 5, 6, 7, 8), 9)
    for linha in linhas:
        linha.update(
            version_id=versao.id, codigo_formatado=formatar_nbs(linha["codigo"]), nivel=nivel_nbs(linha["codigo"])
        )
    for i in range(0, len(linhas), 2000):
        session.execute(insert(NbsNode), linhas[i : i + 2000])
    folhas = sum(1 for linha in linhas if linha["folha"])
    ativar_versao(session, versao, {"total": len(linhas), "folhas": folhas}, [])
    versao.embeddings_status = "pendente"
    return versao, True
