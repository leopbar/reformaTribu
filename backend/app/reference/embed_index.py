"""Geração dos embeddings das descrições oficiais (códigos folha) e dos trechos normativos."""

from __future__ import annotations

import uuid
from collections.abc import Callable

import structlog
from pgvector.sqlalchemy import Vector
from sqlalchemy import bindparam, select, text

from app.config import get_settings
from app.db.session import TenantContext, sync_reference_admin_session
from app.embeddings import client
from app.models import RefVersion

log = structlog.get_logger()

FONTES_NOMENCLATURA = ("ncm", "nbs")
FONTES_NORMATIVAS = ("lc214", "normas")

# Texto indexado de cada trecho normativo: ato, localização e conteúdo (limitado ao que o modelo lê).
_SQL_TEXTO_NORMA = """
SELECT id, norma || ' ' || coalesce('Anexo ' || anexo || ' item ' || item, 'Art. ' || artigo, '') || ': '
       || coalesce(titulo_anexo || ' — ', '') || left(texto, 1800) AS conteudo
  FROM legal_provisions WHERE version_id = :v AND embedding IS NULL ORDER BY ordem, id LIMIT :l
"""


def indexar_versao(version_id: uuid.UUID, lote: int = 256) -> int:
    from app.core.redis import redis_sync

    # Uma indexação por versão de cada vez (a tarefa agendada pode disparar de novo).
    # A trava expira em 10 min e é renovada a cada lote: se o processo morrer, outra execução assume logo.
    trava = redis_sync().lock(f"trava:embeddings:{version_id}", timeout=600, blocking=False)
    if not trava.acquire(blocking=False):
        log.info("embeddings_ja_em_andamento", versao=str(version_id))
        return 0
    try:
        return _indexar(version_id, lote, renovar=lambda: trava.extend(600, replace_ttl=True))
    finally:
        try:
            trava.release()
        except Exception:  # noqa: S110
            pass


def _indexar(version_id: uuid.UUID, lote: int, renovar: Callable[[], object] = lambda: None) -> int:
    s = get_settings()
    ctx = TenantContext(org_id=None, platform_admin=True)
    with sync_reference_admin_session(ctx) as sess:
        v = sess.get(RefVersion, version_id)
        if v is None or v.fonte not in (*FONTES_NOMENCLATURA, *FONTES_NORMATIVAS):
            return 0
        fonte = v.fonte
        v.embeddings_status = "processando"
        v.embeddings_modelo = s.embeddings_modelo
    if fonte in FONTES_NORMATIVAS:
        tabela = "legal_provisions"
        consulta = _SQL_TEXTO_NORMA
    else:
        tabela = "nbs_nodes" if fonte == "nbs" else "ncm_nodes"
        consulta = (
            f"SELECT id, descricao_completa AS conteudo FROM {tabela} WHERE version_id = :v AND folha "
            "AND embedding IS NULL ORDER BY id LIMIT :l"
        )
    total = 0
    atualizar = text(f"UPDATE {tabela} SET embedding = :e WHERE id = :i").bindparams(
        bindparam("e", type_=Vector(s.embeddings_dim))
    )
    while True:
        with sync_reference_admin_session(ctx) as sess:
            rows = sess.execute(text(consulta), {"v": version_id, "l": lote}).all()
            if not rows:
                break
            vetores = client.embed([r.conteudo for r in rows], tipo="documento")
            sess.execute(atualizar, [{"e": vec, "i": r.id} for r, vec in zip(rows, vetores, strict=True)])
            total += len(rows)
            log.info("embeddings_lote", versao=str(version_id), total=total)
        renovar()
    with sync_reference_admin_session(ctx) as sess:
        v = sess.get(RefVersion, version_id)
        assert v is not None
        v.embeddings_status = "concluido"
        v.estatisticas = {**(v.estatisticas or {}), "embeddings": total}
    return total


def versoes_pendentes() -> list[uuid.UUID]:
    with sync_reference_admin_session(TenantContext(org_id=None, platform_admin=True)) as sess:
        return list(
            sess.scalars(
                select(RefVersion.id).where(
                    RefVersion.embeddings_status.in_(["pendente", "processando"]), RefVersion.status == "ativa"
                )
            )
        )
