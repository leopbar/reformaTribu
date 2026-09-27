"""Orquestração do processamento: distribuição dos itens, conclusão, pausa por orçamento e recuperação."""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import and_, func, select, text, update

from app.core.audit_trail import Acao, registrar_sync
from app.db.session import TenantContext, sync_tenant_session
from app.events import bus
from app.llm.budget import OrcamentoExcedido
from app.llm.gateway import ChaveAPIAusente
from app.models import Audit, AuditItem, Notification
from app.models.enums import StatusAuditoria, StatusItem
from app.pipeline.context import carregar_contexto
from app.pipeline.reasons import Motivo
from app.pipeline.runner import AGUARDANDO_LOTE, processar_item
from app.worker.celery_app import celery_app

log = structlog.get_logger()
TAMANHO_BLOCO = 50
FINAIS = (StatusItem.CONFIRMADO, StatusItem.CORRIGIDO, StatusItem.ANALISE_HUMANA, StatusItem.ERRO)


def enfileirar_itens(audit_id: uuid.UUID, org_id: uuid.UUID, item_ids: list[uuid.UUID]) -> None:
    for i in range(0, len(item_ids), TAMANHO_BLOCO):
        bloco = [str(x) for x in item_ids[i : i + TAMANHO_BLOCO]]
        celery_app.send_task("auditoria.processar_itens", args=[str(audit_id), str(org_id), bloco], queue="pipeline")


def iniciar(audit_id: uuid.UUID, org_id: uuid.UUID) -> None:
    ctx = TenantContext.sistema(org_id)
    with sync_tenant_session(ctx) as sess:
        ids = list(
            sess.scalars(
                select(AuditItem.id)
                .where(
                    AuditItem.audit_id == audit_id,
                    AuditItem.ignorado.is_(False),
                    AuditItem.status.in_([StatusItem.PENDENTE, StatusItem.PROCESSANDO]),
                )
                .order_by(AuditItem.linha)
            )
        )
    bus.publicar(audit_id, "status", {"status": "processando", "total": len(ids)})
    if not ids:
        concluir_se_terminado(audit_id, org_id)
        return
    enfileirar_itens(audit_id, org_id, ids)


def processar_itens(audit_id: uuid.UUID, org_id: uuid.UUID, item_ids: list[uuid.UUID]) -> None:
    ctx_t = TenantContext.sistema(org_id)
    with sync_tenant_session(ctx_t) as sess:
        audit = sess.get(Audit, audit_id)
        if audit is None or audit.status not in (StatusAuditoria.PROCESSANDO, StatusAuditoria.AGUARDANDO_LOTE):
            return
        tentativas = dict(
            sess.execute(
                select(AuditItem.id, AuditItem.tentativa).where(
                    AuditItem.id.in_(item_ids), AuditItem.status.notin_(list(FINAIS))
                )
            ).all()
        )
    ctx = carregar_contexto(audit_id, org_id)
    aguardando: list[uuid.UUID] = []
    for item_id in item_ids:
        if item_id not in tentativas:
            continue
        try:
            resultado = processar_item(item_id, tentativas[item_id], ctx)
            if resultado == AGUARDANDO_LOTE:
                aguardando.append(item_id)
        except OrcamentoExcedido as e:
            pausar_por_orcamento(audit_id, org_id, str(e))
            return
        except ChaveAPIAusente as e:
            falhar_auditoria(audit_id, org_id, str(e))
            return
        except Exception as e:
            log.exception("item_falhou", item=str(item_id))
            with sync_tenant_session(ctx_t) as sess:
                item = sess.get(AuditItem, item_id)
                if item is not None:
                    item.status = StatusItem.ERRO
                    item.motivos = list(dict.fromkeys([*(item.motivos or []), Motivo.FALHA_NA_ANALISE_IA]))
                    item.erro = f"{type(e).__name__}: {str(e)[:500]}"
                    item.etapa = "erro"
            bus.publicar(audit_id, "item", {"item_id": str(item_id), "status": "erro"})
    if aguardando:
        with sync_tenant_session(ctx_t) as sess:
            sess.execute(update(AuditItem).where(AuditItem.id.in_(aguardando)).values(etapa="aguardando_lote"))
            sess.execute(
                update(Audit)
                .where(Audit.id == audit_id, Audit.status == StatusAuditoria.PROCESSANDO)
                .values(status=StatusAuditoria.AGUARDANDO_LOTE)
            )
    atualizar_contadores(audit_id, org_id)
    concluir_se_terminado(audit_id, org_id)


