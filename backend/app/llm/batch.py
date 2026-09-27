"""Integração com a Message Batches API.

Fluxo: os nós de IA enfileiram requisições (llm_calls com status "na_fila") e interrompem o
grafo. Esta tarefa coletora agrupa as requisições por auditoria e modelo, envia o lote, consulta o
andamento e, quando o lote termina, grava cada resposta ANTES de retomar os grafos a partir do
checkpoint. Assim, nenhuma requisição é cobrada duas vezes.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import anthropic
import structlog
from sqlalchemy import func, select, update

from app.db.session import TenantContext, sync_tenant_session
from app.llm import budget
from app.llm.gateway import cliente, registrar_resposta
from app.llm.pricing import custo_chamada
from app.models import Audit, AuditItem, LlmBatch, LlmCall
from app.models.enums import StatusAuditoria, StatusChamadaLLM, StatusItem, StatusLote

log = structlog.get_logger()
MAX_POR_LOTE = 10_000
ESPERA_ENVIO = timedelta(seconds=45)
RETENTATIVAS_LOTE = 2


def _custo_previsto(calls: list[LlmCall]) -> Decimal:
    total = Decimal(0)
    for c in calls:
        entrada = len(str(c.requisicao.get("params", ""))) // 3
        total += custo_chamada(c.modelo, entrada, 1500, 0, 0, lote=True)
    return total


def enviar_lotes(org_id: uuid.UUID) -> int:
    ctx = TenantContext.sistema(org_id)
    enviados = 0
    agora = datetime.now(UTC)
    with sync_tenant_session(ctx) as sess:
        fila = list(
            sess.scalars(
                select(LlmCall)
                .where(LlmCall.status == StatusChamadaLLM.NA_FILA, LlmCall.modo == "lote")
                .order_by(LlmCall.created_at)
            )
        )
        grupos: dict[tuple[uuid.UUID | None, str], list[LlmCall]] = defaultdict(list)
        for c in fila:
            grupos[(c.audit_id, c.modelo)].append(c)
        # Envia quando não há mais itens da auditoria sendo preparados, ou após um tempo de espera.
        prontos: list[tuple[uuid.UUID | None, str, list[LlmCall]]] = []
        for (audit_id, modelo), calls in grupos.items():
            ativos = sess.scalar(
                select(func.count())
                .select_from(AuditItem)
                .where(
                    AuditItem.audit_id == audit_id,
                    AuditItem.ignorado.is_(False),
                    AuditItem.status.in_([StatusItem.PENDENTE, StatusItem.PROCESSANDO]),
                    func.coalesce(AuditItem.etapa, "") != "aguardando_lote",
                )
            )
            if ativos == 0 or agora - calls[0].created_at > ESPERA_ENVIO:
                prontos.append((audit_id, modelo, calls))
        if not prontos:
            return 0
        excesso = budget.checar(sess, org_id, sum((_custo_previsto(c) for _, _, c in prontos), Decimal(0)))
    if excesso is not None:
        from app.audits.processing import pausar_por_orcamento

        for audit_id, _, _ in prontos:
            if audit_id:
                pausar_por_orcamento(audit_id, org_id, str(excesso))
        return 0

    api = cliente()
    for audit_id, modelo, calls in prontos:
        for i in range(0, len(calls), MAX_POR_LOTE):
            parte = calls[i : i + MAX_POR_LOTE]
            with sync_tenant_session(ctx) as sess:
                lote = LlmBatch(
                    org_id=org_id,
                    audit_id=audit_id,
                    modelo=modelo,
                    status=StatusLote.ENVIADO,
                    total_requisicoes=len(parte),
                )
                sess.add(lote)
                sess.flush()
                lote_id = lote.id
                reqs = [{"custom_id": str(c.id), "params": c.requisicao["params"]} for c in parte]
            try:
                resp = api.messages.batches.create(requests=reqs)  # type: ignore[arg-type]
            except anthropic.APIError as e:
                log.error("envio_lote_falhou", erro=str(e))
                with sync_tenant_session(ctx) as sess:
                    lb = sess.get(LlmBatch, lote_id)
                    assert lb is not None
                    lb.status, lb.erro = StatusLote.FALHOU, str(e)[:1000]
                continue
            with sync_tenant_session(ctx) as sess:
                lb = sess.get(LlmBatch, lote_id)
                assert lb is not None
                lb.anthropic_batch_id = resp.id
                sess.execute(
                    update(LlmCall)
                    .where(LlmCall.id.in_([c.id for c in parte]))
                    .values(status=StatusChamadaLLM.ENVIADA, batch_id=lote_id)
                )
                if audit_id:
                    sess.execute(
                        update(Audit)
                        .where(Audit.id == audit_id, Audit.status == StatusAuditoria.PROCESSANDO)
                        .values(status=StatusAuditoria.AGUARDANDO_LOTE)
                    )
            enviados += len(parte)
            log.info("lote_enviado", lote=resp.id, requisicoes=len(parte), modelo=modelo)
    return enviados


def verificar_lotes(org_id: uuid.UUID) -> dict[uuid.UUID, list[uuid.UUID]]:
    """Consulta lotes enviados; grava respostas dos que terminaram. Devolve {audit_id: [item_ids]} a retomar."""
    ctx = TenantContext.sistema(org_id)
    retomar: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    with sync_tenant_session(ctx) as sess:
        lotes = [
            (b.id, str(b.anthropic_batch_id), b.audit_id)
            for b in sess.scalars(
                select(LlmBatch).where(LlmBatch.status == StatusLote.ENVIADO, LlmBatch.anthropic_batch_id.is_not(None))
            )
        ]
    if not lotes:
        return {}
    api = cliente()
    for lote_id, anth_id, audit_id in lotes:
        try:
            info = api.messages.batches.retrieve(anth_id)
        except anthropic.APIError as e:
            log.warning("consulta_lote_falhou", lote=anth_id, erro=str(e))
            continue
        if info.processing_status != "ended":
            continue
        resultados: dict[str, Any] = {}
        for r in api.messages.batches.results(anth_id):
            resultados[r.custom_id] = r.result
        with sync_tenant_session(ctx) as sess:
            lb = sess.get(LlmBatch, lote_id)
            assert lb is not None
            contagem: dict[str, int] = defaultdict(int)
            for call in sess.scalars(select(LlmCall).where(LlmCall.batch_id == lote_id)):
                res = resultados.get(str(call.id))
                tipo = getattr(res, "type", "ausente")
                contagem[tipo] += 1
                call.tentativas += 1
                if tipo == "succeeded" and res is not None:
                    registrar_resposta(call, res.message.to_dict(), lote=True)
                    call.status = StatusChamadaLLM.CONCLUIDA
                elif tipo in ("expired", "canceled", "ausente") or (
                    tipo == "errored" and getattr(getattr(res, "error", None), "type", "") != "invalid_request"
                ):
                    if call.tentativas < RETENTATIVAS_LOTE:
                        call.status, call.batch_id = StatusChamadaLLM.NA_FILA, None
                        continue
                    call.status, call.erro = StatusChamadaLLM.FALHOU, f"Lote: {tipo}"
                else:
                    call.status, call.erro = StatusChamadaLLM.FALHOU, f"Lote: requisição inválida ({tipo})"
                if call.item_id:
                    retomar[audit_id].append(call.item_id)
            lb.status = StatusLote.CONCLUIDO
            lb.contagens = dict(contagem)
            lb.concluido_em = datetime.now(UTC)
            sess.execute(
                update(Audit)
                .where(Audit.id == audit_id, Audit.status == StatusAuditoria.AGUARDANDO_LOTE)
                .values(status=StatusAuditoria.PROCESSANDO)
            )
        log.info("lote_concluido", lote=anth_id, contagens=dict(contagem))
    return {a: list(dict.fromkeys(ids)) for a, ids in retomar.items()}
