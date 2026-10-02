"""Upload de planilhas, criação e acompanhamento de auditorias, e consulta de itens."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any

import orjson
from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse
from starlette.concurrency import run_in_threadpool

from app.api.orgs import empresas_permitidas, garantir_acesso_empresa, gasto_mes
from app.config import get_settings
from app.core.audit_trail import Acao, registrar
from app.core.codes import formatar_codigo
from app.core.deps import Principal, SessionDep, exigir
from app.core.errors import AppError, Conflito, NaoEncontrado
from app.core.rbac import Perm
from app.core.redis import redis_async
from app.events.bus import canal_auditoria
from app.ingest import estimate
from app.ingest.mapping import CAMPOS, assinatura_colunas, sugerir_mapeamento, validar_mapeamento
from app.ingest.reader import ArquivoInvalido, ler_planilha
from app.llm import catalogo
from app.llm.gateway import ChaveAPIAusente, verificar_chaves
from app.models import (
    Audit,
    AuditItem,
    CClassTribCode,
    Company,
    ItemCandidate,
    ItemReview,
    LegalProvision,
    LegalRule,
    LlmCall,
    MappingTemplate,
    OrgSettings,
    RefSnapshot,
    UploadedFile,
)
from app.models.enums import STATUS_REVISAVEIS, StatusAuditoria, StatusRevisao
from app.pipeline.reasons import TEXTOS
from app.reference.snapshot import criar_ou_obter
from app.storage import files
from app.worker.celery_app import celery_app

router = APIRouter(tags=["auditorias"])

Ver = Annotated[Principal, Depends(exigir(Perm.VER))]
Enviar = Annotated[Principal, Depends(exigir(Perm.ENVIAR_PLANILHA))]
Criar = Annotated[Principal, Depends(exigir(Perm.CRIAR_AUDITORIA))]


# ================================================================================ upload ==
class CampoOut(BaseModel):
    chave: str
    rotulo: str
    obrigatorio: bool
    descricao: str


class ModeloMapeamentoOut(BaseModel):
    id: uuid.UUID
    nome: str
    sistema_origem: str | None
    mapeamento: dict[str, Any]
    compativel: bool


class UploadOut(BaseModel):
    arquivo_id: uuid.UUID
    nome: str
    formato: str
    encoding: str | None
    separador: str | None
    planilha: str | None
    planilhas: list[str]
    linha_cabecalho: int
    total_linhas: int
    colunas: list[str]
    amostra: list[list[str]]
    mapeamento_sugerido: dict[str, str | None]
    campos: list[CampoOut]
    modelos: list[ModeloMapeamentoOut]


async def _modelos(session: AsyncSession, company_id: uuid.UUID, colunas: list[str]) -> list[ModeloMapeamentoOut]:
    assinatura = assinatura_colunas(colunas)
    rows = await session.scalars(
        select(MappingTemplate)
        .where((MappingTemplate.company_id == company_id) | (MappingTemplate.company_id.is_(None)))
        .order_by(MappingTemplate.created_at.desc())
    )
    saida = []
    for m in rows:
        compat = all((c in colunas) for c in m.mapeamento.values() if c)
        saida.append(
            ModeloMapeamentoOut(
                id=m.id,
                nome=m.nome,
                sistema_origem=m.sistema_origem,
                mapeamento=m.mapeamento,
                compativel=compat or m.assinatura_colunas == assinatura,
            )
        )
    return saida


def _ler(dados: bytes, nome: str, planilha: str | None, cab: int | None) -> Any:
    return ler_planilha(dados, nome, planilha, cab, get_settings().upload_max_linhas)


@router.post("/uploads", response_model=UploadOut, status_code=201)
async def enviar_planilha(
    principal: Enviar,
    session: SessionDep,
    arquivo: Annotated[UploadFile, File()],
    company_id: Annotated[uuid.UUID, Form()],
) -> UploadOut:
    s = get_settings()
    await garantir_acesso_empresa(session, principal, company_id)
    dados = await arquivo.read(s.upload_max_mb * 1024 * 1024 + 1)
    if len(dados) > s.upload_max_mb * 1024 * 1024:
        raise AppError(
            f"O arquivo passa do limite de {s.upload_max_mb} MB.",
            acao="Divida a planilha em partes menores.",
            status_code=413,
            codigo="arquivo_grande",
        )
    if not dados:
        raise AppError("O arquivo está vazio.")
    nome = (arquivo.filename or "planilha")[:300]
    try:
        p = await run_in_threadpool(_ler, dados, nome, None, None)
    except ArquivoInvalido as e:
        raise AppError(e.mensagem, acao=e.acao, codigo="arquivo_invalido") from e
    cfg = await session.get(OrgSettings, principal.org_id)
    retencao = cfg.retencao_arquivos_dias if cfg else s.retencao_arquivos_dias_padrao
    rel = files.salvar(f"uploads/{principal.org_id}", dados, p.formato)
    up = UploadedFile(
        org_id=principal.org_id,
        company_id=company_id,
        nome_original=nome,
        storage_path=rel,
        sha256=files.sha256(dados),
        tamanho_bytes=len(dados),
        formato=p.formato,
        encoding=p.encoding,
        separador=p.separador,
        planilha=p.planilha,
        planilhas=p.planilhas,
        linha_cabecalho=p.linha_cabecalho,
        total_linhas=p.total,
        colunas=p.colunas,
        amostra=p.linhas[:20],
        enviado_por=principal.user_id,
        expurgar_em=(date.today() + timedelta(days=retencao)) if retencao else None,
    )
    session.add(up)
    await session.flush()
    await registrar(
        session,
        principal,
        Acao.UPLOAD,
        entidade="arquivo",
        entidade_id=up.id,
        detalhes={"nome": nome, "linhas": p.total, "formato": p.formato, "empresa": str(company_id)},
    )
    return UploadOut(
        arquivo_id=up.id,
        nome=nome,
        formato=p.formato,
        encoding=p.encoding,
        separador=p.separador,
        planilha=p.planilha,
        planilhas=p.planilhas,
        linha_cabecalho=p.linha_cabecalho,
        total_linhas=p.total,
        colunas=p.colunas,
        amostra=p.linhas[:20],
        mapeamento_sugerido=sugerir_mapeamento(p.colunas, p.linhas),
        campos=[
            CampoOut(chave=c.chave, rotulo=c.rotulo, obrigatorio=c.obrigatorio, descricao=c.descricao) for c in CAMPOS
        ],
        modelos=await _modelos(session, company_id, p.colunas),
    )


class ReleituraIn(BaseModel):
    planilha: str | None = None
    linha_cabecalho: int | None = Field(None, ge=0, le=50)


@router.post("/uploads/{arquivo_id}/reler", response_model=UploadOut)
async def reler_planilha(
    arquivo_id: uuid.UUID, dados_in: ReleituraIn, principal: Enviar, session: SessionDep
) -> UploadOut:
    up = await session.get(UploadedFile, arquivo_id)
    if up is None or up.storage_path is None:
        raise NaoEncontrado("Arquivo não encontrado.")
    dados = files.ler(up.storage_path)
    try:
        p = await run_in_threadpool(_ler, dados, up.nome_original, dados_in.planilha, dados_in.linha_cabecalho)
    except ArquivoInvalido as e:
        raise AppError(e.mensagem, acao=e.acao) from e
    up.planilha, up.linha_cabecalho, up.total_linhas = p.planilha, p.linha_cabecalho, p.total
    up.colunas, up.amostra = p.colunas, p.linhas[:20]
    return UploadOut(
        arquivo_id=up.id,
        nome=up.nome_original,
        formato=p.formato,
        encoding=p.encoding,
        separador=p.separador,
        planilha=p.planilha,
        planilhas=p.planilhas,
        linha_cabecalho=p.linha_cabecalho,
        total_linhas=p.total,
        colunas=p.colunas,
        amostra=p.linhas[:20],
        mapeamento_sugerido=sugerir_mapeamento(p.colunas, p.linhas),
        campos=[
            CampoOut(chave=c.chave, rotulo=c.rotulo, obrigatorio=c.obrigatorio, descricao=c.descricao) for c in CAMPOS
        ],
        modelos=await _modelos(session, up.company_id, p.colunas),
    )


# ============================================================================= auditorias ==
class AuditoriaIn(BaseModel):
    company_id: uuid.UUID
    arquivo_id: uuid.UUID
    nome: str = Field(min_length=2, max_length=200)
    mapeamento: dict[str, str | None]
    data_referencia: date | None = None
    contexto_operacao: dict[str, str] = Field(default_factory=dict)
    salvar_modelo: bool = False
    nome_modelo: str | None = Field(None, max_length=120)
    sistema_origem: str | None = Field(None, max_length=120)


class AuditoriaResumo(BaseModel):
    id: uuid.UUID
    nome: str
    company_id: uuid.UUID
    empresa: str
    status: str
    modo: str | None
    total_itens: int
    contadores: dict[str, Any]
    custo_usd: float
    created_at: datetime
    iniciado_em: datetime | None
    concluido_em: datetime | None
    pendentes_revisao: int = 0


class AuditoriaOut(AuditoriaResumo):
    data_referencia: date
    arquivo: str | None
    mapeamento: dict[str, Any]
    problemas_resumo: dict[str, Any]
    estimativa: dict[str, Any]
    tokens: dict[str, Any]
    configuracao: dict[str, Any]
    erro: str | None
    snapshot: dict[str, Any] | None
    textos_motivos: dict[str, list[str]]
    orcamento: dict[str, Any]


def _resumo(a: Audit, empresa: str, pendentes: int = 0) -> dict[str, Any]:
    return {
        "id": a.id,
        "nome": a.nome,
        "company_id": a.company_id,
        "empresa": empresa,
        "status": a.status,
        "modo": a.modo,
        "total_itens": a.total_itens,
        "contadores": a.contadores or {},
        "custo_usd": float(a.custo_usd or 0),
        "created_at": a.created_at,
        "iniciado_em": a.iniciado_em,
        "concluido_em": a.concluido_em,
        "pendentes_revisao": pendentes,
    }


async def _carregar_auditoria(session: AsyncSession, principal: Principal, audit_id: uuid.UUID) -> Audit:
    a = await session.get(Audit, audit_id)
    if a is None:
        raise NaoEncontrado("Auditoria não encontrada.")
    await garantir_acesso_empresa(session, principal, a.company_id)
    return a


# Estados em que a auditoria pode ser iniciada ou retomada (com os modelos escolhidos agora).
PODE_INICIAR = (
    StatusAuditoria.PRONTA,
    StatusAuditoria.PAUSADA_ORCAMENTO,
    StatusAuditoria.PAUSADA_IA,
    StatusAuditoria.FALHOU,
)


def estimativa_atual(a: Audit) -> dict[str, Any]:
    """Antes de iniciar, a estimativa acompanha os modelos escolhidos agora em "Modelos de IA"."""
    est = a.estimativa or {}
    previsao = (a.problemas_resumo or {}).get("previsao_ia")
    if a.status not in PODE_INICIAR:
        return est
    if not previsao or a.iniciado_em is not None:
        return est
    taxa = est.get("taxa_escalonamento") or (est.get("tempo_real") or {}).get("taxa_escalonamento") or 0.4
    limite = est.get("limite_lote") or (est.get("tempo_real") or {}).get("limite_lote") or 200
    return estimate.estimativas(previsao, float(taxa), int(limite))


async def _saida(session: AsyncSession, a: Audit, principal: Principal) -> AuditoriaOut:
    empresa = await session.get(Company, a.company_id)
    arquivo = await session.get(UploadedFile, a.file_id) if a.file_id else None
    snap = await session.get(RefSnapshot, a.snapshot_id) if a.snapshot_id else None
    pend = await session.scalar(
        select(func.count())
        .select_from(AuditItem)
        .where(
            AuditItem.audit_id == a.id,
            AuditItem.ignorado.is_(False),
            AuditItem.revisao_status == StatusRevisao.PENDENTE,
            AuditItem.status.in_(list(STATUS_REVISAVEIS)),
        )
    )
    cfg = await session.get(OrgSettings, a.org_id)
    return AuditoriaOut(
        **_resumo(a, empresa.razao_social if empresa else "", pend or 0),
        data_referencia=a.data_referencia,
        arquivo=arquivo.nome_original if arquivo else None,
        mapeamento=a.mapeamento,
        problemas_resumo=a.problemas_resumo or {},
        estimativa=await run_in_threadpool(estimativa_atual, a),
        tokens=a.tokens or {},
        configuracao=a.configuracao or {},
        erro=a.erro,
        snapshot={
            "id": str(snap.id),
            "versoes": snap.versoes,
            "completude": snap.completude,
            "criado_em": snap.created_at.isoformat(),
        }
        if snap
        else None,
        textos_motivos={k: list(v) for k, v in TEXTOS.items()},
        orcamento={
            "limite_usd": float(cfg.orcamento_mensal_usd) if cfg and cfg.orcamento_mensal_usd else None,
            "gasto_mes_usd": await gasto_mes(session, a.org_id),
        },
    )


@router.post("/auditorias", response_model=AuditoriaOut, status_code=201)
async def criar_auditoria(dados: AuditoriaIn, principal: Criar, session: SessionDep) -> AuditoriaOut:
    await garantir_acesso_empresa(session, principal, dados.company_id)
    up = await session.get(UploadedFile, dados.arquivo_id)
    if up is None or up.company_id != dados.company_id or up.storage_path is None:
        raise NaoEncontrado("Arquivo não encontrado para esta empresa.")
    erros = validar_mapeamento(dados.mapeamento, up.colunas)
    if erros:
        raise AppError(" ".join(erros), codigo="mapeamento_invalido")
    a = Audit(
        org_id=principal.org_id,
        company_id=dados.company_id,
        file_id=up.id,
        nome=dados.nome,
        mapeamento=dados.mapeamento,
        status=StatusAuditoria.PREPARANDO,
        data_referencia=dados.data_referencia or date.today(),
        contexto_operacao=dados.contexto_operacao,
        created_by=principal.user_id,
    )
    session.add(a)
    if dados.salvar_modelo:
        session.add(
            MappingTemplate(
                org_id=principal.org_id,
                company_id=dados.company_id,
                nome=dados.nome_modelo or f"Modelo de {up.nome_original}",
                sistema_origem=dados.sistema_origem,
                mapeamento=dados.mapeamento,
                assinatura_colunas=assinatura_colunas(up.colunas),
                created_by=principal.user_id,
            )
        )
    await session.flush()
    await registrar(
        session,
        principal,
        Acao.AUDITORIA_CRIADA,
        entidade="auditoria",
        entidade_id=a.id,
        detalhes={"nome": a.nome, "empresa": str(a.company_id)},
    )
    await session.commit()
    celery_app.send_task("auditoria.preparar", args=[str(a.id), str(principal.org_id)], queue="ingest")
    return await _saida(session, a, principal)


@router.get("/auditorias", response_model=list[AuditoriaResumo])
async def listar_auditorias(
    principal: Ver, session: SessionDep, company_id: uuid.UUID | None = None, limite: int = Query(100, le=500)
) -> list[AuditoriaResumo]:
    q = select(Audit, Company.razao_social).join(Company, Company.id == Audit.company_id)
    if company_id:
        q = q.where(Audit.company_id == company_id)
    permitidas = await empresas_permitidas(session, principal)
    if permitidas is not None:
        q = q.where(Audit.company_id.in_(permitidas), Audit.status == StatusAuditoria.CONCLUIDA)
    rows = (await session.execute(q.order_by(Audit.created_at.desc()).limit(limite))).all()
    ids = [a.id for a, _ in rows]
    pend = (
        dict(
            (
                await session.execute(
                    select(AuditItem.audit_id, func.count())
                    .where(
                        AuditItem.audit_id.in_(ids),
                        AuditItem.ignorado.is_(False),
                        AuditItem.revisao_status == StatusRevisao.PENDENTE,
                        AuditItem.status.in_(list(STATUS_REVISAVEIS)),
                    )
                    .group_by(AuditItem.audit_id)
                )
            ).all()
        )
        if ids
        else {}
    )
    return [AuditoriaResumo(**_resumo(a, nome, pend.get(a.id, 0))) for a, nome in rows]


@router.get("/auditorias/{audit_id}", response_model=AuditoriaOut)
async def obter_auditoria(audit_id: uuid.UUID, principal: Ver, session: SessionDep) -> AuditoriaOut:
    return await _saida(session, await _carregar_auditoria(session, principal, audit_id), principal)


class PreviaLinha(BaseModel):
    linha: int
    codigo_interno: str
    descricao: str
    ncm_informado: str | None
    nbs_informado: str | None
    gtin: str | None
    problemas: list[dict[str, str]]


@router.get("/auditorias/{audit_id}/previa", response_model=list[PreviaLinha])
async def previa(
    audit_id: uuid.UUID,
    principal: Ver,
    session: SessionDep,
    problema: str | None = None,
    limite: int = Query(200, le=2000),
) -> list[PreviaLinha]:
    await _carregar_auditoria(session, principal, audit_id)
    q = select(AuditItem).where(AuditItem.audit_id == audit_id, func.jsonb_array_length(AuditItem.problemas) > 0)
    if problema:
        q = q.where(AuditItem.problemas.contains([{"codigo": problema}]))
    rows = await session.scalars(q.order_by(AuditItem.linha).limit(limite))
    return [
        PreviaLinha(
            linha=i.linha,
            codigo_interno=i.codigo_interno,
            descricao=i.descricao,
            ncm_informado=i.ncm_informado,
            nbs_informado=i.nbs_informado,
            gtin=i.gtin,
            problemas=i.problemas,
        )
        for i in rows
    ]


class IniciarIn(BaseModel):
    modo: str | None = Field(None, pattern="^(tempo_real|lote)$")
    confirmar_custo_usd: float = Field(ge=0, description="Custo estimado exibido ao usuário e confirmado por ele.")


@router.post("/auditorias/{audit_id}/iniciar", response_model=AuditoriaOut)
async def iniciar_auditoria(
    audit_id: uuid.UUID, dados: IniciarIn, principal: Criar, session: SessionDep
) -> AuditoriaOut:
    a = await _carregar_auditoria(session, principal, audit_id)
    if a.status not in PODE_INICIAR:
        raise Conflito("Esta auditoria não pode ser iniciada no estado atual.")
    agentes = await run_in_threadpool(catalogo.agentes_configurados)
    modelos = {k: v["modelo"] for k, v in agentes.items()}
    try:
        await run_in_threadpool(verificar_chaves, [m for k, m in modelos.items() if k != "abreviacoes"])
    except ChaveAPIAusente as e:
        raise AppError(
            str(e),
            acao="Peça ao superadministrador para cadastrar a chave em Chaves de API ou trocar o modelo.",
            status_code=503,
            codigo="ia_indisponivel",
        ) from e
    cfg = await session.get(OrgSettings, principal.org_id) or OrgSettings(org_id=principal.org_id)
    estimativas = await run_in_threadpool(estimativa_atual, a)
    modo = dados.modo or estimativas.get("modo_recomendado") or "tempo_real"
    estimativa = estimativas.get(modo, {})
    previsto = float(estimativa.get("custo_usd_estimado", 0))
    if cfg.orcamento_mensal_usd is not None:
        gasto = await gasto_mes(session, principal.org_id)  # type: ignore[arg-type]
        if gasto + previsto > float(cfg.orcamento_mensal_usd):
            raise Conflito(
                f"O custo estimado (US$ {previsto:.2f}) somado ao gasto do mês (US$ {gasto:.2f}) ultrapassa o "
                f"orçamento de US$ {float(cfg.orcamento_mensal_usd):.2f}.",
                acao="Aumente o orçamento em Configurações ou divida a auditoria.",
            )
    snap = await criar_ou_obter(session)
    a.snapshot_id = snap.id
    a.modo = modo
    a.status = StatusAuditoria.PROCESSANDO
    a.erro = None
    a.iniciado_em = a.iniciado_em or datetime.now(UTC)
    a.estimativa = estimativas
    # Os modelos ficam congelados na auditoria: trocar em "Modelos de IA" não muda uma auditoria em andamento.
    a.configuracao = {
        "modelos": modelos,
        "esforcos": {k: v["esforco"] for k, v in agentes.items()},
        "limiar_escalonamento": float(cfg.limiar_escalonamento or 0.8),
        "aprovacao_automatica": cfg.aprovacao_automatica,
        "imposto_seletivo_exige_analise": cfg.imposto_seletivo_exige_analise,
        "custo_estimado_confirmado_usd": dados.confirmar_custo_usd,
        "modo": modo,
    }
    await registrar(
        session,
        principal,
        Acao.AUDITORIA_INICIADA,
        entidade="auditoria",
        entidade_id=a.id,
        detalhes={"modo": modo, "custo_estimado_usd": previsto, "snapshot": str(snap.id)},
    )
    await session.commit()
    celery_app.send_task("auditoria.iniciar", args=[str(a.id), str(principal.org_id)], queue="pipeline")
    return await _saida(session, a, principal)


@router.post("/auditorias/{audit_id}/cancelar", response_model=AuditoriaOut)
async def cancelar_auditoria(audit_id: uuid.UUID, principal: Criar, session: SessionDep) -> AuditoriaOut:
    a = await _carregar_auditoria(session, principal, audit_id)
    if a.status in (StatusAuditoria.CONCLUIDA, StatusAuditoria.CANCELADA):
        raise Conflito("A auditoria já foi encerrada.")
    a.status = StatusAuditoria.CANCELADA
    await registrar(session, principal, Acao.AUDITORIA_CANCELADA, entidade="auditoria", entidade_id=a.id)
    return await _saida(session, a, principal)


# ================================================================================== itens ==
class ItensColunares(BaseModel):
    """Formato colunar compacto para a tabela virtualizada (dezenas de milhares de linhas)."""

    total: int
    campos: list[str]
    linhas: list[list[Any]]


CAMPOS_TABELA = [
    "id",
    "linha",
    "codigo_interno",
    "descricao",
    "tipo",
    "codigo_atual",
    "codigo_sugerido",
    "tipo_codigo",
    "status",
    "motivos",
    "confianca_global",
    "revisao_status",
    "tratamento",
    "cclasstrib_sugerido",
    "cst_sugerido",
    "imposto_seletivo",
    "perguntas",
    "origem",
    "nivel_revisao",
    "aprovado_automaticamente",
    "categoria",
    "hipotese",
]


@router.get("/auditorias/{audit_id}/itens", response_model=ItensColunares)
async def listar_itens(audit_id: uuid.UUID, principal: Ver, session: SessionDep) -> ItensColunares:
    await _carregar_auditoria(session, principal, audit_id)
    q = select(
        AuditItem.id,
        AuditItem.linha,
        AuditItem.codigo_interno,
        AuditItem.descricao,
        AuditItem.tipo,
        AuditItem.ncm,
        AuditItem.nbs,
        AuditItem.ncm_informado,
        AuditItem.codigo_sugerido,
        AuditItem.tipo_codigo_sugerido,
        AuditItem.status,
        AuditItem.motivos,
        AuditItem.confianca_global,
        AuditItem.revisao_status,
        AuditItem.tipo_tratamento,
        AuditItem.cclasstrib_sugerido,
        AuditItem.cst_sugerido,
        AuditItem.is_situacao,
        func.jsonb_array_length(AuditItem.perguntas).label("n_perguntas"),
        AuditItem.origem,
        AuditItem.final_codigo,
        AuditItem.final_cclasstrib,
        AuditItem.nivel_revisao,
        AuditItem.aprovado_automaticamente,
        AuditItem.categoria,
        AuditItem.hipotese,
    ).where(AuditItem.audit_id == audit_id, AuditItem.ignorado.is_(False))
    if principal.somente_leitura:
        q = q.where(AuditItem.revisao_status == StatusRevisao.APROVADO)
    rows = (await session.execute(q.order_by(AuditItem.linha))).all()
    linhas = []
    for r in rows:
        tipo_cod = r.tipo_codigo_sugerido or ("nbs" if r.nbs and not r.ncm else "ncm")
        atual = r.nbs if tipo_cod == "nbs" else (r.ncm or r.ncm_informado)
        linhas.append(
            [
                str(r.id),
                r.linha,
                r.codigo_interno,
                r.descricao,
                r.tipo,
                atual,
                r.final_codigo or r.codigo_sugerido,
                tipo_cod,
                r.status,
                r.motivos or [],
                r.confianca_global,
                r.revisao_status,
                r.tipo_tratamento,
                r.final_cclasstrib or r.cclasstrib_sugerido,
                r.cst_sugerido,
                r.is_situacao,
                r.n_perguntas or 0,
                r.origem,
                r.nivel_revisao,
                r.aprovado_automaticamente,
                r.categoria,
                r.hipotese,
            ]
        )
    return ItensColunares(total=len(linhas), campos=CAMPOS_TABELA, linhas=linhas)


class ItemDetalhe(BaseModel):
    item: dict[str, Any]
    codigo_atual: dict[str, Any] | None
    codigo_sugerido: dict[str, Any] | None
    candidatos: list[dict[str, Any]]
    regra: dict[str, Any] | None
    trecho_legal: dict[str, Any] | None
    cclasstrib: dict[str, Any] | None
    historico: list[dict[str, Any]]
    chamadas_ia: list[dict[str, Any]]
    textos_motivos: dict[str, list[str]]


async def _descricao_codigo(
    session: AsyncSession, snap: RefSnapshot | None, tipo: str | None, codigo: str | None
) -> dict[str, Any] | None:
    if not codigo or not snap or not tipo:
        return None
    from sqlalchemy import text as sql

    vid = snap.versoes.get(tipo)
    if not vid:
        return {"codigo": codigo, "formatado": formatar_codigo(tipo, codigo), "tipo": tipo, "existe": None}
    tabela = "nbs_nodes" if tipo == "nbs" else "ncm_nodes"
    row = (
        await session.execute(
            sql(
                f"SELECT codigo, descricao, descricao_completa, folha, data_inicio, data_fim FROM {tabela} "
                "WHERE version_id = :v AND codigo = :c"
            ),
            {"v": uuid.UUID(vid), "c": codigo},
        )
    ).first()
    hierarquia = []
    if row:
        prefixos = [codigo[:n] for n in range(1, len(codigo) + 1)]
        niveis = (
            await session.execute(
                sql(
                    f"SELECT codigo, descricao FROM {tabela} WHERE version_id = :v AND codigo = ANY(:p) "
                    "ORDER BY length(codigo)"
                ),
                {"v": uuid.UUID(vid), "p": prefixos},
            )
        ).all()
        hierarquia = [
            {"codigo": n.codigo, "formatado": formatar_codigo(tipo, n.codigo), "descricao": n.descricao} for n in niveis
        ]
    return {
        "codigo": codigo,
        "formatado": formatar_codigo(tipo, codigo),
        "tipo": tipo,
        "existe": row is not None,
        "folha": bool(row and row.folha),
        "descricao_completa": row.descricao_completa if row else None,
        "hierarquia": hierarquia,
    }


def _item_dict(i: AuditItem) -> dict[str, Any]:
    d: dict[str, Any] = {}
    for c in AuditItem.__table__.columns.keys():
        v = getattr(i, c)
        if isinstance(v, uuid.UUID):
            v = str(v)
        elif isinstance(v, datetime):
            v = v.isoformat()
        elif hasattr(v, "is_finite"):
            v = float(v)
        d[c] = v
    return d


@router.get("/itens/{item_id}", response_model=ItemDetalhe)
async def detalhe_item(item_id: uuid.UUID, principal: Ver, session: SessionDep) -> ItemDetalhe:
    i = await session.get(AuditItem, item_id)
    if i is None:
        raise NaoEncontrado("Item não encontrado.")
    a = await _carregar_auditoria(session, principal, i.audit_id)
    if principal.somente_leitura and i.revisao_status != StatusRevisao.APROVADO:
        raise NaoEncontrado("Item não encontrado.")
    snap = await session.get(RefSnapshot, a.snapshot_id) if a.snapshot_id else None
    tipo_atual = "nbs" if (i.nbs and not i.ncm) else "ncm"
    atual_cod = i.nbs if tipo_atual == "nbs" else i.ncm
    provavel = (i.estrutura or {}).get("codigo_atual", {}) or {}
    atual = await _descricao_codigo(session, snap, tipo_atual, provavel.get("provavel") or atual_cod)
    if atual is not None and provavel.get("provavel"):
        atual["informado"] = atual_cod
        atual["zero_restaurado"] = True
    tipo_final = i.final_tipo_codigo or i.tipo_codigo_sugerido
    sug = await _descricao_codigo(session, snap, tipo_final, i.final_codigo or i.codigo_sugerido)
    cands = await session.scalars(
        select(ItemCandidate).where(ItemCandidate.item_id == i.id).order_by(ItemCandidate.posicao)
    )
    regra_id = i.final_regra_id or i.regra_id
    regra = await session.get(LegalRule, regra_id) if regra_id else None
    trecho = None
    if regra and regra.provision_id:
        p = await session.get(LegalProvision, regra.provision_id)
        if p:
            trecho = {"anexo": p.anexo, "item": p.item, "titulo_anexo": p.titulo_anexo, "texto": p.texto}
    cct = None
    cct_cod = i.final_cclasstrib or i.cclasstrib_sugerido
    if cct_cod and snap and snap.versoes.get("cclasstrib"):
        c = await session.scalar(
            select(CClassTribCode).where(
                CClassTribCode.version_id == uuid.UUID(snap.versoes["cclasstrib"]), CClassTribCode.codigo == cct_cod
            )
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
    hist = await session.scalars(select(ItemReview).where(ItemReview.item_id == i.id).order_by(ItemReview.created_at))
    calls = await session.scalars(select(LlmCall).where(LlmCall.item_id == i.id).order_by(LlmCall.created_at))
    return ItemDetalhe(
        item=_item_dict(i),
        codigo_atual=atual,
        codigo_sugerido=sug,
        candidatos=[
            {
                "codigo": c.codigo,
                "formatado": formatar_codigo(c.tipo_codigo, c.codigo),
                "tipo": c.tipo_codigo,
                "descricao_completa": c.descricao_completa,
                "posicao": c.posicao,
                "rank_semantico": c.rank_semantico,
                "rank_textual": c.rank_textual,
                "codigo_atual": c.codigo_atual,
            }
            for c in cands
        ],
        regra={
            "id": str(regra.id),
            "slug": regra.slug,
            "versao": regra.versao,
            "anexo": regra.anexo,
            "item": regra.item,
            "titulo_anexo": regra.titulo_anexo,
            "descricao_legal": regra.descricao_legal,
            "dispositivo_legal": regra.dispositivo_legal,
            "tipo_tratamento": regra.tipo_tratamento,
            "condicoes": regra.condicoes,
            "controverso": regra.controverso,
            "nota_controversia": regra.nota_controversia,
        }
        if regra
        else None,
        trecho_legal=trecho,
        cclasstrib=cct,
        historico=[
            {
                "id": str(h.id),
                "acao": h.acao,
                "usuario": h.user_email,
                "comentario": h.comentario,
                "antes": h.antes,
                "depois": h.depois,
                "lote_id": str(h.lote_id) if h.lote_id else None,
                "em": h.created_at.isoformat(),
            }
            for h in hist
        ],
        chamadas_ia=[
            {
                "no": c.no,
                "modelo": c.modelo,
                "prompt": c.prompt_versao,
                "modo": c.modo,
                "status": c.status,
                "tokens_entrada": c.tokens_entrada,
                "tokens_saida": c.tokens_saida,
                "tokens_cache_leitura": c.tokens_cache_leitura,
                "custo_usd": float(c.custo_usd or 0),
                "latencia_ms": c.latencia_ms,
                "em": c.created_at.isoformat(),
            }
            for c in calls
        ],
        textos_motivos={k: list(v) for k, v in TEXTOS.items()},
    )


# ======================================================================= eventos (SSE) ==
@router.get("/auditorias/{audit_id}/eventos")
async def eventos(audit_id: uuid.UUID, principal: Ver, session: SessionDep, request: Request) -> EventSourceResponse:
    a = await _carregar_auditoria(session, principal, audit_id)
    inicial = {
        "tipo": "status",
        "status": a.status,
        "contadores": a.contadores or {},
        "custo_usd": float(a.custo_usd or 0),
    }
    await session.commit()

    async def gerador() -> AsyncIterator[dict[str, str]]:
        yield {"event": "status", "data": orjson.dumps(inicial).decode()}
        pubsub = redis_async().pubsub()
        await pubsub.subscribe(canal_auditoria(audit_id))
        try:
            while not await request.is_disconnected():
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=15.0)
                if msg is None:
                    yield {"event": "ping", "data": "{}"}
                    continue
                dados = msg["data"]
                tipo = orjson.loads(dados).get("tipo", "mensagem")
                yield {"event": tipo, "data": dados}
                await asyncio.sleep(0)
        finally:
            await pubsub.unsubscribe(canal_auditoria(audit_id))
            await pubsub.aclose()  # type: ignore[no-untyped-call]

    return EventSourceResponse(gerador(), ping=20)
