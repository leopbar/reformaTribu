"""Painel da organização (carteira de empresas) e dicionário de abreviações."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from app.api.orgs import empresas_permitidas, gasto_mes
from app.core.audit_trail import Acao, registrar
from app.core.deps import Principal, SessionDep, exigir
from app.core.errors import Conflito, NaoEncontrado, Proibido
from app.core.rbac import Perm
from app.models import Abbreviation, Audit, AuditItem, Company, MappingTemplate, OrgSettings
from app.models.enums import StatusAuditoria, StatusItem, StatusRevisao

router = APIRouter(tags=["painel"])
Ver = Annotated[Principal, Depends(exigir(Perm.VER))]


class EmpresaPainel(BaseModel):
    id: uuid.UUID
    razao_social: str
    cnpj: str
    regime_tributario: str
    auditorias: int
    em_andamento: int
    pendentes_revisao: int
    analise_humana_pendente: int
    ultima_auditoria_em: datetime | None
    ultima_auditoria_id: uuid.UUID | None
    ultima_auditoria_status: str | None


class Painel(BaseModel):
    empresas: list[EmpresaPainel]
    em_andamento: list[dict[str, Any]]
    totais: dict[str, Any]


@router.get("/painel", response_model=Painel)
async def painel(principal: Ver, session: SessionDep) -> Painel:
    q = select(Company).where(Company.ativo.is_(True)).order_by(Company.razao_social)
    permitidas = await empresas_permitidas(session, principal)
    if permitidas is not None:
        q = q.where(Company.id.in_(permitidas))
    empresas = list(await session.scalars(q))
    ids = [e.id for e in empresas]
    por_empresa = (
        dict(
            (
                await session.execute(
                    select(Audit.company_id, func.count()).where(Audit.company_id.in_(ids)).group_by(Audit.company_id)
                )
            ).all()
        )
        if ids
        else {}
    )
    ativos = (
        StatusAuditoria.PREPARANDO,
        StatusAuditoria.PRONTA,
        StatusAuditoria.PROCESSANDO,
        StatusAuditoria.AGUARDANDO_LOTE,
        StatusAuditoria.PAUSADA_ORCAMENTO,
    )
    andamento_por_emp = (
        dict(
            (
                await session.execute(
                    select(Audit.company_id, func.count())
                    .where(Audit.company_id.in_(ids), Audit.status.in_(ativos))
                    .group_by(Audit.company_id)
                )
            ).all()
        )
        if ids
        else {}
    )
    pend = (
        (
            await session.execute(
                select(
                    AuditItem.company_id,
                    func.count(),
                    func.count().filter(AuditItem.status == StatusItem.ANALISE_HUMANA),
                )
                .where(
                    AuditItem.company_id.in_(ids),
                    AuditItem.ignorado.is_(False),
                    AuditItem.revisao_status == StatusRevisao.PENDENTE,
                    AuditItem.status.in_([StatusItem.CONFIRMADO, StatusItem.CORRIGIDO, StatusItem.ANALISE_HUMANA]),
                )
                .group_by(AuditItem.company_id)
            )
        ).all()
        if ids
        else []
    )
    pend_d = {r[0]: (r[1], r[2]) for r in pend}
    ultimas: dict[uuid.UUID, Audit] = {}
    if ids:
        sub = (
            select(Audit.company_id, func.max(Audit.created_at).label("m"))
            .where(Audit.company_id.in_(ids))
            .group_by(Audit.company_id)
            .subquery()
        )
        for a in await session.scalars(
            select(Audit).join(sub, (Audit.company_id == sub.c.company_id) & (Audit.created_at == sub.c.m))
        ):
            ultimas[a.company_id] = a
    saida = [
        EmpresaPainel(
            id=e.id,
            razao_social=e.razao_social,
            cnpj=e.cnpj,
            regime_tributario=e.regime_tributario,
            auditorias=por_empresa.get(e.id, 0),
            em_andamento=andamento_por_emp.get(e.id, 0),
            pendentes_revisao=pend_d.get(e.id, (0, 0))[0],
            analise_humana_pendente=pend_d.get(e.id, (0, 0))[1],
            ultima_auditoria_em=ultimas[e.id].created_at if e.id in ultimas else None,
            ultima_auditoria_id=ultimas[e.id].id if e.id in ultimas else None,
            ultima_auditoria_status=ultimas[e.id].status if e.id in ultimas else None,
        )
        for e in empresas
    ]
    andamento = []
    if principal.papel != "leitura":
        for a, nome in (
            await session.execute(
                select(Audit, Company.razao_social)
                .join(Company, Company.id == Audit.company_id)
                .where(Audit.status.in_(ativos))
                .order_by(Audit.created_at.desc())
                .limit(20)
            )
        ).all():
            andamento.append(
                {
                    "id": str(a.id),
                    "nome": a.nome,
                    "empresa": nome,
                    "status": a.status,
                    "contadores": a.contadores or {},
                    "total_itens": a.total_itens,
                }
            )
    cfg = await session.get(OrgSettings, principal.org_id)
    return Painel(
        empresas=saida,
        em_andamento=andamento,
        totais={
            "empresas": len(empresas),
            "pendentes_revisao": sum(p[0] for p in pend_d.values()),
            "analise_humana": sum(p[1] for p in pend_d.values()),
            "gasto_mes_usd": await gasto_mes(session, principal.exigir_org())
            if principal.papel == "administrador"
            else None,
            "orcamento_usd": float(cfg.orcamento_mensal_usd)
            if cfg and cfg.orcamento_mensal_usd and principal.papel == "administrador"
            else None,
        },
    )


# =========================================================================== abreviações ==
class AbreviacaoIn(BaseModel):
    abreviacao: str = Field(min_length=1, max_length=40, pattern=r"^[^\s]+$")
    expansao: str = Field(min_length=1, max_length=120)
    global_: bool = Field(False, alias="global")


class AbreviacaoOut(BaseModel):
    id: uuid.UUID
    abreviacao: str
    expansao: str
    ativo: bool
    global_: bool = Field(alias="global")

    model_config = {"populate_by_name": True}


@router.get("/abreviacoes", response_model=list[AbreviacaoOut], response_model_by_alias=True)
async def listar_abreviacoes(principal: Ver, session: SessionDep, busca: str | None = None) -> list[AbreviacaoOut]:
    q = select(Abbreviation).order_by(Abbreviation.abreviacao)
    if busca:
        q = q.where(or_(Abbreviation.abreviacao.ilike(f"%{busca}%"), Abbreviation.expansao.ilike(f"%{busca}%")))
    return [
        AbreviacaoOut(id=a.id, abreviacao=a.abreviacao, expansao=a.expansao, ativo=a.ativo, global_=a.org_id is None)
        for a in await session.scalars(q.limit(2000))
    ]


@router.post("/abreviacoes", response_model=AbreviacaoOut, status_code=201, response_model_by_alias=True)
async def criar_abreviacao(
    dados: AbreviacaoIn,
    principal: Annotated[Principal, Depends(exigir(Perm.GERENCIAR_ABREVIACOES))],
    session: SessionDep,
) -> AbreviacaoOut:
    if dados.global_ and not principal.platform_admin:
        raise Proibido("Somente o superadministrador altera o dicionário global.")
    org = None if dados.global_ else principal.org_id
    existente = await session.scalar(
        select(Abbreviation).where(
            Abbreviation.abreviacao == dados.abreviacao.lower(),
            Abbreviation.org_id.is_(None) if org is None else Abbreviation.org_id == org,
        )
    )
    if existente is not None:
        raise Conflito("Essa abreviação já existe neste dicionário.")
    a = Abbreviation(org_id=org, abreviacao=dados.abreviacao.lower(), expansao=dados.expansao.lower())
    session.add(a)
    await session.flush()
    await registrar(
        session,
        principal,
        Acao.ABREVIACAO,
        entidade="abreviacao",
        entidade_id=a.id,
        detalhes={"abreviacao": a.abreviacao, "expansao": a.expansao, "global": dados.global_},
    )
    return AbreviacaoOut(id=a.id, abreviacao=a.abreviacao, expansao=a.expansao, ativo=a.ativo, global_=org is None)


class AbreviacaoPatch(BaseModel):
    expansao: str | None = Field(None, min_length=1, max_length=120)
    ativo: bool | None = None


@router.patch("/abreviacoes/{abrev_id}", response_model=AbreviacaoOut, response_model_by_alias=True)
async def alterar_abreviacao(
    abrev_id: uuid.UUID,
    dados: AbreviacaoPatch,
    principal: Annotated[Principal, Depends(exigir(Perm.GERENCIAR_ABREVIACOES))],
    session: SessionDep,
) -> AbreviacaoOut:
    a = await session.get(Abbreviation, abrev_id)
    if a is None:
        raise NaoEncontrado("Abreviação não encontrada.")
    if a.org_id is None and not principal.platform_admin:
        raise Proibido("Para mudar uma abreviação global nesta organização, crie uma com a mesma sigla.")
    if dados.expansao is not None:
        a.expansao = dados.expansao.lower()
    if dados.ativo is not None:
        a.ativo = dados.ativo
    await registrar(
        session,
        principal,
        Acao.ABREVIACAO,
        entidade="abreviacao",
        entidade_id=a.id,
        detalhes=dados.model_dump(exclude_unset=True),
    )
    return AbreviacaoOut(id=a.id, abreviacao=a.abreviacao, expansao=a.expansao, ativo=a.ativo, global_=a.org_id is None)


# ================================================================= modelos de mapeamento ==
class ModeloOut(BaseModel):
    id: uuid.UUID
    nome: str
    sistema_origem: str | None
    company_id: uuid.UUID | None
    mapeamento: dict[str, Any]
    created_at: datetime

    model_config = {"from_attributes": True}


@router.get("/modelos-mapeamento", response_model=list[ModeloOut])
async def listar_modelos(principal: Ver, session: SessionDep) -> list[MappingTemplate]:
    return list(await session.scalars(select(MappingTemplate).order_by(MappingTemplate.nome)))


@router.delete("/modelos-mapeamento/{modelo_id}", status_code=204)
async def apagar_modelo(
    modelo_id: uuid.UUID, principal: Annotated[Principal, Depends(exigir(Perm.CRIAR_AUDITORIA))], session: SessionDep
) -> None:
    m = await session.get(MappingTemplate, modelo_id)
    if m is None:
        raise NaoEncontrado("Modelo não encontrado.")
    await session.delete(m)
