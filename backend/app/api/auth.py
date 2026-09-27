"""Autenticação: login, refresh com rotação, troca de organização e logout."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.audit_trail import Acao, registrar
from app.core.deps import Principal, PrincipalDep, SessionDep, ip_cliente
from app.core.errors import MuitasTentativas, NaoAutorizado, Proibido
from app.core.rbac import permissoes_do_papel
from app.core.redis import redis_async
from app.core.security import (
    AccessClaims,
    criar_access_token,
    hash_refresh,
    hash_senha,
    novo_csrf_token,
    novo_refresh_token,
    precisa_rehash,
    verificar_senha,
)
from app.db.session import TenantContext, tenant_session
from app.models import Membership, Organization, RefreshToken, User

router = APIRouter(prefix="/auth", tags=["autenticação"])

COOKIE_REFRESH = "rt"
COOKIE_CSRF = "csrf_token"


class LoginIn(BaseModel):
    # No login o e-mail não é validado quanto ao formato: basta procurar a conta.
    email: str = Field(min_length=3, max_length=320)
    senha: str = Field(min_length=1, max_length=256)
    org_id: uuid.UUID | None = None


class OrgResumo(BaseModel):
    org_id: uuid.UUID
    nome: str
    tipo: str
    papel: str


class SessaoOut(BaseModel):
    access_token: str
    expira_em_segundos: int
    usuario_id: uuid.UUID
    nome: str
    email: str
    superadmin: bool
    org_atual: OrgResumo | None
    organizacoes: list[OrgResumo]
    permissoes: list[str]


class TrocarOrgIn(BaseModel):
    org_id: uuid.UUID


def _definir_cookies(response: Response, refresh: str) -> None:
    s = get_settings()
    max_age = s.refresh_token_days * 86400
    response.set_cookie(
        COOKIE_REFRESH,
        refresh,
        max_age=max_age,
        httponly=True,
        secure=s.cookie_secure,
        samesite="strict",
        path="/api/auth",
    )
    response.set_cookie(
        COOKIE_CSRF,
        novo_csrf_token(),
        max_age=max_age,
        httponly=False,
        secure=s.cookie_secure,
        samesite="strict",
        path="/",
    )


def _limpar_cookies(response: Response) -> None:
    response.delete_cookie(COOKIE_REFRESH, path="/api/auth")
    response.delete_cookie(COOKIE_CSRF, path="/")


def _verificar_csrf(request: Request) -> None:
    cookie = request.cookies.get(COOKIE_CSRF)
    header = request.headers.get("x-csrf-token")
    if not cookie or not header or cookie != header:
        raise Proibido(
            "A verificação de segurança da sessão falhou. Recarregue a página e entre novamente.",
            codigo="csrf_invalido",
        )


async def _organizacoes(session: AsyncSession) -> list[OrgResumo]:
    rows = await session.execute(
        select(Membership.org_id, Organization.nome, Organization.tipo, Membership.papel)
        .join(Organization, Organization.id == Membership.org_id)
        .where(Membership.user_id == text("app_user_id()"), Membership.ativo.is_(True), Organization.ativo.is_(True))
        .order_by(Organization.nome)
    )
    return [OrgResumo(org_id=r[0], nome=r[1], tipo=r[2], papel=r[3]) for r in rows]


async def _montar_sessao(
    session: AsyncSession, user: User, org_desejada: uuid.UUID | None
) -> tuple[SessaoOut, uuid.UUID | None]:
    orgs = await _organizacoes(session)
    atual = next((o for o in orgs if o.org_id == org_desejada), None) or (orgs[0] if orgs else None)
    token, exp = criar_access_token(
        AccessClaims(
            user_id=user.id,
            org_id=atual.org_id if atual else None,
            papel=atual.papel if atual else None,
            platform_admin=user.is_platform_admin,
            email=user.email,
        )
    )
    return (
        SessaoOut(
            access_token=token,
            expira_em_segundos=exp,
            usuario_id=user.id,
            nome=user.nome,
            email=user.email,
            superadmin=user.is_platform_admin,
            org_atual=atual,
            organizacoes=orgs,
            permissoes=permissoes_do_papel(atual.papel if atual else None),
        ),
        atual.org_id if atual else None,
    )


async def _emitir_refresh(
    session: AsyncSession,
    request: Request,
    user_id: uuid.UUID,
    org_id: uuid.UUID | None,
    familia: uuid.UUID | None = None,
) -> tuple[str, RefreshToken]:
    token, token_hash = novo_refresh_token()
    rt = RefreshToken(
        user_id=user_id,
        familia_id=familia or uuid.uuid4(),
        token_hash=token_hash,
        org_id=org_id,
        expira_em=datetime.now(UTC) + timedelta(days=get_settings().refresh_token_days),
        user_agent=(request.headers.get("user-agent") or "")[:300],
        ip=ip_cliente(request),
    )
    session.add(rt)
    await session.flush()
    return token, rt


@router.post("/login", response_model=SessaoOut)
async def login(dados: LoginIn, request: Request, response: Response) -> SessaoOut:
    s = get_settings()
    email = dados.email.strip().lower()
    ip = ip_cliente(request) or "?"
    r = redis_async()
    chave_email, chave_ip = f"login:falhas:{email}", f"login:falhas_ip:{ip}"
    try:
        falhas_email = int(await r.get(chave_email) or 0)
        falhas_ip = int(await r.get(chave_ip) or 0)
    except Exception:
        falhas_email = falhas_ip = 0
    if falhas_email >= s.login_max_tentativas or falhas_ip >= s.login_max_tentativas * 4:
        raise MuitasTentativas(
            "Muitas tentativas de acesso sem sucesso.",
            acao=f"Aguarde {s.login_bloqueio_minutos} minutos e tente novamente.",
        )

    async with tenant_session(None) as session:
        row = (await session.execute(text("SELECT * FROM sys_buscar_login(:e)"), {"e": email})).first()
    valido = verificar_senha(dados.senha, row.password_hash if row else None)
    if not row or not valido or not row.ativo:
        try:
            for chave in (chave_email, chave_ip):
                await r.incr(chave)
                await r.expire(chave, s.login_bloqueio_minutos * 60)
        except Exception:  # noqa: S110
            pass
        async with tenant_session(None) as session:
            await registrar(session, None, Acao.LOGIN_FALHOU, detalhes={"motivo": "credenciais"}, plataforma=True)
        raise NaoAutorizado("E-mail ou senha incorretos.", codigo="credenciais_invalidas")

    try:
        await r.delete(chave_email)
    except Exception:  # noqa: S110
        pass

    ctx = TenantContext(org_id=dados.org_id, user_id=row.id, platform_admin=row.is_platform_admin)
    async with tenant_session(ctx) as session:
        user = (await session.execute(select(User).where(User.id == row.id))).scalar_one()
        if precisa_rehash(user.password_hash):
            user.password_hash = hash_senha(dados.senha)
        user.ultimo_login_em = datetime.now(UTC)
        sessao, org_id = await _montar_sessao(session, user, dados.org_id)
        token, _ = await _emitir_refresh(session, request, user.id, org_id)
        principal = Principal(user.id, user.email, org_id, None, user.is_platform_admin, ip, None)
    # O registro vai numa sessão com o contexto da organização escolhida (exigência da RLS).
    async with tenant_session(principal.ctx) as session:
        await registrar(session, principal, Acao.LOGIN, org_id=org_id, plataforma=org_id is None)
    _definir_cookies(response, token)
    return sessao


@router.post("/refresh", response_model=SessaoOut)
async def refresh(request: Request, response: Response) -> SessaoOut:
    _verificar_csrf(request)
    bruto = request.cookies.get(COOKIE_REFRESH)
    if not bruto:
        raise NaoAutorizado("Sua sessão expirou. Entre novamente.")
    agora = datetime.now(UTC)
    reuso = False
    async with tenant_session(None) as session:
        rt = (
            await session.execute(select(RefreshToken).where(RefreshToken.token_hash == hash_refresh(bruto)))
        ).scalar_one_or_none()
        if rt is None:
            _limpar_cookies(response)
            raise NaoAutorizado("Sua sessão expirou. Entre novamente.")
        if rt.revogado_em is not None:
            # Reuso de token já rotacionado: possível roubo. Revoga a família inteira. A revogação é
            # gravada (commit) ANTES de responder com o erro.
            await session.execute(
                update(RefreshToken)
                .where(RefreshToken.familia_id == rt.familia_id, RefreshToken.revogado_em.is_(None))
                .values(revogado_em=agora)
            )
            await registrar(
                session, None, Acao.REUSO_REFRESH, entidade="usuario", entidade_id=rt.user_id, plataforma=True
            )
            reuso = True
    if reuso:
        _limpar_cookies(response)
        raise NaoAutorizado("Por segurança, sua sessão foi encerrada. Entre novamente.")
    assert rt is not None
    async with tenant_session(None) as session:
        if rt.expira_em < agora:
            _limpar_cookies(response)
            raise NaoAutorizado("Sua sessão expirou. Entre novamente.")
        user_id, org_id, familia, antigo_id = rt.user_id, rt.org_id, rt.familia_id, rt.id

    async with tenant_session(TenantContext(org_id=org_id, user_id=user_id)) as session:
        user = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if user is None or not user.ativo:
            _limpar_cookies(response)
            raise NaoAutorizado("Seu acesso foi desativado. Procure o administrador.")
        sessao, org_atual = await _montar_sessao(session, user, org_id)
        token, novo = await _emitir_refresh(session, request, user_id, org_atual, familia)
        await session.execute(
            update(RefreshToken).where(RefreshToken.id == antigo_id).values(revogado_em=agora, substituido_por=novo.id)
        )
    _definir_cookies(response, token)
    return sessao


@router.post("/trocar-organizacao", response_model=SessaoOut)
async def trocar_organizacao(
    dados: TrocarOrgIn, principal: PrincipalDep, request: Request, response: Response
) -> SessaoOut:
    ctx = TenantContext(org_id=dados.org_id, user_id=principal.user_id, platform_admin=principal.platform_admin)
    async with tenant_session(ctx) as session:
        user = (await session.execute(select(User).where(User.id == principal.user_id))).scalar_one()
        sessao, org_id = await _montar_sessao(session, user, dados.org_id)
        if org_id != dados.org_id:
            raise Proibido("Você não tem acesso a essa organização.")
        bruto = request.cookies.get(COOKIE_REFRESH)
        if bruto:
            await session.execute(
                update(RefreshToken).where(RefreshToken.token_hash == hash_refresh(bruto)).values(org_id=org_id)
            )
        p = Principal(
            principal.user_id,
            principal.email,
            org_id,
            None,
            principal.platform_admin,
            principal.ip,
            principal.request_id,
        )
        await registrar(session, p, Acao.TROCA_ORGANIZACAO)
    return sessao


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response) -> Response:
    _verificar_csrf(request)
    bruto = request.cookies.get(COOKIE_REFRESH)
    if bruto:
        async with tenant_session(None) as session:
            rt = (
                await session.execute(select(RefreshToken).where(RefreshToken.token_hash == hash_refresh(bruto)))
            ).scalar_one_or_none()
            if rt:
                await session.execute(
                    update(RefreshToken)
                    .where(RefreshToken.familia_id == rt.familia_id, RefreshToken.revogado_em.is_(None))
                    .values(revogado_em=datetime.now(UTC))
                )
    response.status_code = 204
    _limpar_cookies(response)
    return response


@router.get("/eu", response_model=SessaoOut)
async def eu(principal: PrincipalDep, session: SessionDep) -> SessaoOut:
    user = (await session.execute(select(User).where(User.id == principal.user_id))).scalar_one()
    sessao, _ = await _montar_sessao(session, user, principal.org_id)
    return sessao
