"""Tarefas Celery. Cada tarefa é fina: delega para os serviços do domínio."""

from __future__ import annotations

import io
import uuid
import zipfile
from datetime import UTC, date, datetime
from typing import Any

import orjson
import structlog
from sqlalchemy import select, text

from app.audits import preparation, processing
from app.core.audit_trail import Acao, registrar_sync
from app.db.session import TenantContext, sync_tenant_session
from app.llm import batch
from app.models import ExportJob, Notification, UploadedFile
from app.models.enums import StatusExportacao
from app.reference import embed_index, service
from app.rules import extraction
from app.storage import files
from app.worker.celery_app import celery_app

log = structlog.get_logger()


def _orgs(funcao: str) -> list[uuid.UUID]:
    with sync_tenant_session(None) as s:
        return [r[0] for r in s.execute(text(f"SELECT org_id FROM {funcao}()"))]


# ------------------------------------------------------------------------------ auditoria --
@celery_app.task(name="auditoria.preparar", bind=True, max_retries=2)
def preparar(self: Any, audit_id: str, org_id: str) -> None:
    preparation.preparar_auditoria(uuid.UUID(audit_id), uuid.UUID(org_id))


@celery_app.task(name="auditoria.iniciar")
def iniciar(audit_id: str, org_id: str) -> None:
    processing.iniciar(uuid.UUID(audit_id), uuid.UUID(org_id))


@celery_app.task(name="auditoria.processar_itens", bind=True, max_retries=5, default_retry_delay=30)
def processar_itens(self: Any, audit_id: str, org_id: str, item_ids: list[str]) -> None:
    from app.embeddings.client import EmbeddingsIndisponivel

    try:
        processing.processar_itens(uuid.UUID(audit_id), uuid.UUID(org_id), [uuid.UUID(i) for i in item_ids])
    except EmbeddingsIndisponivel as e:
        raise self.retry(exc=e) from e


@celery_app.task(name="analise.reavaliar_itens")
def reavaliar_itens(org_id: str, item_ids: list[str], motivo: str) -> int:
    """Reavalia itens depois de um fato novo (resposta, dossiê, tese validada). Não chama a IA."""
    from app.analise import aplicacao

    n = 0
    auditorias: set[uuid.UUID] = set()
    for i in range(0, len(item_ids), 200):
        with sync_tenant_session(TenantContext.sistema(uuid.UUID(org_id))) as s:
            for iid in item_ids[i : i + 200]:
                if aplicacao.reavaliar(s, uuid.UUID(iid), motivo):
                    n += 1
            from app.models import AuditItem

            auditorias |= set(
                s.scalars(
                    select(AuditItem.audit_id).where(AuditItem.id.in_([uuid.UUID(x) for x in item_ids[i : i + 200]]))
                )
            )
    for a in auditorias:
        processing.atualizar_contadores(a, uuid.UUID(org_id))
    return n


@celery_app.task(name="analise.atualizar_contadores")
def atualizar_contadores(audit_id: str, org_id: str) -> None:
    processing.atualizar_contadores(uuid.UUID(audit_id), uuid.UUID(org_id))


@celery_app.task(name="auditoria.recuperar_travados")
def recuperar_travados() -> int:
    return sum(processing.recuperar_travados(o) for o in _orgs("sys_orgs_com_trabalho"))


# ------------------------------------------------------------------------------ Batch API --
@celery_app.task(name="llm.coletar_lotes")
def coletar_lotes() -> dict[str, int]:
    enviados = retomados = 0
    for org in _orgs("sys_orgs_com_trabalho"):
        try:
            enviados += batch.enviar_lotes(org)
            for audit_id, itens in batch.verificar_lotes(org).items():
                processing.enfileirar_itens(audit_id, org, itens)
                retomados += len(itens)
        except Exception:
            log.exception("coleta_lotes_falhou", org=str(org))
    return {"enviados": enviados, "retomados": retomados}


# --------------------------------------------------------------------- base de referência --
@celery_app.task(name="referencia.importar", bind=True)
def importar_referencia(
    self: Any,
    fonte: str,
    url: str | None = None,
    arquivo_rel: str | None = None,
    nome_arquivo: str | None = None,
    usuario_id: str | None = None,
    usuario_email: str | None = None,
) -> dict[str, Any]:
    r = service.importar(
        fonte,
        url=url,
        arquivo_rel=arquivo_rel,
        nome_arquivo=nome_arquivo,
        usuario_id=uuid.UUID(usuario_id) if usuario_id else None,
        usuario_email=usuario_email,
    )
    if r.get("criada") and fonte in ("ncm", "nbs", "lc214", "normas"):
        indexar_embeddings.delay(r["versao_id"])
    return r


@celery_app.task(name="referencia.importar_ato")
def importar_ato(chave: str, usuario_id: str | None = None, usuario_email: str | None = None) -> dict[str, Any]:
    r = service.importar_ato(
        chave, usuario_id=uuid.UUID(usuario_id) if usuario_id else None, usuario_email=usuario_email
    )
    if r.get("criada"):
        indexar_embeddings.delay(r["versao_id"])
    return r


@celery_app.task(name="referencia.indexar_embeddings", bind=True, max_retries=10, default_retry_delay=120)
def indexar_embeddings(self: Any, version_id: str) -> int:
    from app.embeddings.client import EmbeddingsIndisponivel

    try:
        return embed_index.indexar_versao(uuid.UUID(version_id))
    except EmbeddingsIndisponivel as e:
        raise self.retry(exc=e) from e


