"""Organização atual, configurações, empresas auditadas, usuários, atividades e notificações."""

from __future__ import annotations

import secrets
import string
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.exc import IntegrityError

from app.core.audit_trail import Acao, registrar
from app.core.codes import cnpj_valido, normalizar_cnpj
from app.core.deps import Principal, PrincipalDep, SessionDep, exigir
from app.core.errors import Conflito, NaoEncontrado
from app.core.rbac import Perm
from app.core.security import hash_senha, validar_forca_senha, verificar_senha
from app.llm.pricing import MODELOS_SUPORTADOS
from app.models import (
    AuditLog,
    Company,
    CompanyAccess,
    LlmCall,
    Membership,
    Notification,
    Organization,
    OrgSettings,
    User,
)
from app.models.enums import Papel, RegimeTributario

router = APIRouter(tags=["organização"])

UFS = {
    "AC",
    "AL",
    "AP",
    "AM",
    "BA",
    "CE",
    "DF",
    "ES",
    "GO",
    "MA",
    "MT",
    "MS",
    "MG",
    "PA",
    "PB",
    "PR",
    "PE",
    "PI",
    "RJ",
    "RN",
    "RS",
    "RO",
    "RR",
    "SC",
    "SP",
    "SE",
    "TO",
}


# ============================================================ organização e configurações ==
class ConfiguracoesOut(BaseModel):
    limiar_confirmado: float
    limiar_corrigido: float
    limiar_escalonamento: float
    modelo_principal: str | None
    modelo_escalonamento: str | None
    modelo_leve: str | None
    usar_modelo_leve: bool
    orcamento_mensal_usd: float | None
    alerta_orcamento_pct: int
    lote_min_itens: int | None
    imposto_seletivo_exige_analise: bool
    aprovacao_automatica: bool
    retencao_arquivos_dias: int
    modelos_disponiveis: list[str]


class OrganizacaoOut(BaseModel):
    id: uuid.UUID
    nome: str
    tipo: str
    configuracoes: ConfiguracoesOut
    gasto_mes_usd: float


class ConfiguracoesIn(BaseModel):
    limiar_confirmado: float | None = Field(None, ge=0.5, le=1)
    limiar_corrigido: float | None = Field(None, ge=0.5, le=1)
    limiar_escalonamento: float | None = Field(None, ge=0, le=1)
    modelo_principal: str | None = None
    modelo_escalonamento: str | None = None
    modelo_leve: str | None = None
    usar_modelo_leve: bool | None = None
    orcamento_mensal_usd: float | None = Field(None, ge=0)
    alerta_orcamento_pct: int | None = Field(None, ge=10, le=100)
    lote_min_itens: int | None = Field(None, ge=1)
    imposto_seletivo_exige_analise: bool | None = None
    aprovacao_automatica: bool | None = None
    retencao_arquivos_dias: int | None = Field(None, ge=0, le=3650)
    nome: str | None = Field(None, min_length=2, max_length=200)

    @field_validator("modelo_principal", "modelo_escalonamento", "modelo_leve")
    @classmethod
    def _modelo(cls, v: str | None) -> str | None:
        if v and v not in MODELOS_SUPORTADOS:
            raise ValueError("Modelo não suportado. Escolha um dos modelos listados.")
        return v or None


def _config_out(cfg: OrgSettings) -> ConfiguracoesOut:
    return ConfiguracoesOut(
        limiar_confirmado=float(cfg.limiar_confirmado),
        limiar_corrigido=float(cfg.limiar_corrigido),
        limiar_escalonamento=float(cfg.limiar_escalonamento),
        modelo_principal=cfg.modelo_principal,
        modelo_escalonamento=cfg.modelo_escalonamento,
        modelo_leve=cfg.modelo_leve,
        usar_modelo_leve=cfg.usar_modelo_leve,
        orcamento_mensal_usd=float(cfg.orcamento_mensal_usd) if cfg.orcamento_mensal_usd is not None else None,
        alerta_orcamento_pct=cfg.alerta_orcamento_pct,
        lote_min_itens=cfg.lote_min_itens,
        imposto_seletivo_exige_analise=cfg.imposto_seletivo_exige_analise,
        aprovacao_automatica=cfg.aprovacao_automatica,
        retencao_arquivos_dias=cfg.retencao_arquivos_dias,
        modelos_disponiveis=sorted(MODELOS_SUPORTADOS),
    )


async def gasto_mes(session: Any, org_id: uuid.UUID) -> float:
    inicio = date.today().replace(day=1)
    total = await session.scalar(
        select(func.coalesce(func.sum(LlmCall.custo_usd), 0)).where(
            LlmCall.org_id == org_id, LlmCall.created_at >= inicio
        )
    )
    return float(total or 0)


