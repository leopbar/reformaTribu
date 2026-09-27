"""Dependências do FastAPI: usuário autenticado, sessão com tenant e checagem de permissões."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NaoAutorizado, Proibido
from app.core.rbac import Perm, tem_permissao
from app.core.security import AccessClaims, decodificar_access_token
from app.db.session import TenantContext, reference_admin_session, tenant_session
from app.models.enums import Papel


@dataclass(frozen=True)
class Principal:
    user_id: uuid.UUID
    email: str
    org_id: uuid.UUID | None
    papel: str | None
    platform_admin: bool
    ip: str | None
    request_id: str | None

    @property
    def ctx(self) -> TenantContext:
        return TenantContext(org_id=self.org_id, user_id=self.user_id, platform_admin=self.platform_admin)

    def exigir_org(self) -> uuid.UUID:
        if self.org_id is None:
            raise Proibido("Escolha uma organização para continuar.", acao="Selecione a organização no topo da tela.")
        return self.org_id

    @property
    def somente_leitura(self) -> bool:
        return self.papel == Papel.LEITURA


def ip_cliente(request: Request) -> str | None:
    return request.client.host if request.client else None


async def get_principal(request: Request) -> Principal:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise NaoAutorizado("Você precisa entrar para continuar.")
    claims: AccessClaims | None = decodificar_access_token(auth[7:].strip())
    if claims is None:
        raise NaoAutorizado("Sua sessão expirou. Entre novamente.", codigo="token_expirado")
    return Principal(
        user_id=claims.user_id,
        email=claims.email,
        org_id=claims.org_id,
        papel=claims.papel,
        platform_admin=claims.platform_admin,
        ip=ip_cliente(request),
        request_id=getattr(request.state, "request_id", None),
    )


PrincipalDep = Annotated[Principal, Depends(get_principal)]


async def get_session(principal: PrincipalDep) -> AsyncIterator[AsyncSession]:
    async with tenant_session(principal.ctx) as s:
        yield s


SessionDep = Annotated[AsyncSession, Depends(get_session)]


def exigir(perm: Perm) -> Callable[[Principal], Awaitable[Principal]]:
    async def _dep(principal: PrincipalDep) -> Principal:
        principal.exigir_org()
        if not tem_permissao(principal.papel, perm):
            raise Proibido("Seu papel nesta organização não permite esta ação.")
        return principal

    return _dep


async def exigir_superadmin(principal: PrincipalDep) -> Principal:
    if not principal.platform_admin:
        raise Proibido("Somente o superadministrador da plataforma pode gerenciar a base de referência.")
    return principal


SuperAdminDep = Annotated[Principal, Depends(exigir_superadmin)]


async def get_ref_session(principal: SuperAdminDep) -> AsyncIterator[AsyncSession]:
    async with reference_admin_session(principal.ctx) as s:
        yield s


RefSessionDep = Annotated[AsyncSession, Depends(get_ref_session)]