@celery_app.task(name="referencia.indexar_pendentes")
def indexar_pendentes() -> int:
    n = 0
    for v in embed_index.versoes_pendentes():
        indexar_embeddings.delay(str(v))
        n += 1
    return n


@celery_app.task(name="referencia.sugerir_condicoes")
def sugerir_condicoes(regra_ids: list[str], solicitante: str | None = None) -> dict[str, int]:
    from app.db.session import sync_reference_admin_session

    ok = falhas = 0
    for rid in regra_ids:
        try:
            with sync_reference_admin_session(TenantContext(org_id=None, platform_admin=True)) as s:
                extraction.sugerir_condicoes(s, uuid.UUID(rid), solicitante)
            ok += 1
        except Exception:
            log.exception("sugestao_condicoes_falhou", regra=rid)
            falhas += 1
    return {"ok": ok, "falhas": falhas}


@celery_app.task(name="referencia.verificar_atualizacoes")
def verificar_atualizacoes() -> dict[str, Any]:
    """Baixa as fontes oficiais; se o conteúdo mudou, cria nova versão (regras novas ficam pendentes)."""
    resultado: dict[str, Any] = {}
    for fonte in ("cclasstrib", "lc214", "ncm", "nbs"):
        try:
            r = service.importar(fonte)
            resultado[fonte] = "nova_versao" if r["criada"] else "sem_alteracao"
            if r["criada"] and fonte in ("ncm", "nbs", "lc214", "normas"):
                indexar_embeddings.delay(r["versao_id"])
        except Exception as e:
            resultado[fonte] = f"indisponivel: {str(e)[:200]}"
    log.info("verificacao_fontes", **resultado)
    return resultado


# ---------------------------------------------------------------------------- exportação --
@celery_app.task(name="exportacao.gerar")
def gerar_exportacao(job_id: str, org_id: str) -> None:
    from app.export.service import executar_job

    ctx = TenantContext.sistema(uuid.UUID(org_id))
    with sync_tenant_session(ctx) as s:
        job = s.get(ExportJob, uuid.UUID(job_id))
        if job is None:
            return
        job.status = StatusExportacao.GERANDO
    try:
        with sync_tenant_session(ctx) as s:
            job = s.get(ExportJob, uuid.UUID(job_id))
            assert job is not None
            dados, nome = executar_job(s, job)
            job.arquivo_path = files.salvar(f"exportacoes/{org_id}", dados, nome.rsplit(".", 1)[-1])
            job.arquivo_nome = nome
            job.status = StatusExportacao.CONCLUIDA
            job.concluido_em = datetime.now(UTC)
            s.add(
                Notification(
                    org_id=job.org_id,
                    user_id=job.created_by,
                    tipo="exportacao",
                    titulo="Exportação pronta",
                    mensagem=f"O arquivo {nome} está pronto para baixar.",
                    link=f"/auditorias/{job.audit_id}/exportar",
                )
            )
    except Exception as e:
        log.exception("exportacao_falhou", job=job_id)
        with sync_tenant_session(ctx) as s:
            job = s.get(ExportJob, uuid.UUID(job_id))
            if job:
                job.status, job.erro = StatusExportacao.FALHOU, "Não foi possível gerar o arquivo: " + str(e)[:300]


@celery_app.task(name="exportacao.dados_organizacao")
def exportar_dados_organizacao(org_id: str, user_id: str, job_id: str) -> None:
    """LGPD: pacote com todos os dados da organização (JSON por tabela, compactado)."""
    ctx = TenantContext.sistema(uuid.UUID(org_id))
    tabelas = [
        "companies",
        "memberships",
        "audits",
        "audit_items",
        "item_reviews",
        "approved_memory",
        "llm_calls",
        "export_jobs",
        "mapping_templates",
        "abbreviations",
        "audit_log",
    ]
    buf = io.BytesIO()
    with sync_tenant_session(ctx) as s, zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for t in tabelas:
            linhas = [
                dict(r._mapping)
                for r in s.execute(text(f"SELECT * FROM {t} WHERE org_id = :o"), {"o": uuid.UUID(org_id)})
            ]
            z.writestr(f"{t}.json", orjson.dumps(linhas, default=str, option=orjson.OPT_INDENT_2))
        job = s.get(ExportJob, uuid.UUID(job_id))
        if job is not None:
            job.arquivo_path = files.salvar(f"exportacoes/{org_id}", buf.getvalue(), "zip")
            job.arquivo_nome = f"dados-organizacao-{date.today().isoformat()}.zip"
            job.status = StatusExportacao.CONCLUIDA
            job.concluido_em = datetime.now(UTC)
        registrar_sync(s, Acao.DADOS_EXPORTADOS, org_id=uuid.UUID(org_id), user_id=uuid.UUID(user_id))


# ---------------------------------------------------------------------------- manutenção --
@celery_app.task(name="manutencao.expurgar_arquivos")
def expurgar_arquivos() -> int:
    """Retenção (LGPD): apaga arquivos originais vencidos, mantendo os dados necessários."""
    total = 0
    for org in _orgs("sys_orgs_com_arquivos_a_expurgar"):
        with sync_tenant_session(TenantContext.sistema(org)) as s:
            for f in s.scalars(
                select(UploadedFile).where(
                    UploadedFile.expurgado_em.is_(None), UploadedFile.expurgar_em <= date.today()
                )
            ):
                if f.storage_path:
                    files.apagar(f.storage_path)
                f.storage_path, f.expurgado_em, f.amostra = None, datetime.now(UTC), []
                total += 1
            registrar_sync(s, Acao.EXPURGO, org_id=org, detalhes={"arquivos": total})
    return total