def atualizar_contadores(audit_id: uuid.UUID, org_id: uuid.UUID) -> dict[str, Any]:
    with sync_tenant_session(TenantContext.sistema(org_id)) as sess:
        rows = sess.execute(
            select(AuditItem.status, AuditItem.etapa, func.count())
            .where(AuditItem.audit_id == audit_id, AuditItem.ignorado.is_(False))
            .group_by(AuditItem.status, AuditItem.etapa)
        ).all()
        por_status: Counter[str] = Counter()
        por_etapa: Counter[str] = Counter()
        for st, etapa, n in rows:
            por_status[st] += n
            if st in (StatusItem.PENDENTE, StatusItem.PROCESSANDO):
                por_etapa[etapa or "na_fila"] += n
        motivos = sess.execute(
            text(
                "SELECT m, count(*) FROM audit_items, unnest(motivos) m WHERE audit_id = :a AND NOT ignorado "
                "GROUP BY m ORDER BY 2 DESC"
            ),
            {"a": audit_id},
        ).all()
        custo = sess.execute(
            text(
                "SELECT coalesce(sum(custo_usd),0), coalesce(sum(tokens_entrada),0), coalesce(sum(tokens_saida),0), "
                "coalesce(sum(tokens_cache_leitura),0), coalesce(sum(tokens_cache_escrita),0), count(*) "
                "FROM llm_calls WHERE audit_id = :a"
            ),
            {"a": audit_id},
        ).one()
        contadores = {
            "por_status": dict(por_status),
            "por_etapa": dict(por_etapa),
            "motivos": {m: int(n) for m, n in motivos},
            "concluidos": sum(por_status[s] for s in FINAIS),
            "total": sum(por_status.values()),
        }
        audit = sess.get(Audit, audit_id)
        if audit is not None:
            audit.contadores = contadores
            audit.custo_usd = custo[0]
            audit.tokens = {
                "entrada": int(custo[1]),
                "saida": int(custo[2]),
                "cache_leitura": int(custo[3]),
                "cache_escrita": int(custo[4]),
                "chamadas": int(custo[5]),
            }
    bus.publicar(audit_id, "progresso", {"contadores": contadores, "custo_usd": float(custo[0])})
    return contadores


def concluir_se_terminado(audit_id: uuid.UUID, org_id: uuid.UUID) -> bool:
    with sync_tenant_session(TenantContext.sistema(org_id)) as sess:
        audit = sess.get(Audit, audit_id)
        if audit is None or audit.status in (
            StatusAuditoria.CONCLUIDA,
            StatusAuditoria.CANCELADA,
            StatusAuditoria.FALHOU,
            StatusAuditoria.PAUSADA_ORCAMENTO,
        ):
            return False
        restantes = sess.scalar(
            select(func.count())
            .select_from(AuditItem)
            .where(AuditItem.audit_id == audit_id, AuditItem.ignorado.is_(False), AuditItem.status.notin_(list(FINAIS)))
        )
        if restantes:
            return False
        audit.status = StatusAuditoria.CONCLUIDA
        audit.concluido_em = datetime.now(UTC)
        c = (audit.contadores or {}).get("por_status", {})
        sess.add(
            Notification(
                org_id=org_id,
                user_id=audit.created_by,
                tipo="auditoria_concluida",
                titulo="Auditoria concluída",
                mensagem=f"“{audit.nome}” terminou: {c.get('confirmado', 0)} confirmados, {c.get('corrigido', 0)} "
                f"corrigidos e {c.get('analise_humana', 0)} para análise humana.",
                link=f"/auditorias/{audit_id}",
            )
        )
    atualizar_contadores(audit_id, org_id)
    bus.publicar(audit_id, "status", {"status": "concluida"})
    return True


def pausar_por_orcamento(audit_id: uuid.UUID, org_id: uuid.UUID, mensagem: str) -> None:
    with sync_tenant_session(TenantContext.sistema(org_id)) as sess:
        audit = sess.get(Audit, audit_id)
        if audit is None or audit.status == StatusAuditoria.PAUSADA_ORCAMENTO:
            return
        audit.status = StatusAuditoria.PAUSADA_ORCAMENTO
        audit.erro = mensagem
        sess.add(
            Notification(
                org_id=org_id,
                tipo="orcamento",
                titulo="Auditoria pausada: orçamento de IA atingido",
                mensagem=f"{mensagem} Aumente o orçamento em Configurações e retome a auditoria “{audit.nome}”.",
                link=f"/auditorias/{audit_id}",
            )
        )
        registrar_sync(
            sess,
            Acao.ORCAMENTO,
            org_id=org_id,
            entidade="auditoria",
            entidade_id=audit_id,
            detalhes={"evento": "bloqueio", "mensagem": mensagem},
        )
    bus.publicar(audit_id, "status", {"status": "pausada_orcamento", "mensagem": mensagem})


def falhar_auditoria(audit_id: uuid.UUID, org_id: uuid.UUID, mensagem: str) -> None:
    with sync_tenant_session(TenantContext.sistema(org_id)) as sess:
        audit = sess.get(Audit, audit_id)
        if audit is not None:
            audit.status = StatusAuditoria.FALHOU
            audit.erro = mensagem
    bus.publicar(audit_id, "status", {"status": "falhou", "mensagem": mensagem})


def recuperar_travados(org_id: uuid.UUID, minutos: int = 15) -> int:
    """Reenfileira itens parados (ex.: worker reiniciado). O grafo retoma do checkpoint."""
    limite = datetime.now(UTC) - timedelta(minutes=minutos)
    total = 0
    with sync_tenant_session(TenantContext.sistema(org_id)) as sess:
        audits = list(sess.scalars(select(Audit.id).where(Audit.status == StatusAuditoria.PROCESSANDO)))
        pendentes: dict[uuid.UUID, list[uuid.UUID]] = {}
        for a in audits:
            ids = list(
                sess.scalars(
                    select(AuditItem.id).where(
                        AuditItem.audit_id == a,
                        AuditItem.ignorado.is_(False),
                        AuditItem.status.in_([StatusItem.PENDENTE, StatusItem.PROCESSANDO]),
                        and_(AuditItem.updated_at < limite, func.coalesce(AuditItem.etapa, "") != "aguardando_lote"),
                    )
                )
            )
            if ids:
                pendentes[a] = ids
    for a, ids in pendentes.items():
        log.info("recuperando_itens", auditoria=str(a), itens=len(ids))
        enfileirar_itens(a, org_id, ids)
        total += len(ids)
    return total
