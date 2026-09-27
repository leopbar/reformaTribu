"""Orçamento mensal de IA por organização: alerta e bloqueio."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit_trail import Acao, registrar_sync
from app.models import LlmCall, Notification, OrgSettings


class OrcamentoExcedido(Exception):
    def __init__(self, gasto: Decimal, limite: Decimal) -> None:
        super().__init__(f"Orçamento mensal de IA atingido (US$ {gasto:.2f} de US$ {limite:.2f}).")
        self.gasto = gasto
        self.limite = limite


def gasto_mes(session: Session, org_id: uuid.UUID) -> Decimal:
    inicio = date.today().replace(day=1)
    total = session.scalar(
        select(func.coalesce(func.sum(LlmCall.custo_usd), 0)).where(
            LlmCall.org_id == org_id, LlmCall.created_at >= inicio
        )
    )
    return Decimal(str(total or 0))


def verificar(session: Session, org_id: uuid.UUID, custo_previsto: Decimal = Decimal(0)) -> None:
    """Lança OrcamentoExcedido se o gasto do mês + custo previsto ultrapassar o limite."""
    excesso = checar(session, org_id, custo_previsto)
    if excesso is not None:
        raise excesso


def checar(session: Session, org_id: uuid.UUID, custo_previsto: Decimal = Decimal(0)) -> OrcamentoExcedido | None:
    """Devolve o excesso (sem lançar) e emite, uma vez por mês, o alerta de percentual atingido.

    Use quando o alerta precisa ser gravado mesmo que o orçamento esteja estourado.
    """
    cfg = session.get(OrgSettings, org_id)
    if cfg is None or cfg.orcamento_mensal_usd is None:
        return None
    limite = Decimal(cfg.orcamento_mensal_usd)
    gasto = gasto_mes(session, org_id)
    mes = date.today().strftime("%Y-%m")
    if limite > 0 and gasto >= limite * Decimal(cfg.alerta_orcamento_pct) / 100 and cfg.ultimo_alerta_orcamento != mes:
        cfg.ultimo_alerta_orcamento = mes
        session.add(
            Notification(
                org_id=org_id,
                tipo="orcamento",
                titulo="Orçamento de IA quase no limite",
                mensagem=f"O gasto com IA neste mês chegou a US$ {gasto:.2f} de US$ {limite:.2f} "
                f"({cfg.alerta_orcamento_pct}% do orçamento). Ao atingir o limite, novas análises serão pausadas.",
                link="/configuracoes",
            )
        )
        registrar_sync(
            session,
            Acao.ORCAMENTO,
            org_id=org_id,
            detalhes={"evento": "alerta", "gasto": float(gasto), "limite": float(limite)},
        )
    if gasto + custo_previsto > limite:
        return OrcamentoExcedido(gasto, limite)
    return None
