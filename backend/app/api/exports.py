"""Exportações (XLSX/CSV/PDF), layouts e dados da organização (LGPD)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.audits import _carregar_auditoria
from app.core.audit_trail import Acao, registrar
from app.core.deps import Principal, SessionDep, exigir
from app.core.errors import Conflito, NaoEncontrado
from app.core.rbac import Perm
from app.export.service import COLUNAS_DISPONIVEIS, LAYOUT_PADRAO
from app.models import AuditItem, ExportJob, ExportLayout
from app.models.enums import StatusExportacao, StatusRevisao
from app.storage import files
from app.worker.celery_app import celery_app

router = APIRouter(tags=["exportação"])
Exportar = Annotated[Principal, Depends(exigir(Perm.EXPORTAR))]
Ver = Annotated[Principal, Depends(exigir(Perm.VER))]
Admin = Annotated[Principal, Depends(exigir(Perm.GERENCIAR_CONFIGURACOES))]

MIME = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv; charset=utf-8",
    "pdf": "application/pdf",
    "zip": "application/zip",
}


class JobIn(BaseModel):
    formato: str = Field(pattern="^(xlsx|csv|pdf)$")
    layout_id: uuid.UUID | None = None


class JobOut(BaseModel):
    id: uuid.UUID
    audit_id: uuid.UUID
    formato: str
    status: str
    arquivo_nome: str | None
    total_itens: int
    erro: str | None
    created_at: datetime
    concluido_em: datetime | None

    model_config = {"from_attributes": True}


@router.post("/auditorias/{audit_id}/exportacoes", response_model=JobOut, status_code=201)
async def criar_exportacao(audit_id: uuid.UUID, dados: JobIn, principal: Exportar, session: SessionDep) -> ExportJob:
    await _carregar_auditoria(session, principal, audit_id)
    if dados.formato != "pdf":
        aprovados = await session.scalar(
            select(AuditItem.id)
            .where(AuditItem.audit_id == audit_id, AuditItem.revisao_status == StatusRevisao.APROVADO)
            .limit(1)
        )
        if aprovados is None:
            raise Conflito(
                "Nenhum item foi aprovado ainda. Somente itens aprovados entram na exportação final.",
                acao="Revise e aprove os itens antes de exportar.",
            )
    job = ExportJob(
        org_id=principal.org_id,
        audit_id=audit_id,
        formato=dados.formato,
        layout_id=dados.layout_id,
        status=StatusExportacao.NA_FILA,
        created_by=principal.user_id,
    )
    session.add(job)
    await session.flush()
    await registrar(
        session,
        principal,
        Acao.EXPORTACAO,
        entidade="auditoria",
        entidade_id=audit_id,
        detalhes={"formato": dados.formato, "job": str(job.id)},
    )
    await session.commit()
    celery_app.send_task("exportacao.gerar", args=[str(job.id), str(principal.org_id)], queue="export")
    return job


@router.get("/auditorias/{audit_id}/exportacoes", response_model=list[JobOut])
async def listar_exportacoes(audit_id: uuid.UUID, principal: Ver, session: SessionDep) -> list[ExportJob]:
    await _carregar_auditoria(session, principal, audit_id)
    return list(
        await session.scalars(
            select(ExportJob).where(ExportJob.audit_id == audit_id).order_by(ExportJob.created_at.desc()).limit(50)
        )
    )


@router.get("/exportacoes/{job_id}/arquivo")
async def baixar(job_id: uuid.UUID, principal: Ver, session: SessionDep) -> Response:
    job = await session.get(ExportJob, job_id)
    if job is None or job.status != StatusExportacao.CONCLUIDA or not job.arquivo_path:
        raise NaoEncontrado("Arquivo não disponível.")
    await _carregar_auditoria(session, principal, job.audit_id)
    ext = (job.arquivo_nome or "x.bin").rsplit(".", 1)[-1]
    return Response(
        files.ler(job.arquivo_path),
        media_type=MIME.get(ext, "application/octet-stream"),
        headers={"Content-Disposition": f'attachment; filename="{job.arquivo_nome}"'},
    )


# ================================================================================ layouts ==
class ColunaLayout(BaseModel):
    campo: str
    titulo: str = Field(min_length=1, max_length=60)


class LayoutIn(BaseModel):
    nome: str = Field(min_length=2, max_length=120)
    colunas: list[ColunaLayout] = Field(min_length=1)
    separador_csv: str = Field(";", pattern="^(;|,|\\t|\\|)$")
    ncm_formatado: bool = False


class LayoutOut(LayoutIn):
    id: uuid.UUID


class OpcoesLayout(BaseModel):
    campos: dict[str, str]
    padrao: list[str]
    layouts: list[LayoutOut]


@router.get("/layouts-exportacao", response_model=OpcoesLayout)
async def listar_layouts(principal: Ver, session: SessionDep) -> OpcoesLayout:
    rows = await session.scalars(select(ExportLayout).order_by(ExportLayout.nome))
    return OpcoesLayout(
        campos=COLUNAS_DISPONIVEIS,
        padrao=LAYOUT_PADRAO,
        layouts=[
            LayoutOut(
                id=r.id,
                nome=r.nome,
                colunas=[ColunaLayout(**c) for c in r.colunas],
                separador_csv=r.separador_csv,
                ncm_formatado=r.ncm_formatado,
            )
            for r in rows
        ],
    )


@router.post("/layouts-exportacao", response_model=LayoutOut, status_code=201)
async def criar_layout(dados: LayoutIn, principal: Exportar, session: SessionDep) -> LayoutOut:
    invalidos = [c.campo for c in dados.colunas if c.campo not in COLUNAS_DISPONIVEIS]
    if invalidos:
        raise Conflito(f"Campos desconhecidos: {', '.join(invalidos)}.")
    lay = ExportLayout(
        org_id=principal.org_id,
        nome=dados.nome,
        colunas=[c.model_dump() for c in dados.colunas],
        separador_csv=dados.separador_csv,
        ncm_formatado=dados.ncm_formatado,
    )
    session.add(lay)
    await session.flush()
    return LayoutOut(id=lay.id, **dados.model_dump())


@router.delete("/layouts-exportacao/{layout_id}", status_code=204)
async def apagar_layout(layout_id: uuid.UUID, principal: Exportar, session: SessionDep) -> None:
    lay = await session.get(ExportLayout, layout_id)
    if lay is None:
        raise NaoEncontrado("Layout não encontrado.")
    await session.delete(lay)


# =================================================================================== LGPD ==
@router.post("/organizacao/exportar-dados", response_model=JobOut, status_code=202)
async def exportar_dados(principal: Admin, session: SessionDep) -> ExportJob:
    """Gera um pacote com todos os dados da organização (direito de portabilidade)."""
    from app.models import Audit

    audit_id = await session.scalar(select(Audit.id).order_by(Audit.created_at.desc()).limit(1))
    if audit_id is None:
        raise Conflito("A organização ainda não tem auditorias; não há dados a exportar.")
    job = ExportJob(
        org_id=principal.org_id,
        audit_id=audit_id,
        formato="zip",
        status=StatusExportacao.NA_FILA,
        created_by=principal.user_id,
    )
    session.add(job)
    await session.flush()
    await session.commit()
    celery_app.send_task(
        "exportacao.dados_organizacao",
        args=[str(principal.org_id), str(principal.user_id), str(job.id)],
        queue="export",
    )
    return job