async def _carregar_config(session: Any, org_id: uuid.UUID) -> OrgSettings:
    cfg = await session.get(OrgSettings, org_id)
    if cfg is None:
        cfg = OrgSettings(org_id=org_id)
        session.add(cfg)
        await session.flush()
        await session.refresh(cfg)
    return cfg  # type: ignore[no-any-return]


@router.get("/organizacao", response_model=OrganizacaoOut)
async def organizacao_atual(
    principal: Annotated[Principal, Depends(exigir(Perm.VER))], session: SessionDep
) -> OrganizacaoOut:
    org_id = principal.exigir_org()
    org = await session.get(Organization, org_id)
    if org is None:
        raise NaoEncontrado("Organização não encontrada.")
    cfg = await _carregar_config(session, org_id)
    return OrganizacaoOut(
        id=org.id,
        nome=org.nome,
        tipo=org.tipo,
        configuracoes=_config_out(cfg),
        gasto_mes_usd=await gasto_mes(session, org_id),
    )


@router.patch("/organizacao/configuracoes", response_model=OrganizacaoOut)
async def alterar_configuracoes(
    dados: ConfiguracoesIn,
    principal: Annotated[Principal, Depends(exigir(Perm.GERENCIAR_CONFIGURACOES))],
    session: SessionDep,
) -> OrganizacaoOut:
    org_id = principal.exigir_org()
    org = await session.get(Organization, org_id)
    assert org is not None
    cfg = await _carregar_config(session, org_id)
    mudancas: dict[str, Any] = {}
    for campo, valor in dados.model_dump(exclude_unset=True).items():
        if campo == "nome":
            if valor and valor != org.nome:
                mudancas["nome"] = {"de": org.nome, "para": valor}
                org.nome = valor
            continue
        atual = getattr(cfg, campo)
        novo = Decimal(str(valor)) if isinstance(atual, Decimal) and valor is not None else valor
        if atual != novo:
            mudancas[campo] = {"de": float(atual) if isinstance(atual, Decimal) else atual, "para": valor}
            setattr(cfg, campo, novo)
    if cfg.limiar_confirmado < cfg.limiar_corrigido - Decimal("0.2"):
        raise Conflito("O limite para Confirmado não pode ser muito menor que o limite para Corrigido.")
    if mudancas:
        await registrar(
            session, principal, Acao.CONFIGURACAO, entidade="organizacao", entidade_id=org_id, detalhes=mudancas
        )
    return OrganizacaoOut(
        id=org.id,
        nome=org.nome,
        tipo=org.tipo,
        configuracoes=_config_out(cfg),
        gasto_mes_usd=await gasto_mes(session, org_id),
    )


# =================================================================== empresas auditadas ==
class EmpresaIn(BaseModel):
    razao_social: str = Field(min_length=2, max_length=250)
    nome_fantasia: str | None = Field(None, max_length=250)
    cnpj: str
    regime_tributario: RegimeTributario
    uf: str
    atividade_principal: str | None = Field(None, max_length=300)
    cnae: str | None = Field(None, max_length=10)
    atributos: dict[str, Any] = Field(default_factory=dict)

    @field_validator("cnpj")
    @classmethod
    def _cnpj(cls, v: str) -> str:
        c = normalizar_cnpj(v)
        if not cnpj_valido(c):
            raise ValueError("CNPJ inválido. Confira os dígitos (o CNPJ alfanumérico também é aceito).")
        return c

    @field_validator("uf")
    @classmethod
    def _uf(cls, v: str) -> str:
        v = v.strip().upper()
        if v not in UFS:
            raise ValueError("UF inválida.")
        return v


class EmpresaPatch(BaseModel):
    razao_social: str | None = Field(None, min_length=2, max_length=250)
    nome_fantasia: str | None = None
    regime_tributario: RegimeTributario | None = None
    uf: str | None = None
    atividade_principal: str | None = None
    cnae: str | None = None
    atributos: dict[str, Any] | None = None
    ativo: bool | None = None


class EmpresaOut(BaseModel):
    id: uuid.UUID
    razao_social: str
    nome_fantasia: str | None
    cnpj: str
    regime_tributario: str
    uf: str
    atividade_principal: str | None
    cnae: str | None
    atributos: dict[str, Any]
    ativo: bool
    created_at: datetime

    model_config = {"from_attributes": True}


