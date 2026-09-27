"""Estimativa de custo e tempo antes de iniciar uma auditoria."""

from __future__ import annotations

import math
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.llm.pricing import custo_chamada
from app.llm.prompts import carregar
from app.models import AuditItem, LlmCall

# Tamanhos médios por chamada (tokens). O bloco de sistema vai para o cache após a 1ª chamada.
USUARIO_PRINCIPAL = 1600
SAIDA_PRINCIPAL = 1400  # inclui raciocínio adaptativo
USUARIO_ESCALONAMENTO = 2100
SAIDA_ESCALONAMENTO = 2600
TAXA_ESCALONAMENTO_PADRAO = 0.35


def _tokens_sistema(nome: str) -> int:
    return math.ceil(len(carregar(nome).texto) / 3.2)


def taxa_escalonamento_historica(session: Session, org_id: Any) -> float:
    total = session.scalar(
        select(func.count())
        .select_from(LlmCall)
        .where(LlmCall.org_id == org_id, LlmCall.no == "julgar_coerencia", LlmCall.status == "concluida")
    )
    esc = session.scalar(
        select(func.count())
        .select_from(LlmCall)
        .where(LlmCall.org_id == org_id, LlmCall.no == "escalar", LlmCall.status == "concluida")
    )
    if not total or total < 50:
        return TAXA_ESCALONAMENTO_PADRAO
    return min(1.0, (esc or 0) / total)


def estimar(
    n_com_ia: int,
    modelo_principal: str,
    modelo_escalonamento: str,
    taxa_escalonamento: float,
    lote: bool,
) -> dict[str, Any]:
    sp, se = _tokens_sistema("julgar_coerencia"), _tokens_sistema("escalar")
    n_esc = math.ceil(n_com_ia * taxa_escalonamento)
    # 1ª chamada escreve o cache; as demais leem.
    custo_p = (
        custo_chamada(modelo_principal, USUARIO_PRINCIPAL, SAIDA_PRINCIPAL, sp, 0, lote) if n_com_ia else 0
    ) + custo_chamada(modelo_principal, USUARIO_PRINCIPAL, SAIDA_PRINCIPAL, 0, sp, lote) * max(0, n_com_ia - 1)
    custo_e = custo_chamada(modelo_escalonamento, USUARIO_ESCALONAMENTO, SAIDA_ESCALONAMENTO, 0, se, lote) * n_esc
    total = float(custo_p + custo_e)
    s = get_settings()
    if lote:
        tempo_min = (30, 24 * 60)
        texto_tempo = "Em lote: normalmente até 1 hora; no máximo 24 horas."
    else:
        seg = n_com_ia * 9 / 4 + n_esc * 14 / 4  # 4 processos em paralelo
        tempo_min = (max(1, math.ceil(seg / 60 * 0.7)), max(1, math.ceil(seg / 60 * 1.5)))
        texto_tempo = f"Cerca de {tempo_min[0]} a {tempo_min[1]} minutos."
    return {
        "itens_com_ia": n_com_ia,
        "escalonamentos_estimados": n_esc,
        "taxa_escalonamento": round(taxa_escalonamento, 3),
        "tokens_entrada_estimados": n_com_ia * (USUARIO_PRINCIPAL + sp) + n_esc * (USUARIO_ESCALONAMENTO + se),
        "tokens_saida_estimados": n_com_ia * SAIDA_PRINCIPAL + n_esc * SAIDA_ESCALONAMENTO,
        "custo_usd_estimado": round(total, 2),
        "custo_usd_faixa": [round(total * 0.6, 2), round(total * 1.6, 2)],
        "modo": "lote" if lote else "tempo_real",
        "limite_lote": s.llm_batch_min_itens,
        "tempo_minutos": list(tempo_min),
        "tempo_texto": texto_tempo,
        "modelos": {"principal": modelo_principal, "escalonamento": modelo_escalonamento},
        "observacao": "Estimativa aproximada. O custo real de cada chamada é registrado e exibido durante a auditoria.",
    }


def contar_itens(session: Session, audit_id: Any) -> dict[str, int]:
    rows = session.execute(
        select(AuditItem.ignorado, func.count()).where(AuditItem.audit_id == audit_id).group_by(AuditItem.ignorado)
    ).all()
    d = {bool(r[0]): int(r[1]) for r in rows}
    return {"validos": d.get(False, 0), "ignorados": d.get(True, 0)}
