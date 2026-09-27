"""Infraestrutura comum dos importadores: coleta, idempotência e versionamento."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

import httpx
import structlog
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import RefVersion
from app.models.enums import StatusVersao
from app.storage import files

log = structlog.get_logger()


class FonteIndisponivel(Exception):
    """A fonte oficial não pôde ser baixada (fora do ar, bloqueada ou formato inesperado)."""


class FormatoInvalido(Exception):
    """O arquivo não tem o formato esperado para a fonte."""


@dataclass
class Coleta:
    dados: bytes
    url: str | None
    modo: str  # download | upload_manual
    nome_arquivo: str | None
    content_type: str | None = None


def baixar(url: str, tentativas: int = 3) -> Coleta:
    s = get_settings()
    ultimo: Exception | None = None
    for t in range(1, tentativas + 1):
        try:
            with httpx.Client(
                timeout=httpx.Timeout(120.0, connect=15.0),
                follow_redirects=True,
                headers={"User-Agent": s.http_user_agent},
            ) as c:
                r = c.get(url)
                r.raise_for_status()
                return Coleta(r.content, url, "download", url.rsplit("/", 1)[-1][:200], r.headers.get("content-type"))
        except httpx.HTTPError as e:
            ultimo = e
            time.sleep(2 * t)
    raise FonteIndisponivel(f"Não foi possível baixar {url}: {ultimo}")


def versao_existente(session: Session, fonte: str, sha: str) -> RefVersion | None:
    return session.scalar(
        select(RefVersion).where(
            RefVersion.fonte == fonte, RefVersion.sha256 == sha, RefVersion.status != StatusVersao.FALHOU
        )
    )


def criar_versao(
    session: Session,
    fonte: str,
    coleta: Coleta,
    extensao: str,
    rotulo: str,
    usuario_id: uuid.UUID | None,
    usuario_email: str | None,
) -> tuple[RefVersion, bool]:
    """Cria a versão (status importando). Devolve (versão, criada?). Idempotente por hash."""
    sha = files.sha256(coleta.dados)
    existente = versao_existente(session, fonte, sha)
    if existente is not None:
        return existente, False
    rel = files.salvar(f"referencia/{fonte}", coleta.dados, extensao)
    v = RefVersion(
        fonte=fonte,
        rotulo=rotulo,
        url_origem=coleta.url,
        modo_coleta=coleta.modo,
        coletado_em=datetime.now(UTC),
        sha256=sha,
        arquivo_path=rel,
        arquivo_nome=coleta.nome_arquivo,
        status=StatusVersao.IMPORTANDO,
        importado_por=usuario_id,
        importado_por_email=usuario_email,
    )
    session.add(v)
    session.flush()
    return v, True


def ativar_versao(
    session: Session,
    versao: RefVersion,
    estatisticas: dict[str, Any],
    avisos: list[Any],
    vigencia_inicio: date | None = None,
) -> None:
    session.execute(
        update(RefVersion)
        .where(RefVersion.fonte == versao.fonte, RefVersion.status == StatusVersao.ATIVA, RefVersion.id != versao.id)
        .values(status=StatusVersao.SUBSTITUIDA, vigencia_fim=date.today())
    )
    versao.status = StatusVersao.ATIVA
    versao.estatisticas = estatisticas
    versao.avisos = avisos
    versao.vigencia_inicio = vigencia_inicio or date.today()


def versao_ativa(session: Session, fonte: str) -> RefVersion | None:
    return session.scalar(
        select(RefVersion)
        .where(RefVersion.fonte == fonte, RefVersion.status == StatusVersao.ATIVA)
        .order_by(RefVersion.coletado_em.desc())
    )


def parse_data_br(texto: object) -> date | None:
    if not texto:
        return None
    t = str(texto).strip()[:10]
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            d = datetime.strptime(t, fmt).date()
            return None if d.year >= 9999 else d
        except ValueError:
            continue
    return None