async def empresas_permitidas(session: Any, principal: Principal) -> list[uuid.UUID] | None:
    """None = todas; lista = somente as liberadas (papel Leitura)."""
    if principal.papel != Papel.LEITURA:
        return None
    rows = await session.execute(
        select(CompanyAccess.company_id)
        .join(Membership, Membership.id == CompanyAccess.membership_id)
        .where(Membership.user_id == principal.user_id, Membership.org_id == principal.org_id)
    )
    return [r[0] for r in rows]


async def garantir_acesso_empresa(session: Any, principal: Principal, company_id: uuid.UUID) -> Company:
    empresa = await session.get(Company, company_id)
    if empresa is None:
        raise NaoEncontrado("Empresa não encontrada.")
    permitidas = await empresas_permitidas(session, principal)
    if permitidas is not None and company_id not in permitidas:
        raise NaoEncontrado("Empresa não encontrada.")
    return empresa  # type: ignore[no-any-return]


@router.get("/empresas", response_model=list[EmpresaOut])
async def listar_empresas(
    principal: Annotated[Principal, Depends(exigir(Perm.VER))], session: SessionDep, incluir_inativas: bool = False
) -> list[Company]:
    q = select(Company).order_by(Company.razao_social)
    if not incluir_inativas:
        q = q.where(Company.ativo.is_(True))
    permitidas = await empresas_permitidas(session, principal)
    if permitidas is not None:
        q = q.where(Company.id.in_(permitidas))
    return list((await session.execute(q)).scalars())


@router.post("/empresas", response_model=EmpresaOut, status_code=201)
async def criar_empresa(
    dados: EmpresaIn, principal: Annotated[Principal, Depends(exigir(Perm.GERENCIAR_EMPRESAS))], session: SessionDep
) -> Company:
    empresa = Company(org_id=principal.exigir_org(), **dados.model_dump(mode="json"))
    session.add(empresa)
    try:
        await session.flush()
    except IntegrityError as e:
        raise Conflito("Já existe uma empresa com este CNPJ nesta organização.") from e
    await registrar(
        session,
        principal,
        Acao.EMPRESA,
        entidade="empresa",
        entidade_id=empresa.id,
        detalhes={"operacao": "criada", "cnpj": empresa.cnpj},
    )
    return empresa


@router.get("/empresas/{company_id}", response_model=EmpresaOut)
async def obter_empresa(
    company_id: uuid.UUID, principal: Annotated[Principal, Depends(exigir(Perm.VER))], session: SessionDep
) -> Company:
    return await garantir_acesso_empresa(session, principal, company_id)


@router.patch("/empresas/{company_id}", response_model=EmpresaOut)
async def alterar_empresa(
    company_id: uuid.UUID,
    dados: EmpresaPatch,
    principal: Annotated[Principal, Depends(exigir(Perm.GERENCIAR_EMPRESAS))],
    session: SessionDep,
) -> Company:
    empresa = await garantir_acesso_empresa(session, principal, company_id)
    valores = dados.model_dump(exclude_unset=True, mode="json")
    if valores.get("uf"):
        valores["uf"] = valores["uf"].upper()
        if valores["uf"] not in UFS:
            raise Conflito("UF inválida.")
    for k, v in valores.items():
        setattr(empresa, k, v)
    await registrar(
        session,
        principal,
        Acao.EMPRESA,
        entidade="empresa",
        entidade_id=empresa.id,
        detalhes={"operacao": "alterada", "campos": sorted(valores)},
    )
    return empresa


# ============================================================================= usuários ==
class UsuarioOut(BaseModel):
    membership_id: uuid.UUID
    usuario_id: uuid.UUID
    nome: str
    email: str
    papel: str
    ativo: bool
    empresas_liberadas: list[uuid.UUID]
    ultimo_login_em: datetime | None


class UsuarioIn(BaseModel):
    nome: str = Field(min_length=2, max_length=200)
    email: EmailStr
    papel: Papel
    empresas_liberadas: list[uuid.UUID] = Field(default_factory=list)


class UsuarioCriadoOut(UsuarioOut):
    senha_temporaria: str | None


class UsuarioPatch(BaseModel):
    papel: Papel | None = None
    ativo: bool | None = None
    empresas_liberadas: list[uuid.UUID] | None = None
    nome: str | None = Field(None, min_length=2, max_length=200)


def gerar_senha_temporaria() -> str:
    alfabeto = string.ascii_letters + string.digits
    base = "".join(secrets.choice(alfabeto) for _ in range(14))
    return base[:5] + "-" + base[5:10] + "-" + base[10:] + secrets.choice("!@#%&*")


