"""Registro de ações relevantes no log de auditoria imutável."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog

if TYPE_CHECKING:
    from app.core.deps import Principal


class Acao:
    LOGIN = "login"
    LOGIN_FALHOU = "login_falhou"
    LOGOUT = "logout"
    TROCA_ORGANIZACAO = "troca_organizacao"
    REUSO_REFRESH = "reuso_refresh_token"
    UPLOAD = "upload_planilha"
    AUDITORIA_CRIADA = "auditoria_criada"
    AUDITORIA_INICIADA = "auditoria_iniciada"
    AUDITORIA_CANCELADA = "auditoria_cancelada"
    ITEM_REPROCESSADO = "item_reprocessado"
    APROVACAO = "aprovacao"
    APROVACAO_LOTE = "aprovacao_lote"
    EDICAO = "edicao"
    REJEICAO = "rejeicao"
    DESFAZER = "desfazer"
    EXPORTACAO = "exportacao"
    CONFIGURACAO = "configuracao_alterada"
    USUARIO = "usuario_alterado"
    EMPRESA = "empresa_alterada"
    ORGANIZACAO = "organizacao_alterada"
    ABREVIACAO = "abreviacao_alterada"
    REFERENCIA_IMPORTADA = "referencia_importada"
    REGRA_REVISADA = "regra_revisada"
    REGRA_EDITADA = "regra_editada"
    ORCAMENTO = "orcamento"
    DADOS_EXPORTADOS = "dados_organizacao_exportados"
    DADOS_EXCLUIDOS = "dados_organizacao_excluidos"
    EXPURGO = "expurgo_arquivos"


def _registro(
    acao: str,
    *,
    org_id: uuid.UUID | None,
    user_id: uuid.UUID | None,
    user_email: str | None,
    entidade: str | None,
    entidade_id: object | None,
    detalhes: dict[str, Any] | None,
    ip: str | None,
    request_id: str | None,
) -> dict[str, Any]:
    # Inserção via Core (sem RETURNING): entradas sem organização não são legíveis pela
    # aplicação por causa da RLS, mas precisam poder ser gravadas.
    return dict(
        org_id=org_id,
        user_id=user_id,
        user_email=user_email,
        acao=acao,
        entidade=entidade,
        entidade_id=str(entidade_id) if entidade_id is not None else None,
        detalhes=detalhes or {},
        ip=ip,
        request_id=request_id,
    )


async def registrar(
    session: AsyncSession,
    principal: Principal | None,
    acao: str,
    *,
    entidade: str | None = None,
    entidade_id: object | None = None,
    detalhes: dict[str, Any] | None = None,
    org_id: uuid.UUID | None = None,
    plataforma: bool = False,
) -> None:
    """Grava uma entrada. `plataforma=True` grava sem organização (visível ao superadministrador)."""
    await session.execute(
        insert(AuditLog).values(
            **_registro(
                acao,
                org_id=None if plataforma else (org_id or (principal.org_id if principal else None)),
                user_id=principal.user_id if principal else None,
                user_email=principal.email if principal else None,
                entidade=entidade,
                entidade_id=entidade_id,
                detalhes=detalhes,
                ip=principal.ip if principal else None,
                request_id=principal.request_id if principal else None,
            )
        )
    )


def registrar_sync(
    session: Session,
    acao: str,
    *,
    org_id: uuid.UUID | None,
    user_id: uuid.UUID | None = None,
    user_email: str | None = None,
    entidade: str | None = None,
    entidade_id: object | None = None,
    detalhes: dict[str, Any] | None = None,
) -> None:
    session.execute(
        insert(AuditLog).values(
            **_registro(
                acao,
                org_id=org_id,
                user_id=user_id,
                user_email=user_email,
                entidade=entidade,
                entidade_id=entidade_id,
                detalhes=detalhes,
                ip=None,
                request_id=None,
            )
        )
    )
