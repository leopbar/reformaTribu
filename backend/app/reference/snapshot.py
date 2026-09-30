"""Snapshots imutáveis da base de referência (versões ativas + regras aprovadas)."""

from __future__ import annotations

import hashlib
from typing import Any

import orjson
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LegalRule, RefSnapshot, RefVersion
from app.models.enums import FonteReferencia, StatusRegra, StatusVersao


async def criar_ou_obter(session: AsyncSession) -> RefSnapshot:
    versoes: dict[str, Any] = {}
    embeddings: dict[str, bool] = {}
    # Atos normativos complementares: vários ativos ao mesmo tempo (lista de versões).
    normas = sorted(
        str(i)
        for i in await session.scalars(
            select(RefVersion.id).where(RefVersion.fonte == "normas", RefVersion.status == StatusVersao.ATIVA)
        )
    )
    embeddings["embeddings_normas"] = bool(normas) and not await session.scalar(
        select(RefVersion.id)
        .where(
            RefVersion.fonte.in_(["lc214", "normas"]),
            RefVersion.status == StatusVersao.ATIVA,
            RefVersion.embeddings_status != "concluido",
        )
        .limit(1)
    )
    for f in FonteReferencia:
        if f == FonteReferencia.NORMAS:
            continue
        v = await session.scalar(
            select(RefVersion)
            .where(RefVersion.fonte == f.value, RefVersion.status == StatusVersao.ATIVA)
            .order_by(RefVersion.coletado_em.desc())
            .limit(1)
        )
        versoes[f.value] = str(v.id) if v else None
        if f.value in ("ncm", "nbs"):
            embeddings[f"embeddings_{f.value}"] = bool(v and v.embeddings_status == "concluido")
    aprovadas = sorted(
        str(i) for i in await session.scalars(select(LegalRule.id).where(LegalRule.status == StatusRegra.APROVADA))
    )
    pendentes = sorted(
        str(i)
        for i in await session.scalars(
            select(LegalRule.id).where(LegalRule.status.in_([StatusRegra.PENDENTE_REVISAO, StatusRegra.INVALIDA]))
        )
    )
    completude = {
        "normas": len(normas),
        "ncm": versoes.get("ncm") is not None,
        "nbs": versoes.get("nbs") is not None,
        "cclasstrib": versoes.get("cclasstrib") is not None,
        "lc214": versoes.get("lc214") is not None,
        "regras_aprovadas": len(aprovadas),
        "regras_pendentes": len(pendentes),
        **embeddings,
    }
    h = hashlib.sha256(
        orjson.dumps(
            {"v": versoes, "n": normas, "a": aprovadas, "p": pendentes, "e": embeddings}, option=orjson.OPT_SORT_KEYS
        )
    ).hexdigest()
    existente = await session.scalar(select(RefSnapshot).where(RefSnapshot.hash == h))
    if existente is not None:
        return existente
    # Os atos complementares ficam fora de `versoes` (que tem uma versão por fonte).
    snap = RefSnapshot(
        hash=h,
        versoes=versoes,
        regras_aprovadas=aprovadas,
        regras_pendentes=pendentes,
        completude={**completude, "normas_versoes": normas},
    )
    session.add(snap)
    await session.flush()
    return snap
