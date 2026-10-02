"""Base de referência (superadministrador): versões, importações, regras e catálogo de atributos.
Também: busca de códigos oficiais (qualquer usuário) e gestão de organizações da plataforma."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, or_, select, text, update
from sqlalchemy.orm import Session

from app.api.orgs import gerar_senha_temporaria
from app.core.audit_trail import Acao, registrar
from app.core.codes import formatar_codigo
from app.core.deps import Principal, PrincipalDep, RefSessionDep, SessionDep, SuperAdminDep, exigir
from app.core.errors import AppError, Conflito, NaoEncontrado
from app.core.rbac import Perm
from app.core.security import hash_senha
from app.db.session import TenantContext, tenant_session
from app.models import (
    CClassTribCode,
    ConditionAttribute,
    LegalProvision,
    LegalRule,
    Membership,
    NbsNode,
    NcmNode,
    Organization,
    OrgSettings,
    RefVersion,
    User,
)
from app.models.enums import FonteReferencia, OrigemRegra, StatusRegra, StatusVersao, TipoOrganizacao
from app.reference.search import autocompletar
from app.reference.service import INSTRUCOES_UPLOAD
from app.rules.divergencias import ContextoDivergencias, exige_justificativa
from app.rules.official import sincronizar_codigos
from app.rules.schema import de_yaml, para_yaml, regra_para_declarativa
from app.rules.uso import resumo as resumo_pelo_uso
from app.rules.validation import validar_regra
from app.storage import files
from app.worker.celery_app import celery_app

router = APIRouter(tags=["base de referência"])
Ver = Annotated[Principal, Depends(exigir(Perm.VER))]


# ======================================================================== busca pública ==
class CodigoOficial(BaseModel):
    codigo: str
    formatado: str
    descricao: str
    descricao_completa: str
    folha: bool


@router.get("/codigos/busca", response_model=list[CodigoOficial])
async def buscar_codigos(
    principal: PrincipalDep,
    session: SessionDep,
    q: str = Query(min_length=2, max_length=100),
    tipo: str = Query("ncm", pattern="^(ncm|nbs)$"),
    versao_id: uuid.UUID | None = None,
) -> list[CodigoOficial]:
    vid = versao_id or await session.scalar(
        select(RefVersion.id)
        .where(RefVersion.fonte == tipo, RefVersion.status == StatusVersao.ATIVA)
        .order_by(RefVersion.coletado_em.desc())
    )
    if vid is None:
        raise Conflito(f"A tabela {tipo.upper()} ainda não foi importada na base de referência.")
    rows = await autocompletar(session, tipo, vid, q)
    return [
        CodigoOficial(
            codigo=r["codigo"],
            formatado=r["codigo_formatado"],
            descricao=r["descricao"],
            descricao_completa=r["descricao_completa"],
            folha=r["folha"],
        )
        for r in rows
    ]


# ============================================================================== versões ==
class VersaoOut(BaseModel):
    id: uuid.UUID
    fonte: str
    rotulo: str
    url_origem: str | None
    modo_coleta: str
    coletado_em: datetime
    sha256: str
    arquivo_nome: str | None
    status: str
    vigencia_inicio: date | None
    vigencia_fim: date | None
    importado_por_email: str | None
    estatisticas: dict[str, Any]
    avisos: list[Any]
    erro: str | None
    embeddings_status: str
    embeddings_modelo: str | None

    model_config = {"from_attributes": True}


class AtoNormativoOut(BaseModel):
    chave: str
    rotulo: str
    ementa: str
    url: str
    versao: VersaoOut | None


class StatusBase(BaseModel):
    fontes: dict[str, VersaoOut | None]
    atos_normativos: list[AtoNormativoOut]
    completa: bool
    faltando: list[str]
    regras: dict[str, int]
    instrucoes: dict[str, str]


@router.get("/referencia/status", response_model=StatusBase)
async def status_base(principal: PrincipalDep, session: SessionDep) -> StatusBase:
    from app.reference.importers.normas import CATALOGO

    fontes: dict[str, VersaoOut | None] = {}
    for f in FonteReferencia:
        if f == FonteReferencia.NORMAS:
            continue
        v = await session.scalar(
            select(RefVersion)
            .where(RefVersion.fonte == f.value, RefVersion.status == StatusVersao.ATIVA)
            .order_by(RefVersion.coletado_em.desc())
            .limit(1)
        )
        fontes[f.value] = VersaoOut.model_validate(v) if v else None
    atos_ativos = {
        v.rotulo: v
        for v in await session.scalars(
            select(RefVersion).where(RefVersion.fonte == "normas", RefVersion.status == StatusVersao.ATIVA)
        )
    }
    atos = [
        AtoNormativoOut(
            chave=a.chave,
            rotulo=a.rotulo,
            ementa=a.ementa,
            url=a.url,
            versao=VersaoOut.model_validate(atos_ativos[a.rotulo]) if a.rotulo in atos_ativos else None,
        )
        for a in CATALOGO
    ]
    regras = dict((await session.execute(select(LegalRule.status, func.count()).group_by(LegalRule.status))).all())
    # Regras aprovadas não são mais pré-requisito: o analista raciocina a partir do texto legal e das tabelas.
    faltando = [f for f, v in fontes.items() if v is None]
    return StatusBase(
        fontes=fontes,
        atos_normativos=atos,
        completa=not faltando,
        faltando=faltando,
        regras=regras,
        instrucoes=INSTRUCOES_UPLOAD,
    )


@router.get("/referencia/versoes", response_model=list[VersaoOut])
async def listar_versoes(principal: SuperAdminDep, session: RefSessionDep, fonte: str | None = None) -> list[Any]:
    q = select(RefVersion).order_by(RefVersion.coletado_em.desc()).limit(100)
    if fonte:
        q = q.where(RefVersion.fonte == fonte)
    return list(await session.scalars(q))


class ImportarIn(BaseModel):
    fonte: FonteReferencia
    url: str | None = Field(None, max_length=500)


class TarefaOut(BaseModel):
    tarefa_id: str
    mensagem: str


@router.post("/referencia/importar", response_model=TarefaOut, status_code=202)
async def importar(dados: ImportarIn, principal: SuperAdminDep, session: RefSessionDep) -> TarefaOut:
    r = celery_app.send_task(
        "referencia.importar",
        kwargs={
            "fonte": dados.fonte.value,
            "url": dados.url,
            "usuario_id": str(principal.user_id),
            "usuario_email": principal.email,
        },
        queue="reference",
    )
    return TarefaOut(tarefa_id=r.id, mensagem="Importação iniciada. Acompanhe na lista de versões.")


class ImportarAtoIn(BaseModel):
    chave: str = Field(max_length=40)


@router.post("/referencia/importar-ato", response_model=TarefaOut, status_code=202)
async def importar_ato(dados: ImportarAtoIn, principal: SuperAdminDep, session: RefSessionDep) -> TarefaOut:
    from app.reference.importers.normas import ato_por_chave

    try:
        ato = ato_por_chave(dados.chave)
    except ValueError as e:
        raise AppError(str(e)) from e
    r = celery_app.send_task(
        "referencia.importar_ato",
        kwargs={"chave": ato.chave, "usuario_id": str(principal.user_id), "usuario_email": principal.email},
        queue="reference",
    )
    return TarefaOut(tarefa_id=r.id, mensagem=f"Importação de {ato.rotulo} iniciada.")


@router.post("/referencia/upload", response_model=TarefaOut, status_code=202)
async def importar_arquivo(
    principal: SuperAdminDep,
    session: RefSessionDep,
    fonte: Annotated[FonteReferencia, Form()],
    arquivo: Annotated[UploadFile, File()],
) -> TarefaOut:
    dados = await arquivo.read(200 * 1024 * 1024)
    if not dados:
        raise AppError("Arquivo vazio.")
    ext = (arquivo.filename or "arquivo").rsplit(".", 1)[-1].lower()[:5]
    rel = files.salvar(f"referencia/_uploads/{fonte.value}", dados, ext or "bin")
    r = celery_app.send_task(
        "referencia.importar",
        kwargs={
            "fonte": fonte.value,
            "arquivo_rel": rel,
            "nome_arquivo": arquivo.filename,
            "usuario_id": str(principal.user_id),
            "usuario_email": principal.email,
        },
        queue="reference",
    )
    return TarefaOut(tarefa_id=r.id, mensagem="Arquivo recebido. A importação foi iniciada.")


@router.get("/referencia/tarefas/{tarefa_id}")
async def status_tarefa(tarefa_id: str, principal: SuperAdminDep) -> dict[str, Any]:
    from celery.result import AsyncResult

    r: AsyncResult[Any] = AsyncResult(tarefa_id, app=celery_app)
    return {"estado": r.state}


# ================================================================================ regras ==
class RegraResumo(BaseModel):
    id: uuid.UUID
    slug: str
    versao: int
    anexo: str | None
    item: str | None
    descricao_legal: str
    dispositivo_legal: str
    tipo_tratamento: str
    tipo_codigo: str | None
    cst_ibs_cbs: str | None
    cclasstrib: str | None
    status: str
    origem: str
    total_codigos: int
    total_condicoes: int
    erros: int
    avisos: int
    divergencias: int = 0
    controverso: bool
    updated_at: datetime


class PaginaRegras(BaseModel):
    itens: list[RegraResumo]
    total: int
    por_status: dict[str, int]
    anexos: list[str]


def _resumo_regra(r: LegalRule) -> RegraResumo:
    return RegraResumo(
        id=r.id,
        slug=r.slug,
        versao=r.versao,
        anexo=r.anexo,
        item=r.item,
        descricao_legal=r.descricao_legal[:300],
        dispositivo_legal=r.dispositivo_legal,
        tipo_tratamento=r.tipo_tratamento,
        tipo_codigo=r.tipo_codigo,
        cst_ibs_cbs=r.cst_ibs_cbs,
        cclasstrib=r.cclasstrib,
        status=r.status,
        origem=r.origem,
        total_codigos=len((r.abrangencia or {}).get("codigos", [])),
        total_condicoes=len(r.condicoes or []),
        erros=len(r.erros_validacao or []),
        avisos=len(r.avisos or []),
        divergencias=len(exige_justificativa(r.avisos or [])),
        controverso=r.controverso,
        updated_at=r.updated_at,
    )


class CodigoNoUso(BaseModel):
    codigo: str
    situacao: str  # confirmado | em_confirmacao | divergem | outro | sem_decisao
    decisoes: int
    faltam: int
    cclasstrib: str | None
    ramo: str | None
    itens: int = 0


class RegraNoUso(BaseModel):
    regra_id: uuid.UUID
    titulo: str
    descricao: str
    cclasstrib: str | None
    situacao: str  # confirmada | em_confirmacao
    codigos_confirmados: int
    codigos: list[CodigoNoUso]


class DivergenciaNoUso(BaseModel):
    regra_id: uuid.UUID
    titulo: str
    descricao: str
    cclasstrib: str | None
    mensagens: list[str]
    gravidade: str
    itens: int
    resolvida: bool
    codigos_resolvidos: int
    codigos: list[CodigoNoUso]


class ResumoRegras(BaseModel):
    organizacao_selecionada: bool
    total_regras: int
    aprovadas: int
    total_divergencias: int
    decisoes: int
    regras_em_uso: list[RegraNoUso]
    divergencias: list[DivergenciaNoUso]
    divergencias_sem_itens: int


@router.get("/regras/resumo", response_model=ResumoRegras)
async def resumo_regras(principal: SuperAdminDep, org_id: uuid.UUID | None = None) -> Any:
    """Regras pelo uso (ADR 0028): confirmadas pelas decisões de pessoas e divergências que tocam itens.

    Lê uma organização por vez (a escolhida aqui ou a da sessão): as decisões nunca se misturam entre
    organizações. Devolve só agregados (códigos, cClassTrib e contagens), sem produtos nem empresas."""
    org = org_id or principal.org_id
    ctx = TenantContext(org_id=org, user_id=principal.user_id, platform_admin=principal.platform_admin)
    async with tenant_session(ctx) as session:
        return await session.run_sync(lambda s: resumo_pelo_uso(s, org is not None))


@router.get("/regras", response_model=PaginaRegras)
async def listar_regras(
    principal: SuperAdminDep,
    session: RefSessionDep,
    status: str | None = None,
    anexo: str | None = None,
    busca: str | None = Query(None, max_length=100),
    com_avisos: bool = False,
    com_divergencias: bool = False,
    pagina: int = Query(1, ge=1),
    por_pagina: int = Query(50, le=500),
) -> PaginaRegras:
    q = select(LegalRule)
    if status:
        q = q.where(LegalRule.status == status)
    else:
        q = q.where(LegalRule.status.notin_([StatusRegra.SUBSTITUIDA]))
    if anexo:
        q = q.where(LegalRule.anexo == anexo)
    if busca:
        t = f"%{busca}%"
        q = q.where(
            or_(
                LegalRule.descricao_legal.ilike(t),
                LegalRule.slug.ilike(t),
                LegalRule.cclasstrib.ilike(t),
                LegalRule.dispositivo_legal.ilike(t),
            )
        )
    if com_avisos:
        q = q.where(func.jsonb_array_length(LegalRule.avisos) > 0)
    if com_divergencias:
        q = q.where(
            or_(
                LegalRule.avisos.contains([{"divergencia": True, "gravidade": "alta"}]),
                LegalRule.avisos.contains([{"divergencia": True, "gravidade": "media"}]),
            )
        )
    total = await session.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = await session.scalars(
        q.order_by(LegalRule.anexo.nulls_last(), LegalRule.slug).offset((pagina - 1) * por_pagina).limit(por_pagina)
    )
    por_status = dict((await session.execute(select(LegalRule.status, func.count()).group_by(LegalRule.status))).all())
    anexos = sorted(
        {a for a in await session.scalars(select(LegalRule.anexo).distinct()) if a}, key=lambda a: (len(a), a)
    )
    return PaginaRegras(itens=[_resumo_regra(r) for r in rows], total=total, por_status=por_status, anexos=anexos)


class RegraDetalhe(BaseModel):
    regra: dict[str, Any]
    texto_legal: dict[str, Any] | None
    cclasstrib: dict[str, Any] | None
    codigos: list[dict[str, Any]]
    excecoes: list[dict[str, Any]]
    versao_anterior: dict[str, Any] | None
    catalogo_atributos: list[dict[str, Any]]
    # Descrição oficial dos códigos citados nas divergências (para a tela de revisão).
    descricoes: dict[str, str] = {}


def _regra_dict(r: LegalRule) -> dict[str, Any]:
    d = {c: getattr(r, c) for c in LegalRule.__table__.columns.keys()}
    for k, v in d.items():
        if isinstance(v, uuid.UUID | datetime | date):
            d[k] = str(v) if isinstance(v, uuid.UUID) else v.isoformat()
    return d


def _descricoes(sess: Session, tipo: str | None, codigos: list[str]) -> dict[str, str]:
    if not codigos or not tipo:
        return {}
    modelo = NbsNode if tipo == "nbs" else NcmNode
    v = sess.scalar(select(RefVersion.id).where(RefVersion.fonte == tipo, RefVersion.status == StatusVersao.ATIVA))
    if v is None:
        return {}
    return dict(
        sess.execute(
            select(modelo.codigo, modelo.descricao_completa).where(modelo.version_id == v, modelo.codigo.in_(codigos))
        ).all()
    )


@router.get("/regras/{regra_id}", response_model=RegraDetalhe)
async def detalhe_regra(regra_id: uuid.UUID, principal: SuperAdminDep, session: RefSessionDep) -> RegraDetalhe:
    r = await session.get(LegalRule, regra_id)
    if r is None:
        raise NaoEncontrado("Regra não encontrada.")
    texto = None
    if r.provision_id:
        p = await session.get(LegalProvision, r.provision_id)
        if p:
            texto = {"anexo": p.anexo, "item": p.item, "titulo_anexo": p.titulo_anexo, "texto": p.texto}
    cct = None
    if r.cclasstrib:
        v = await session.scalar(
            select(RefVersion.id).where(RefVersion.fonte == "cclasstrib", RefVersion.status == StatusVersao.ATIVA)
        )
        c = (
            await session.scalar(
                select(CClassTribCode).where(CClassTribCode.version_id == v, CClassTribCode.codigo == r.cclasstrib)
            )
            if v
            else None
        )
        if c:
            cct = {
                "codigo": c.codigo,
                "cst": c.cst,
                "nome": c.nome,
                "perc_red_ibs": float(c.perc_red_ibs or 0),
                "perc_red_cbs": float(c.perc_red_cbs or 0),
                "url_legislacao": c.url_legislacao,
                "texto_regulamento": c.texto_regulamento_cbs,
            }
    cods = [c["codigo"] for c in (r.abrangencia or {}).get("codigos", [])]
    excs = [e["codigo"] for e in r.excecoes or [] if e.get("codigo")]
    divs = [c for a in r.avisos or [] if a.get("divergencia") for c in a.get("codigos", [])]
    desc = await session.run_sync(lambda s: _descricoes(s, r.tipo_codigo, cods[:500] + excs[:200] + divs[:1500]))
    anterior = await session.get(LegalRule, r.substitui_id) if r.substitui_id else None
    catalogo = await session.scalars(select(ConditionAttribute).order_by(ConditionAttribute.chave))
    return RegraDetalhe(
        regra=_regra_dict(r),
        texto_legal=texto,
        cclasstrib=cct,
        codigos=[
            {"codigo": c, "formatado": formatar_codigo(r.tipo_codigo, c), "descricao": desc.get(c)} for c in cods[:500]
        ],
        excecoes=[
            {
                **e,
                "formatado": formatar_codigo(r.tipo_codigo, e["codigo"]) if e.get("codigo") else None,
                "descricao_oficial": desc.get(e.get("codigo", "")),
            }
            for e in r.excecoes or []
        ],
        versao_anterior=_regra_dict(anterior) if anterior else None,
        catalogo_atributos=[
            {"chave": a.chave, "fonte": a.fonte, "pergunta": a.pergunta, "descricao": a.descricao} for a in catalogo
        ],
        descricoes={c: desc[c] for c in divs if c in desc},
    )


class CondicaoIn(BaseModel):
    atributo: str = Field(pattern=r"^[a-z][a-z0-9_]{1,59}$")
    fonte: str = Field(pattern="^(item|empresa|operacao)$")
    deve_ser: str = Field(min_length=1, max_length=60)
    pergunta: str = Field(min_length=5, max_length=300)
    trecho_legal: str | None = Field(None, max_length=2000)


class ExcecaoIn(BaseModel):
    codigo: str | None = Field(None, pattern=r"^\d{2,9}$")
    descricao: str | None = Field(None, max_length=500)
    trecho_legal: str | None = Field(None, max_length=2000)


class RegraPatch(BaseModel):
    condicoes: list[CondicaoIn] | None = None
    excecoes: list[ExcecaoIn] | None = None
    cst_ibs_cbs: str | None = Field(None, pattern=r"^\d{3}$")
    cclasstrib: str | None = Field(None, pattern=r"^\d{6}$")
    tipo_tratamento: str | None = None
    codigos: list[str] | None = None
    controverso: bool | None = None
    nota_controversia: str | None = Field(None, max_length=2000)
    vigencia_inicio: date | None = None
    vigencia_fim: date | None = None
    dispositivo_legal: str | None = Field(None, max_length=500)


@router.patch("/regras/{regra_id}", response_model=RegraDetalhe)
async def editar_regra(
    regra_id: uuid.UUID, dados: RegraPatch, principal: SuperAdminDep, session: RefSessionDep
) -> RegraDetalhe:
    r = await session.get(LegalRule, regra_id)
    if r is None:
        raise NaoEncontrado("Regra não encontrada.")
    if r.status == StatusRegra.APROVADA:
        # Regra aprovada nunca é alterada: cria-se uma nova versão pendente.
        nova = LegalRule(
            **{
                c: getattr(r, c)
                for c in LegalRule.__table__.columns.keys()
                if c
                not in (
                    "id",
                    "versao",
                    "status",
                    "revisado_por",
                    "revisado_por_email",
                    "revisado_em",
                    "nota_revisao",
                    "created_at",
                    "updated_at",
                    "substitui_id",
                )
            }
        )
        maxv = await session.scalar(select(func.max(LegalRule.versao)).where(LegalRule.slug == r.slug))
        nova.versao, nova.status, nova.substitui_id, nova.origem = (
            (maxv or 1) + 1,
            StatusRegra.PENDENTE_REVISAO,
            r.id,
            OrigemRegra.MANUAL,
        )
        session.add(nova)
        await session.flush()
        r = nova
    elif r.status not in (StatusRegra.PENDENTE_REVISAO, StatusRegra.INVALIDA):
        raise Conflito("Somente regras pendentes, inválidas ou aprovadas (gerando nova versão) podem ser editadas.")
    mudou = dados.model_dump(exclude_unset=True, mode="json")
    if dados.condicoes is not None:
        r.condicoes = [c.model_dump() for c in dados.condicoes]
    if dados.excecoes is not None:
        r.excecoes = [{k: v for k, v in e.model_dump().items() if v} for e in dados.excecoes]
    if dados.codigos is not None:
        from app.rules.schema import nivel_por_tamanho

        r.abrangencia = {
            **(r.abrangencia or {}),
            "codigos": [
                {"codigo": c, "nivel": nivel_por_tamanho(r.tipo_codigo or "ncm", c)}
                for c in dict.fromkeys(dados.codigos)
            ],
        }
    for campo in (
        "cst_ibs_cbs",
        "cclasstrib",
        "tipo_tratamento",
        "controverso",
        "nota_controversia",
        "vigencia_inicio",
        "vigencia_fim",
        "dispositivo_legal",
    ):
        if campo in mudou:
            setattr(r, campo, getattr(dados, campo))
    await session.flush()
    await session.run_sync(_revalidar, r.id)
    await registrar(
        session,
        principal,
        Acao.REGRA_EDITADA,
        entidade="regra",
        entidade_id=r.id,
        detalhes={"slug": r.slug, "versao": r.versao, "campos": sorted(mudou)},
        plataforma=True,
    )
    await session.flush()
    return await detalhe_regra(r.id, principal, session)


def _revalidar(s: Session, regra_id: uuid.UUID) -> None:
    regra = s.get(LegalRule, regra_id)
    if regra is not None:
        sincronizar_codigos(s, regra)
        validar_regra(s, regra)


class RevisaoRegraIn(BaseModel):
    nota: str | None = Field(None, max_length=2000)


async def _aprovar_regra(
    session: Any, r: LegalRule, principal: Principal, nota: str | None, ctx: ContextoDivergencias | None = None
) -> None:
    await session.run_sync(lambda s: validar_regra(s, s.get(LegalRule, r.id), ctx))
    if r.status != StatusRegra.PENDENTE_REVISAO or r.erros_validacao:
        raise Conflito(f"A regra {r.slug} tem erros de validação e não pode ser aprovada.", detalhes=r.erros_validacao)
    divergencias = exige_justificativa(r.avisos or [])
    if divergencias and len((nota or "").strip()) < 15:
        raise Conflito(
            f"A regra tem {len(divergencias)} divergência(s) com a lei ou a tabela oficial. Corrija-as ou explique "
            "na nota da revisão (mínimo de 15 caracteres) por que a regra está correta assim.",
            detalhes=[{"codigo": a["codigo"], "mensagem": a["mensagem"]} for a in divergencias],
        )
    catalogo = set(await session.scalars(select(ConditionAttribute.chave)))
    for c in r.condicoes or []:
        if c["atributo"] not in catalogo:
            session.add(
                ConditionAttribute(
                    chave=c["atributo"],
                    fonte=c.get("fonte", "item"),
                    pergunta=c["pergunta"],
                    descricao=c.get("trecho_legal") or c["pergunta"],
                    valores=[],
                )
            )
            catalogo.add(c["atributo"])
    r.status = StatusRegra.APROVADA
    r.revisado_por, r.revisado_por_email, r.revisado_em, r.nota_revisao = (
        principal.user_id,
        principal.email,
        datetime.now(UTC),
        nota,
    )
    await session.execute(
        update(LegalRule)
        .where(LegalRule.slug == r.slug, LegalRule.id != r.id, LegalRule.status == StatusRegra.APROVADA)
        .values(status=StatusRegra.SUBSTITUIDA)
    )
    await registrar(
        session,
        principal,
        Acao.REGRA_REVISADA,
        entidade="regra",
        entidade_id=r.id,
        detalhes={"slug": r.slug, "versao": r.versao, "decisao": "aprovada", "nota": nota},
        plataforma=True,
    )


@router.post("/regras/{regra_id}/aprovar", response_model=RegraResumo)
async def aprovar_regra(
    regra_id: uuid.UUID, dados: RevisaoRegraIn, principal: SuperAdminDep, session: RefSessionDep
) -> RegraResumo:
    r = await session.get(LegalRule, regra_id)
    if r is None:
        raise NaoEncontrado("Regra não encontrada.")
    await _aprovar_regra(session, r, principal, dados.nota)
    return _resumo_regra(r)


@router.post("/regras/{regra_id}/rejeitar", response_model=RegraResumo)
async def rejeitar_regra(
    regra_id: uuid.UUID, dados: RevisaoRegraIn, principal: SuperAdminDep, session: RefSessionDep
) -> RegraResumo:
    r = await session.get(LegalRule, regra_id)
    if r is None:
        raise NaoEncontrado("Regra não encontrada.")
    if r.status not in (StatusRegra.PENDENTE_REVISAO, StatusRegra.INVALIDA, StatusRegra.APROVADA):
        raise Conflito("Esta regra não pode ser rejeitada.")
    r.status = StatusRegra.REJEITADA
    r.revisado_por, r.revisado_por_email, r.revisado_em, r.nota_revisao = (
        principal.user_id,
        principal.email,
        datetime.now(UTC),
        dados.nota,
    )
    await registrar(
        session,
        principal,
        Acao.REGRA_REVISADA,
        entidade="regra",
        entidade_id=r.id,
        detalhes={"slug": r.slug, "decisao": "rejeitada", "nota": dados.nota},
        plataforma=True,
    )
    return _resumo_regra(r)


class LoteRegrasIn(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=2000)
    confirmar: bool = False
    nota: str | None = None


class LoteRegrasOut(BaseModel):
    aprovaveis: int
    aprovadas: int
    bloqueadas: list[dict[str, Any]]


@router.post("/regras/aprovar-lote", response_model=LoteRegrasOut)
async def aprovar_regras_lote(dados: LoteRegrasIn, principal: SuperAdminDep, session: RefSessionDep) -> LoteRegrasOut:
    regras = list(await session.scalars(select(LegalRule).where(LegalRule.id.in_(dados.ids))))
    aprovaveis = [
        r
        for r in regras
        if r.status == StatusRegra.PENDENTE_REVISAO
        and not r.erros_validacao
        and not any(a.get("codigo") == "CONDICOES_TEXTUAIS" for a in r.avisos or [])
        and not exige_justificativa(r.avisos or [])
    ]
    bloqueadas = [
        {
            "id": str(r.id),
            "slug": r.slug,
            "motivo": "erros de validação"
            if r.erros_validacao
            else (
                "divergências com a lei (revise individualmente)"
                if exige_justificativa(r.avisos or [])
                else ("condições textuais não estruturadas" if r.status == StatusRegra.PENDENTE_REVISAO else r.status)
            ),
        }
        for r in regras
        if r not in aprovaveis
    ]
    if not dados.confirmar:
        return LoteRegrasOut(aprovaveis=len(aprovaveis), aprovadas=0, bloqueadas=bloqueadas)
    ctx = await session.run_sync(ContextoDivergencias) if aprovaveis else None
    for r in aprovaveis:
        await _aprovar_regra(session, r, principal, dados.nota or "Aprovação em lote", ctx)
    return LoteRegrasOut(aprovaveis=len(aprovaveis), aprovadas=len(aprovaveis), bloqueadas=bloqueadas)


class IdsIn(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=1000)


@router.post("/regras/sugerir-condicoes", response_model=TarefaOut, status_code=202)
async def sugerir_condicoes(dados: IdsIn, principal: SuperAdminDep, session: RefSessionDep) -> TarefaOut:
    r = celery_app.send_task(
        "referencia.sugerir_condicoes", args=[[str(i) for i in dados.ids], principal.email], queue="reference"
    )
    return TarefaOut(tarefa_id=r.id, mensagem=f"Sugestão de condições iniciada para {len(dados.ids)} regras.")


@router.post("/regras/regenerar", response_model=dict[str, Any])
async def regenerar_regras(principal: SuperAdminDep, session: RefSessionDep) -> dict[str, Any]:
    from starlette.concurrency import run_in_threadpool

    from app.reference.service import pos_importacao

    return await run_in_threadpool(pos_importacao, "cclasstrib")


@router.get("/regras-yaml", response_class=PlainTextResponse)
async def exportar_yaml(principal: SuperAdminDep, session: RefSessionDep, status: str | None = None) -> str:
    q = select(LegalRule).where(LegalRule.status != StatusRegra.SUBSTITUIDA).order_by(LegalRule.slug)
    if status:
        q = q.where(LegalRule.status == status)
    return para_yaml([regra_para_declarativa(r) for r in await session.scalars(q)])


@router.post("/regras-yaml", response_model=dict[str, int])
async def importar_yaml(
    principal: SuperAdminDep, session: RefSessionDep, arquivo: Annotated[UploadFile, File()]
) -> dict[str, int]:
    try:
        regras = de_yaml((await arquivo.read(20 * 1024 * 1024)).decode("utf-8"))
    except Exception as e:
        raise AppError(f"Arquivo YAML inválido: {str(e)[:300]}") from e
    n = 0
    for d in regras:
        maxv = await session.scalar(select(func.max(LegalRule.versao)).where(LegalRule.slug == d.id))
        anterior = await session.scalar(
            select(LegalRule).where(LegalRule.slug == d.id, LegalRule.status == StatusRegra.APROVADA)
        )
        r = LegalRule(
            slug=d.id,
            versao=(maxv or 0) + 1,
            anexo=d.anexo,
            item=d.item,
            titulo_anexo=d.titulo_anexo,
            descricao_legal=d.descricao_legal,
            dispositivo_legal=d.dispositivo_legal,
            tipo_tratamento=d.tipo_tratamento,
            tipo_codigo=d.abrangencia.tipo_codigo,
            abrangencia={
                "universal": d.abrangencia.universal,
                "codigos": [c.model_dump() for c in d.abrangencia.codigos],
            },
            excecoes=[e.model_dump(exclude_none=True) for e in d.excecoes],
            condicoes=[c.model_dump(exclude_none=True) for c in d.condicoes],
            cst_ibs_cbs=d.cst_ibs_cbs,
            cclasstrib=d.cclasstrib,
            vigencia_inicio=d.vigencia.get("inicio"),
            vigencia_fim=d.vigencia.get("fim"),
            prioridade=d.prioridade,
            controverso=d.controverso,
            nota_controversia=d.nota_controversia,
            status=StatusRegra.PENDENTE_REVISAO,
            origem=OrigemRegra.YAML,
            substitui_id=anterior.id if anterior else None,
        )
        session.add(r)
        await session.flush()
        await session.run_sync(_revalidar, r.id)
        n += 1
    await registrar(session, principal, Acao.REGRA_EDITADA, detalhes={"importacao_yaml": n}, plataforma=True)
    return {"importadas": n}


@router.get("/referencia/validacao", response_model=dict[str, Any])
async def relatorio_validacao(principal: SuperAdminDep, session: RefSessionDep) -> dict[str, Any]:
    """Regras (inclusive aprovadas) que citam códigos inexistentes ou extintos na tabela vigente."""
    rows = await session.execute(
        text(
            "SELECT id, slug, versao, status, e->>'mensagem' AS mensagem FROM legal_rules, "
            "jsonb_array_elements(erros_validacao) e WHERE e->>'codigo' = 'CODIGO_INEXISTENTE' "
            "AND status <> 'substituida' ORDER BY slug"
        )
    )
    return {"codigos_inexistentes": [dict(r._mapping) | {"id": str(r.id)} for r in rows]}


# =================================================================== catálogo de atributos ==
class AtributoIn(BaseModel):
    chave: str = Field(pattern=r"^[a-z][a-z0-9_]{1,59}$")
    fonte: str = Field(pattern="^(item|empresa|operacao)$")
    descricao: str = Field(min_length=3, max_length=500)
    pergunta: str = Field(min_length=5, max_length=300)
    valores: list[str] = Field(default_factory=list)


@router.get("/atributos", response_model=list[AtributoIn])
async def listar_atributos(principal: PrincipalDep, session: SessionDep) -> list[AtributoIn]:
    return [
        AtributoIn(
            chave=a.chave, fonte=a.fonte, descricao=a.descricao, pergunta=a.pergunta, valores=list(a.valores or [])
        )
        for a in await session.scalars(select(ConditionAttribute).order_by(ConditionAttribute.chave))
    ]


@router.post("/atributos", response_model=AtributoIn, status_code=201)
async def criar_atributo(dados: AtributoIn, principal: SuperAdminDep, session: RefSessionDep) -> AtributoIn:
    if await session.get(ConditionAttribute, dados.chave):
        raise Conflito("Já existe um atributo com essa chave.")
    session.add(ConditionAttribute(**dados.model_dump()))
    return dados


# ============================================================ organizações da plataforma ==
class OrgIn(BaseModel):
    nome: str = Field(min_length=2, max_length=200)
    tipo: TipoOrganizacao
    admin_nome: str = Field(min_length=2, max_length=200)
    admin_email: EmailStr


class OrgOut(BaseModel):
    id: uuid.UUID
    nome: str
    tipo: str
    ativo: bool
    created_at: datetime
    admin_email: str | None = None
    senha_temporaria: str | None = None


@router.get("/plataforma/organizacoes", response_model=list[OrgOut])
async def listar_orgs(principal: SuperAdminDep) -> list[OrgOut]:
    async with tenant_session(principal.ctx) as s:
        return [
            OrgOut(id=o.id, nome=o.nome, tipo=o.tipo, ativo=o.ativo, created_at=o.created_at)
            for o in await s.scalars(select(Organization).order_by(Organization.nome))
        ]


@router.post("/plataforma/organizacoes", response_model=OrgOut, status_code=201)
async def criar_org(dados: OrgIn, principal: SuperAdminDep) -> OrgOut:
    async with tenant_session(principal.ctx) as s:
        org = Organization(nome=dados.nome, tipo=dados.tipo.value)
        s.add(org)
        await s.flush()
        org_id = org.id
    ctx = TenantContext(org_id=org_id, user_id=principal.user_id, platform_admin=True)
    senha = None
    async with tenant_session(ctx) as s:
        s.add(OrgSettings(org_id=org_id))
        existente = await s.scalar(text("SELECT sys_usuario_por_email(:e)"), {"e": dados.admin_email.lower()})
        if existente is None:
            senha = gerar_senha_temporaria()
            u = User(email=dados.admin_email.lower(), nome=dados.admin_nome, password_hash=hash_senha(senha))
            s.add(u)
            await s.flush()
            existente = u.id
        s.add(Membership(org_id=org_id, user_id=existente, papel="administrador"))
        await registrar(
            s,
            principal,
            Acao.ORGANIZACAO,
            entidade="organizacao",
            entidade_id=org_id,
            detalhes={"operacao": "criada", "nome": dados.nome},
            org_id=org_id,
        )
        o = await s.get(Organization, org_id)
        assert o is not None
        return OrgOut(
            id=o.id,
            nome=o.nome,
            tipo=o.tipo,
            ativo=o.ativo,
            created_at=o.created_at,
            admin_email=dados.admin_email,
            senha_temporaria=senha,
        )


@router.delete("/plataforma/organizacoes/{org_id}", status_code=204)
async def excluir_org(org_id: uuid.UUID, principal: SuperAdminDep, confirmar_nome: str = Query(...)) -> None:
    """Exclusão definitiva dos dados da organização (LGPD). Exige digitar o nome da organização."""
    async with tenant_session(principal.ctx) as s:
        org = await s.get(Organization, org_id)
        if org is None:
            raise NaoEncontrado("Organização não encontrada.")
        if confirmar_nome.strip() != org.nome:
            raise Conflito("O nome digitado não confere com o da organização.")
        await registrar(
            s,
            principal,
            Acao.DADOS_EXCLUIDOS,
            entidade="organizacao",
            entidade_id=org_id,
            detalhes={"nome": org.nome},
            plataforma=True,
        )
        await s.delete(org)