async def _usuario_out(session: Any, m: Membership) -> UsuarioOut:
    user = await session.get(User, m.user_id)
    acessos = await session.execute(select(CompanyAccess.company_id).where(CompanyAccess.membership_id == m.id))
    return UsuarioOut(
        membership_id=m.id,
        usuario_id=m.user_id,
        nome=user.nome,
        email=user.email,
        papel=m.papel,
        ativo=m.ativo and user.ativo,
        empresas_liberadas=[a[0] for a in acessos],
        ultimo_login_em=user.ultimo_login_em,
    )


@router.get("/usuarios", response_model=list[UsuarioOut])
async def listar_usuarios(
    principal: Annotated[Principal, Depends(exigir(Perm.GERENCIAR_USUARIOS))], session: SessionDep
) -> list[UsuarioOut]:
    ms = (await session.execute(select(Membership).where(Membership.org_id == principal.org_id))).scalars().all()
    saida = [await _usuario_out(session, m) for m in ms]
    return sorted(saida, key=lambda u: u.nome.lower())


@router.post("/usuarios", response_model=UsuarioCriadoOut, status_code=201)
async def criar_usuario(
    dados: UsuarioIn, principal: Annotated[Principal, Depends(exigir(Perm.GERENCIAR_USUARIOS))], session: SessionDep
) -> UsuarioCriadoOut:
    org_id = principal.exigir_org()
    existente = await session.scalar(text("SELECT sys_usuario_por_email(:e)"), {"e": dados.email.lower()})
    senha: str | None = None
    if existente is None:
        senha = gerar_senha_temporaria()
        user = User(email=dados.email.lower(), nome=dados.nome, password_hash=hash_senha(senha))
        session.add(user)
        await session.flush()
        user_id = user.id
    else:
        user_id = existente
    m = Membership(org_id=org_id, user_id=user_id, papel=dados.papel.value)
    session.add(m)
    try:
        await session.flush()
    except IntegrityError as e:
        raise Conflito("Este usuário já faz parte da organização.") from e
    await _definir_acessos(session, org_id, m.id, dados.empresas_liberadas if dados.papel == Papel.LEITURA else [])
    await registrar(
        session,
        principal,
        Acao.USUARIO,
        entidade="usuario",
        entidade_id=user_id,
        detalhes={"operacao": "adicionado", "papel": dados.papel.value},
    )
    out = await _usuario_out(session, m)
    return UsuarioCriadoOut(**out.model_dump(), senha_temporaria=senha)


async def _definir_acessos(
    session: Any, org_id: uuid.UUID, membership_id: uuid.UUID, empresas: list[uuid.UUID]
) -> None:
    await session.execute(delete(CompanyAccess).where(CompanyAccess.membership_id == membership_id))
    for cid in dict.fromkeys(empresas):
        if await session.get(Company, cid) is None:
            raise NaoEncontrado("Uma das empresas liberadas não existe nesta organização.")
        session.add(CompanyAccess(org_id=org_id, membership_id=membership_id, company_id=cid))
    await session.flush()


@router.patch("/usuarios/{membership_id}", response_model=UsuarioOut)
async def alterar_usuario(
    membership_id: uuid.UUID,
    dados: UsuarioPatch,
    principal: Annotated[Principal, Depends(exigir(Perm.GERENCIAR_USUARIOS))],
    session: SessionDep,
) -> UsuarioOut:
    m = await session.get(Membership, membership_id)
    if m is None:
        raise NaoEncontrado("Usuário não encontrado nesta organização.")
    if m.user_id == principal.user_id and (dados.ativo is False or (dados.papel and dados.papel != m.papel)):
        raise Conflito("Você não pode alterar o seu próprio papel ou desativar a si mesmo.")
    mudancas = dados.model_dump(exclude_unset=True, mode="json")
    if dados.papel is not None:
        m.papel = dados.papel.value
    if dados.ativo is not None:
        m.ativo = dados.ativo
    if dados.nome:
        user = await session.get(User, m.user_id)
        if user is not None:
            user.nome = dados.nome
    if dados.empresas_liberadas is not None:
        await _definir_acessos(session, m.org_id, m.id, dados.empresas_liberadas)
    await registrar(
        session,
        principal,
        Acao.USUARIO,
        entidade="usuario",
        entidade_id=m.user_id,
        detalhes={"operacao": "alterado", "campos": sorted(mudancas)},
    )
    return await _usuario_out(session, m)


class AlterarSenhaIn(BaseModel):
    senha_atual: str
    nova_senha: str = Field(max_length=256)


@router.post("/conta/senha", status_code=204)
async def alterar_senha(dados: AlterarSenhaIn, principal: PrincipalDep, session: SessionDep) -> None:
    user = await session.get(User, principal.user_id)
    if user is None or not verificar_senha(dados.senha_atual, user.password_hash):
        raise Conflito("A senha atual não confere.")
    erro = validar_forca_senha(dados.nova_senha)
    if erro:
        raise Conflito(erro)
    user.password_hash = hash_senha(dados.nova_senha)
    await registrar(
        session,
        principal,
        Acao.USUARIO,
        entidade="usuario",
        entidade_id=user.id,
        detalhes={"operacao": "senha_alterada"},
        plataforma=principal.org_id is None,
    )


# =========================================================================== atividades ==
class AtividadeOut(BaseModel):
    id: int
    acao: str
    user_email: str | None
    entidade: str | None
    entidade_id: str | None
    detalhes: dict[str, Any]
    ip: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class PaginaAtividades(BaseModel):
    itens: list[AtividadeOut]
    total: int


@router.get("/atividades", response_model=PaginaAtividades)
async def listar_atividades(
    principal: Annotated[Principal, Depends(exigir(Perm.VER_LOG))],
    session: SessionDep,
    busca: str | None = Query(None, max_length=100),
    acao: str | None = None,
    de: date | None = None,
    ate: date | None = None,
    pagina: int = Query(1, ge=1),
    por_pagina: int = Query(50, ge=1, le=200),
) -> PaginaAtividades:
    q = select(AuditLog).where(AuditLog.org_id == principal.org_id)
    if acao:
        q = q.where(AuditLog.acao == acao)
    if busca:
        termo = f"%{busca}%"
        q = q.where(
            or_(AuditLog.user_email.ilike(termo), AuditLog.entidade_id.ilike(termo), AuditLog.acao.ilike(termo))
        )
    if de:
        q = q.where(AuditLog.created_at >= de)
    if ate:
        q = q.where(AuditLog.created_at < datetime.combine(ate, datetime.max.time(), tzinfo=UTC))
    total = await session.scalar(select(func.count()).select_from(q.subquery()))
    rows = await session.execute(q.order_by(AuditLog.id.desc()).offset((pagina - 1) * por_pagina).limit(por_pagina))
    return PaginaAtividades(itens=[AtividadeOut.model_validate(r) for r in rows.scalars()], total=total or 0)


# ======================================================================== notificações ==
class NotificacaoOut(BaseModel):
    id: uuid.UUID
    tipo: str
    titulo: str
    mensagem: str
    link: str | None
    lida_em: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


@router.get("/notificacoes", response_model=list[NotificacaoOut])
async def listar_notificacoes(
    principal: Annotated[Principal, Depends(exigir(Perm.VER))], session: SessionDep, somente_nao_lidas: bool = False
) -> list[Notification]:
    q = (
        select(Notification)
        .where(or_(Notification.user_id.is_(None), Notification.user_id == principal.user_id))
        .order_by(Notification.created_at.desc())
        .limit(50)
    )
    if somente_nao_lidas:
        q = q.where(Notification.lida_em.is_(None))
    return list((await session.execute(q)).scalars())


@router.post("/notificacoes/marcar-lidas", status_code=204)
async def marcar_lidas(principal: Annotated[Principal, Depends(exigir(Perm.VER))], session: SessionDep) -> None:
    rows = await session.execute(select(Notification).where(Notification.lida_em.is_(None)))
    agora = datetime.now(UTC)
    for n in rows.scalars():
        if n.user_id in (None, principal.user_id):
            n.lida_em = agora


# ==================================================================== tipos auxiliares ==
class OpcoesOut(BaseModel):
    regimes: list[dict[str, str]]
    papeis: list[dict[str, str]]
    ufs: list[str]


@router.get("/opcoes", response_model=OpcoesOut)
async def opcoes() -> OpcoesOut:
    return OpcoesOut(
        regimes=[
            {"valor": "mei", "rotulo": "MEI"},
            {"valor": "simples_nacional", "rotulo": "Simples Nacional"},
            {"valor": "lucro_presumido", "rotulo": "Lucro Presumido"},
            {"valor": "lucro_real", "rotulo": "Lucro Real"},
        ],
        papeis=[
            {"valor": "administrador", "rotulo": "Administrador"},
            {"valor": "revisor", "rotulo": "Revisor"},
            {"valor": "operador", "rotulo": "Operador"},
            {"valor": "leitura", "rotulo": "Leitura"},
        ],
        ufs=sorted(UFS),
    )


TipoOrg = Literal["escritorio_contabil", "empresa"]
