"""Analista fiscal: dossiê da empresa, fatos, perguntas decisivas, teses por família e dossiê de decisão."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.analise import aplicacao, dossie, transicao
from app.analise import fatos as fatos_mod
from app.analise import pendencias as pend_mod
from app.analise.avaliacao import DIMENSOES
from app.api.audits import _carregar_auditoria
from app.api.orgs import garantir_acesso_empresa
from app.audits.processing import enfileirar_itens
from app.core.audit_trail import Acao, registrar
from app.core.codes import formatar_codigo
from app.core.deps import Principal, SessionDep, exigir
from app.core.errors import Conflito, NaoEncontrado
from app.core.rbac import Perm
from app.llm import catalogo as catalogo_ia
from app.models import (
    Audit,
    AuditItem,
    Company,
    CompanyFact,
    ItemReview,
    LegalProvision,
    LlmCall,
    Pendencia,
    RefSnapshot,
    RefVersion,
    TaxProfile,
    TaxThesis,
)
from app.models.enums import EscopoFato, OrigemFato, StatusAuditoria, StatusItem, StatusPendencia, StatusRevisao
from app.worker.celery_app import celery_app

router = APIRouter(tags=["analista fiscal"])
Ver = Annotated[Principal, Depends(exigir(Perm.VER))]
Responder = Annotated[Principal, Depends(exigir(Perm.RESPONDER))]
Revisar = Annotated[Principal, Depends(exigir(Perm.REVISAR))]

LIMITE_REAVALIACAO_IMEDIATA = 400


def _reavaliar(session: Session, item_ids: list[uuid.UUID], motivo: str) -> int:
    n = 0
    for i in item_ids:
        if aplicacao.reavaliar(session, i, motivo):
            n += 1
    return n


async def _reavaliar_ou_enfileirar(
    session: Any, org_id: uuid.UUID, item_ids: list[uuid.UUID], motivo: str
) -> tuple[int, bool]:
    """Poucos itens: reavalia na hora (sem IA). Muitos: em segundo plano."""
    if len(item_ids) <= LIMITE_REAVALIACAO_IMEDIATA:
        n = await session.run_sync(lambda s: _reavaliar(s, item_ids, motivo))
        return n, False
    await session.commit()
    celery_app.send_task(
        "analise.reavaliar_itens", args=[str(org_id), [str(i) for i in item_ids], motivo], queue="pipeline"
    )
    return len(item_ids), True


async def _atualizar_contadores(audit_ids: set[uuid.UUID], org_id: uuid.UUID, session: Any) -> None:
    """Recalcula os contadores já na resposta: a tela recarrega logo em seguida e precisa vê-los certos."""
    await session.commit()
    from app.audits.processing import atualizar_contadores

    for a in audit_ids:
        await run_in_threadpool(atualizar_contadores, a, org_id)


# ================================================================================ dossiê ==
class FatoOut(BaseModel):
    id: uuid.UUID
    escopo: str
    grupo_chave: str | None
    item_chave: str | None
    atributo: str
    valor: str
    origem: str
    origem_rotulo: str
    evidencia: str | None
    autor_email: str | None
    created_at: datetime


def _fato_out(f: CompanyFact) -> FatoOut:
    return FatoOut(
        id=f.id,
        escopo=f.escopo,
        grupo_chave=f.grupo_chave,
        item_chave=f.item_chave,
        atributo=f.atributo,
        valor=f.valor,
        origem=f.origem,
        origem_rotulo=fatos_mod.ROTULOS_ORIGEM.get(f.origem, f.origem),
        evidencia=f.evidencia,
        autor_email=f.autor_email,
        created_at=f.created_at,
    )


class PerguntaDossieOut(BaseModel):
    atributo: str
    pergunta: str
    ajuda: str
    opcoes: list[dict[str, str]]
    valor: str | None
    origem: str | None
    autor_email: str | None
    respondido_em: datetime | None


class DossieOut(BaseModel):
    company_id: uuid.UUID
    empresa: str
    segmento: str | None
    segmentos: list[dict[str, str]]
    cadastro: dict[str, Any]
    perguntas: list[PerguntaDossieOut]
    # Perguntas sobre a empresa que o analista fez durante as análises (fora do questionário fixo).
    perguntas_das_analises: list[PerguntaDossieOut]
    outros_fatos: list[FatoOut]
    completo: bool
    faltando: int
    perguntas_abertas_em_auditorias: int


async def _dossie(session: Any, empresa: Company) -> DossieOut:
    fatos = {
        f.atributo: f
        for f in await session.scalars(
            select(CompanyFact)
            .where(
                CompanyFact.company_id == empresa.id,
                CompanyFact.escopo == EscopoFato.EMPRESA,
                CompanyFact.ativo.is_(True),
            )
            .order_by(CompanyFact.created_at)
        )
    }
    perguntas = []
    catalogo = dossie.perguntas_do_segmento(empresa.segmento)
    for p in catalogo:
        f = fatos.get(p.atributo)
        perguntas.append(
            PerguntaDossieOut(
                **p.como_dict(),
                valor=f.valor if f else None,
                origem=f.origem if f else None,
                autor_email=f.autor_email if f else None,
                respondido_em=f.created_at if f else None,
            )
        )
    nomes = {p.atributo for p in catalogo}
    abertas_lista = list(
        await session.scalars(
            select(Pendencia)
            .where(
                Pendencia.company_id == empresa.id,
                Pendencia.escopo == EscopoFato.EMPRESA,
                Pendencia.status == StatusPendencia.ABERTA,
            )
            .order_by(Pendencia.created_at)
        )
    )
    abertas = len(abertas_lista)
    das_analises: dict[str, PerguntaDossieOut] = {}
    for pend in abertas_lista:
        if pend.atributo in nomes or pend.atributo in das_analises:
            continue
        das_analises[pend.atributo] = PerguntaDossieOut(
            atributo=pend.atributo,
            pergunta=pend.pergunta,
            ajuda=pend.motivo or "",
            opcoes=[
                {"valor": str(o.get("valor")), "rotulo": str(o.get("rotulo") or o.get("valor"))}
                for o in pend.opcoes or []
            ],
            valor=None,
            origem=None,
            autor_email=None,
            respondido_em=None,
        )
    faltando = sum(1 for p in perguntas if p.valor is None) + (0 if empresa.segmento else 1) + len(das_analises)
    return DossieOut(
        company_id=empresa.id,
        empresa=empresa.razao_social,
        segmento=empresa.segmento,
        segmentos=[{"valor": v, "rotulo": r} for v, r in dossie.SEGMENTOS],
        cadastro={
            "regime_tributario": empresa.regime_tributario,
            "uf": empresa.uf,
            "cnae": empresa.cnae,
            "atividade_principal": empresa.atividade_principal,
        },
        perguntas=perguntas,
        perguntas_das_analises=list(das_analises.values()),
        outros_fatos=[_fato_out(f) for k, f in fatos.items() if k not in nomes],
        completo=faltando == 0,
        faltando=faltando,
        perguntas_abertas_em_auditorias=int(abertas or 0),
    )


@router.get("/empresas/{company_id}/dossie", response_model=DossieOut)
async def obter_dossie(company_id: uuid.UUID, principal: Ver, session: SessionDep) -> DossieOut:
    empresa = await garantir_acesso_empresa(session, principal, company_id)
    return await _dossie(session, empresa)


class DossieIn(BaseModel):
    segmento: str | None = Field(None, max_length=40)
    respostas: dict[str, str] = Field(default_factory=dict)


@router.post("/empresas/{company_id}/dossie", response_model=DossieOut)
async def salvar_dossie(company_id: uuid.UUID, dados: DossieIn, principal: Responder, session: SessionDep) -> DossieOut:
    empresa = await garantir_acesso_empresa(session, principal, company_id)
    if dados.segmento is not None:
        if dados.segmento not in dict(dossie.SEGMENTOS):
            raise Conflito("Segmento inválido.")
        empresa.segmento = dados.segmento
    respostas = {fatos_mod.chave(k): v for k, v in dados.respostas.items() if str(v).strip()}

    def _gravar(s: Session) -> list[uuid.UUID]:
        for atributo, v in respostas.items():
            fatos_mod.registrar(
                s,
                org_id=empresa.org_id,
                company_id=empresa.id,
                escopo=EscopoFato.EMPRESA,
                atributo=atributo,
                valor_=v,
                origem=OrigemFato.USUARIO,
                evidencia="Dossiê do estabelecimento",
                autor_id=principal.user_id,
                autor_email=principal.email,
            )
        # Perguntas de empresa abertas nas auditorias foram respondidas pelo dossiê.
        afetados: list[uuid.UUID] = []
        for p in pend_mod.pendencias_empresa_abertas(s, empresa.id, set(respostas)):
            p.status, p.resposta = StatusPendencia.RESPONDIDA, respostas[p.atributo]
            p.respondido_por, p.respondido_por_email = principal.user_id, principal.email
            afetados.extend(p.item_ids)
        return list(dict.fromkeys(afetados))

    afetados = await session.run_sync(_gravar)
    await registrar(
        session,
        principal,
        Acao.DOSSIE,
        entidade="empresa",
        entidade_id=empresa.id,
        detalhes={"segmento": empresa.segmento, "respostas": respostas},
    )
    if afetados:
        await _reavaliar_ou_enfileirar(session, empresa.org_id, afetados, "dossiê atualizado")
        audits = set(await session.scalars(select(AuditItem.audit_id).where(AuditItem.id.in_(afetados)).distinct()))
        await _atualizar_contadores(audits, empresa.org_id, session)
    return await _dossie(session, empresa)


@router.get("/empresas/{company_id}/fatos", response_model=list[FatoOut])
async def listar_fatos(
    company_id: uuid.UUID,
    principal: Ver,
    session: SessionDep,
    escopo: str | None = None,
    limite: int = Query(500, le=5000),
) -> list[FatoOut]:
    await garantir_acesso_empresa(session, principal, company_id)
    q = select(CompanyFact).where(CompanyFact.company_id == company_id, CompanyFact.ativo.is_(True))
    if escopo:
        q = q.where(CompanyFact.escopo == escopo)
    return [_fato_out(f) for f in await session.scalars(q.order_by(CompanyFact.created_at.desc()).limit(limite))]


# ============================================================================= perguntas ==
class ItemResumo(BaseModel):
    id: uuid.UUID
    linha: int
    codigo_interno: str
    descricao: str
    sugestao: dict[str, str] | None = None
    resposta: str | None = None  # resposta que vale hoje para o item (perguntas respondidas)


class PendenciaOut(BaseModel):
    id: uuid.UUID
    atributo: str
    escopo: str
    grupo_chave: str
    grupo_rotulo: str | None
    pergunta: str
    motivo: str | None
    opcoes: list[dict[str, Any]]
    nivel: str
    status: str
    resposta: str | None
    respondido_por_email: str | None
    respondido_em: datetime | None
    total_itens: int
    itens: list[ItemResumo]


async def _itens_respondidos(session: Any, p: Pendencia) -> list[uuid.UUID]:
    """Itens que receberam a resposta desta pergunta. A lista da pergunta se esvazia quando os itens não
    precisam mais dela; o histórico de fatos guarda de qual pergunta cada resposta veio (para corrigir)."""
    chaves = [
        c
        for c in await session.scalars(
            select(CompanyFact.item_chave).where(CompanyFact.pendencia_id == p.id, CompanyFact.item_chave.is_not(None))
        )
        if c
    ]
    ids = list(
        await session.scalars(
            select(AuditItem.id).where(AuditItem.audit_id == p.audit_id, AuditItem.codigo_interno.in_(set(chaves)))
        )
    )
    for k in p.respostas_itens or {}:
        try:
            ids.append(uuid.UUID(str(k)))
        except ValueError:
            continue
    return list(dict.fromkeys(ids))


async def _pendencia_out(session: Any, p: Pendencia, limite_itens: int) -> PendenciaOut:
    itens: list[ItemResumo] = []
    respondida = p.status == StatusPendencia.RESPONDIDA and p.escopo != EscopoFato.EMPRESA
    todos = await _itens_respondidos(session, p) if respondida else list(p.item_ids or [])
    if todos:
        rows = list(
            await session.scalars(
                select(AuditItem).where(AuditItem.id.in_(todos[:limite_itens])).order_by(AuditItem.linha)
            )
        )
        atuais: dict[str, str] = {}
        if rows:
            atuais = {
                f.item_chave: f.valor
                for f in await session.scalars(
                    select(CompanyFact).where(
                        CompanyFact.company_id == p.company_id,
                        CompanyFact.escopo == EscopoFato.ITEM,
                        CompanyFact.atributo == p.atributo,
                        CompanyFact.ativo.is_(True),
                        CompanyFact.item_chave.in_([i.codigo_interno for i in rows]),
                    )
                )
            }
        itens = [
            ItemResumo(
                id=i.id,
                linha=i.linha,
                codigo_interno=i.codigo_interno,
                descricao=i.descricao,
                sugestao=((i.estrutura or {}).get("sugestoes_fatos") or {}).get(p.atributo),
                resposta=atuais.get(i.codigo_interno),
            )
            for i in rows
        ]
    return PendenciaOut(
        id=p.id,
        atributo=p.atributo,
        escopo=p.escopo,
        grupo_chave=p.grupo_chave,
        grupo_rotulo=p.grupo_rotulo,
        pergunta=p.pergunta,
        motivo=p.motivo,
        opcoes=p.opcoes or [],
        nivel=p.nivel,
        status=p.status,
        resposta=p.resposta,
        respondido_por_email=p.respondido_por_email,
        respondido_em=p.respondido_em,
        total_itens=len(todos),
        itens=itens,
    )


@router.get("/auditorias/{audit_id}/pendencias", response_model=list[PendenciaOut])
async def listar_pendencias(
    audit_id: uuid.UUID, principal: Ver, session: SessionDep, status: str | None = "aberta"
) -> list[PendenciaOut]:
    await _carregar_auditoria(session, principal, audit_id)
    q = select(Pendencia).where(Pendencia.audit_id == audit_id)
    if status:
        q = q.where(Pendencia.status == status)
    lista = list(await session.scalars(q))
    # Primeiro as perguntas de empresa, depois as que destravam mais itens.
    lista.sort(key=lambda p: (p.escopo != EscopoFato.EMPRESA, -len(p.item_ids or []), p.pergunta))
    return [await _pendencia_out(session, p, 8) for p in lista]


async def _pendencia(session: Any, principal: Principal, pid: uuid.UUID) -> Pendencia:
    p = await session.get(Pendencia, pid)
    if p is None:
        raise NaoEncontrado("Pergunta não encontrada.")
    await _carregar_auditoria(session, principal, p.audit_id)
    return p  # type: ignore[no-any-return]


@router.get("/pendencias/{pendencia_id}", response_model=PendenciaOut)
async def obter_pendencia(pendencia_id: uuid.UUID, principal: Ver, session: SessionDep) -> PendenciaOut:
    return await _pendencia_out(session, await _pendencia(session, principal, pendencia_id), 2000)


class RespostaIn(BaseModel):
    valor: str | None = Field(
        None, max_length=200, description="Resposta para a empresa (dossiê) ou para o único item da pergunta."
    )
    respostas_itens: dict[uuid.UUID, str] = Field(
        default_factory=dict, description="Resposta de cada item (obrigatória quando a pergunta tem vários)."
    )
    observacao: str | None = Field(None, max_length=1000)


class RespostaOut(BaseModel):
    pendencia: PendenciaOut
    reavaliados: int
    em_segundo_plano: bool
    mensagem: str


@router.post("/pendencias/{pendencia_id}/responder", response_model=RespostaOut)
async def responder_pendencia(
    pendencia_id: uuid.UUID, dados: RespostaIn, principal: Responder, session: SessionDep
) -> RespostaOut:
    p = await _pendencia(session, principal, pendencia_id)
    autor = pend_mod.Autor(principal.user_id, principal.email)
    item_ids = await session.run_sync(
        lambda s: pend_mod.responder(
            s,
            pendencia_id,
            autor,
            valor=dados.valor,
            respostas_itens=dados.respostas_itens or None,
            observacao=dados.observacao,
        )
    )
    await registrar(
        session,
        principal,
        Acao.PERGUNTA_RESPONDIDA,
        entidade="pendencia",
        entidade_id=pendencia_id,
        detalhes={
            "atributo": p.atributo,
            "grupo": p.grupo_chave,
            "valor": dados.valor,
            "itens": len(dados.respostas_itens),
        },
    )
    alvo = list(dados.respostas_itens) if dados.valor is None and p.escopo != EscopoFato.EMPRESA else item_ids
    if p.escopo == EscopoFato.EMPRESA:
        # Fato da empresa (ADR 0029): a mesma pergunta aberta em outras auditorias da empresa também fica
        # respondida, e os itens dela são reavaliados.
        def _outras(s: Session) -> list[uuid.UUID]:
            mais: list[uuid.UUID] = []
            for outra in pend_mod.pendencias_empresa_abertas(s, p.company_id, {p.atributo}):
                outra.status, outra.resposta = StatusPendencia.RESPONDIDA, p.resposta
                outra.respondido_por, outra.respondido_por_email = principal.user_id, principal.email
                mais.extend(outra.item_ids)
            return mais

        alvo = list(dict.fromkeys([*alvo, *await session.run_sync(_outras)]))
    if p.atributo == pend_mod.FATO_CODIGO:
        # "O que é este item?" (ADR 0029): o código escolhido é analisado de novo (pode chamar a IA).
        reprocessar = await session.run_sync(lambda s: pend_mod.identificar_pela_resposta(s, p.id, autor, alvo))
        if reprocessar:
            a = await session.get(Audit, p.audit_id)
            assert a is not None
            if a.status == StatusAuditoria.CONCLUIDA:
                a.status = StatusAuditoria.PROCESSANDO
            a.modo = "tempo_real"
            await session.commit()
            from app.audits.processing import enfileirar_itens

            enfileirar_itens(a.id, a.org_id, reprocessar)
        alvo = [i for i in alvo if i not in set(reprocessar)]
    n, fundo = await _reavaliar_ou_enfileirar(session, p.org_id, alvo, f"resposta de {principal.email}")
    await _atualizar_contadores({p.audit_id}, p.org_id, session)
    await session.refresh(p)
    msg = (
        f"Resposta registrada. {n} itens serão reavaliados em segundo plano."
        if fundo
        else f"Resposta registrada. {n} itens reavaliados."
    )
    return RespostaOut(
        pendencia=await _pendencia_out(session, p, 50), reavaliados=n, em_segundo_plano=fundo, mensagem=msg
    )


# ============================================================================ famílias ==
class TeseResumo(BaseModel):
    id: uuid.UUID
    tipo_codigo: str
    codigo: str
    codigo_formatado: str
    descricao: str | None
    entendimento: str | None
    hipoteses: list[dict[str, Any]]
    imposto_seletivo: str | None
    itens: int
    por_status: dict[str, int]
    modelo: str | None
    aprovada_por_email: str | None
    aprovada_em: datetime | None
    created_at: datetime


def _tese_resumo(t: TaxThesis, itens: int, por_status: dict[str, int]) -> TeseResumo:
    r = t.resultado or {}
    return TeseResumo(
        id=t.id,
        tipo_codigo=t.tipo_codigo,
        codigo=t.codigo,
        codigo_formatado=formatar_codigo(t.tipo_codigo, t.codigo),
        descricao=((t.evidencias or {}).get("pacote") or {}).get("codigo", {}).get("descricao_oficial"),
        entendimento=r.get("entendimento"),
        hipoteses=[
            {"id": h["id"], "titulo": h["titulo"], "cclasstrib": h["cclasstrib"], "tipo": h["tipo"]}
            for h in r.get("hipoteses", [])
        ],
        imposto_seletivo=(r.get("imposto_seletivo") or {}).get("situacao"),
        itens=itens,
        por_status=por_status,
        modelo=t.modelo,
        aprovada_por_email=t.aprovada_por_email,
        aprovada_em=t.aprovada_em,
        created_at=t.created_at,
    )


@router.get("/auditorias/{audit_id}/teses", response_model=list[TeseResumo])
async def listar_teses(audit_id: uuid.UUID, principal: Ver, session: SessionDep) -> list[TeseResumo]:
    await _carregar_auditoria(session, principal, audit_id)
    rows = (
        await session.execute(
            select(AuditItem.thesis_id, AuditItem.status, func.count())
            .where(AuditItem.audit_id == audit_id, AuditItem.thesis_id.is_not(None))
            .group_by(AuditItem.thesis_id, AuditItem.status)
        )
    ).all()
    contagem: dict[uuid.UUID, dict[str, int]] = {}
    for tid, st, n in rows:
        if tid is not None:
            contagem.setdefault(tid, {})[st] = n
    if not contagem:
        return []
    teses = await session.scalars(select(TaxThesis).where(TaxThesis.id.in_(list(contagem))))
    saida = [_tese_resumo(t, sum(contagem[t.id].values()), contagem[t.id]) for t in teses]
    return sorted(saida, key=lambda t: -t.itens)


class TeseDetalhe(TeseResumo):
    resultado: dict[str, Any]
    validacao: dict[str, Any]
    evidencias: dict[str, Any]
    fatos_empresa: dict[str, Any]
    data_referencia: str
    transicao: dict[str, str]


@router.get("/teses/{tese_id}", response_model=TeseDetalhe)
async def obter_tese(tese_id: uuid.UUID, principal: Ver, session: SessionDep) -> TeseDetalhe:
    t = await session.get(TaxThesis, tese_id)
    if t is None:
        raise NaoEncontrado("Tese não encontrada.")
    await garantir_acesso_empresa(session, principal, t.company_id)
    n = await session.scalar(select(func.count()).select_from(AuditItem).where(AuditItem.thesis_id == t.id))
    return TeseDetalhe(
        **_tese_resumo(t, int(n or 0), {}).model_dump(),
        resultado=t.resultado,
        validacao=t.validacao,
        evidencias=(t.evidencias or {}).get("pacote", {}),
        fatos_empresa=t.fatos_empresa,
        data_referencia=t.data_referencia.isoformat(),
        transicao=transicao.como_dict(t.data_referencia),
    )


class AprovarTeseIn(BaseModel):
    comentario: str | None = Field(None, max_length=2000)


@router.post("/teses/{tese_id}/aprovar", response_model=TeseDetalhe)
async def aprovar_tese(
    tese_id: uuid.UUID, dados: AprovarTeseIn, principal: Revisar, session: SessionDep
) -> TeseDetalhe:
    """Curadoria: o revisor valida o raciocínio da família; os itens são reavaliados (sem IA)."""
    t = await session.get(TaxThesis, tese_id)
    if t is None:
        raise NaoEncontrado("Tese não encontrada.")
    await garantir_acesso_empresa(session, principal, t.company_id)
    from datetime import UTC

    t.aprovada_por, t.aprovada_por_email, t.aprovada_em = principal.user_id, principal.email, datetime.now(UTC)
    await registrar(
        session,
        principal,
        Acao.TESE_APROVADA,
        entidade="tese",
        entidade_id=t.id,
        detalhes={"codigo": t.codigo, "comentario": dados.comentario},
    )
    ids = list(await session.scalars(select(AuditItem.id).where(AuditItem.thesis_id == t.id)))
    audits = set(await session.scalars(select(AuditItem.audit_id).where(AuditItem.thesis_id == t.id).distinct()))
    await _reavaliar_ou_enfileirar(session, t.org_id, ids, f"tese validada por {principal.email}")
    await _atualizar_contadores(audits, t.org_id, session)
    return await obter_tese(tese_id, principal, session)


# ===================================================================== dossiê de decisão ==
class DossieDecisao(BaseModel):
    item: dict[str, Any]
    identidade: dict[str, Any]
    resultado: dict[str, Any]
    dimensoes: list[dict[str, Any]]
    fatos_usados: list[dict[str, Any]]
    fatos_do_item: list[FatoOut]
    fundamentos: list[dict[str, Any]]
    hipoteses: list[dict[str, Any]]
    perguntas: list[dict[str, Any]]
    tese: dict[str, Any] | None
    versoes_perfil: list[dict[str, Any]]
    base_normativa: list[dict[str, Any]]
    transicao: dict[str, str]
    revisoes: list[dict[str, Any]]
    chamadas_ia: list[dict[str, Any]]


@router.get("/itens/{item_id}/dossie", response_model=DossieDecisao)
async def dossie_decisao(item_id: uuid.UUID, principal: Ver, session: SessionDep) -> DossieDecisao:
    """Tudo o que é preciso para responder, meses depois: por que este item recebeu este cClassTrib?"""
    i = await session.get(AuditItem, item_id)
    if i is None:
        raise NaoEncontrado("Item não encontrado.")
    a = await _carregar_auditoria(session, principal, i.audit_id)
    tese = await session.get(TaxThesis, i.thesis_id) if i.thesis_id else None
    perfis = list(
        await session.scalars(select(TaxProfile).where(TaxProfile.item_id == i.id).order_by(TaxProfile.versao.desc()))
    )
    ativo = next((p for p in perfis if p.ativo), None)
    # Texto integral dos trechos citados (o pacote guarda um resumo).
    fundamentos = []
    for f in i.fundamentos or []:
        completo = dict(f)
        if f.get("tipo") == "trecho" and f.get("id"):
            try:
                p = await session.get(LegalProvision, uuid.UUID(str(f["id"])))
            except ValueError:
                p = None
            if p is not None:
                completo["texto_integral"] = p.texto
        fundamentos.append(completo)
    empresa = await session.get(Company, i.company_id)
    familia = (
        fatos_mod.grupo_familia(
            (i.identidade or {}).get("tipo_codigo") or "ncm", str((i.identidade or {}).get("codigo"))
        )
        if (i.identidade or {}).get("codigo")
        else None
    )
    grupos = [g for g in (familia, fatos_mod.grupo_categoria(i.categoria)) if g]
    fatos_item = list(
        await session.scalars(
            select(CompanyFact)
            .where(
                CompanyFact.company_id == i.company_id,
                ((CompanyFact.escopo == EscopoFato.ITEM) & (CompanyFact.item_chave == i.codigo_interno))
                | ((CompanyFact.escopo == EscopoFato.GRUPO) & CompanyFact.grupo_chave.in_(grupos or [""])),
            )
            .order_by(CompanyFact.created_at.desc())
        )
    )
    snap = await session.get(RefSnapshot, a.snapshot_id) if a.snapshot_id else None
    base = []
    if snap:
        ids = [v for v in (snap.versoes or {}).values() if v] + list((snap.completude or {}).get("normas_versoes", []))
        for v in await session.scalars(select(RefVersion).where(RefVersion.id.in_([uuid.UUID(x) for x in ids]))):
            base.append(
                {
                    "fonte": v.fonte,
                    "rotulo": v.rotulo,
                    "coletado_em": v.coletado_em.isoformat(),
                    "url": v.url_origem,
                    "sha256": v.sha256[:12],
                }
            )
    revisoes = await session.scalars(
        select(ItemReview).where(ItemReview.item_id == i.id).order_by(ItemReview.created_at)
    )
    chamadas_ids = [i.id]
    q_calls = select(LlmCall).where(LlmCall.item_id.in_(chamadas_ids))
    if tese and tese.llm_call_id:
        q_calls = select(LlmCall).where((LlmCall.item_id == i.id) | (LlmCall.id == tese.llm_call_id))
    calls = await session.scalars(q_calls.order_by(LlmCall.created_at))
    registro = (ativo.registro if ativo else {}) or {}
    dims = i.dimensoes or {}
    return DossieDecisao(
        item={
            "id": str(i.id),
            "linha": i.linha,
            "codigo_interno": i.codigo_interno,
            "descricao": i.descricao,
            "categoria": i.categoria,
            "marca": i.marca,
            "unidade": i.unidade,
            "gtin": i.gtin,
            "ncm_informado": i.ncm_informado,
            "cst_atual": i.cst_atual,
            "cclasstrib_atual": i.cclasstrib_atual,
            "empresa": empresa.razao_social if empresa else None,
            "data_referencia": a.data_referencia.isoformat(),
            "cenario": i.cenario,
            "status": i.status,
            "nivel_revisao": i.nivel_revisao,
            "revisao_status": i.revisao_status,
            "aprovado_automaticamente": i.aprovado_automaticamente,
            "motivos": i.motivos or [],
            "erro": i.erro,
        },
        identidade=i.identidade or {},
        resultado={
            "hipotese": i.hipotese,
            "conclusao": i.conclusao,
            "cst": i.final_cst or i.cst_sugerido,
            "cclasstrib": i.final_cclasstrib or i.cclasstrib_sugerido,
            "perc_red_ibs": float(i.perc_red_ibs) if i.perc_red_ibs is not None else None,
            "perc_red_cbs": float(i.perc_red_cbs) if i.perc_red_cbs is not None else None,
            "imposto_seletivo": i.is_situacao,
            "tratamento": i.tipo_tratamento,
            "dispositivo": i.final_dispositivo or i.dispositivo_legal,
            "confianca_global": i.confianca_global,
            "perfil_versao": i.perfil_versao,
        },
        dimensoes=[{"chave": k, **dims[k]} for k, _ in DIMENSOES if k in dims],
        fatos_usados=i.fatos_usados or [],
        fatos_do_item=[_fato_out(f) for f in fatos_item],
        fundamentos=fundamentos,
        hipoteses=registro.get("hipoteses_avaliadas", []),
        perguntas=i.perguntas or [],
        tese=(
            {
                "id": str(tese.id),
                "codigo": formatar_codigo(tese.tipo_codigo, tese.codigo),
                "entendimento": (tese.resultado or {}).get("entendimento"),
                "observacoes": (tese.resultado or {}).get("observacoes"),
                "conflitos": (tese.resultado or {}).get("conflitos", []),
                "imposto_seletivo": (tese.resultado or {}).get("imposto_seletivo"),
                "modelo": tese.modelo,
                "prompt": tese.prompt_versao,
                "criada_em": tese.created_at.isoformat(),
                "aprovada_por": tese.aprovada_por_email,
                "fatos_empresa": tese.fatos_empresa,
            }
            if tese
            else None
        ),
        versoes_perfil=[
            {
                "versao": p.versao,
                "ativo": p.ativo,
                "status": p.status,
                "cst": p.cst,
                "cclasstrib": p.cclasstrib,
                "hipotese": p.hipotese,
                "imposto_seletivo": p.imposto_seletivo,
                "confianca_global": p.confianca_global,
                "motivo": p.motivo_versao,
                "vigencia": p.vigencia.isoformat(),
                "em": p.created_at.isoformat(),
            }
            for p in perfis
        ],
        base_normativa=base,
        transicao=transicao.como_dict(a.data_referencia),
        revisoes=[
            {
                "acao": r.acao,
                "usuario": r.user_email,
                "comentario": r.comentario,
                "em": r.created_at.isoformat(),
            }
            for r in revisoes
        ],
        chamadas_ia=[
            {
                "no": c.no,
                "modelo": c.modelo,
                "prompt": c.prompt_versao,
                "modo": c.modo,
                "tokens_entrada": c.tokens_entrada,
                "tokens_saida": c.tokens_saida,
                "custo_usd": float(c.custo_usd or 0),
                "compartilhada": c.item_id is None,
                "em": c.created_at.isoformat(),
            }
            for c in calls
        ],
    )


# ================================================================ refazer com o modelo atual ==
class RefazerOut(BaseModel):
    teses: int
    itens: int
    aprovados_mantidos: int
    modelo: str
    mensagem: str


async def _refazer(session: Any, principal: Principal, a: Audit, teses: list[TaxThesis]) -> RefazerOut:
    """Substitui os pareceres (ficam no histórico) e reprocessa os itens desta auditoria que os usavam.

    O Jurista estuda de novo com o modelo escolhido agora em "Modelos de IA". A identificação dos itens
    é reaproveitada (mesma resposta, sem custo) quando o modelo do Identificador não mudou.
    """
    if a.status not in (StatusAuditoria.CONCLUIDA, StatusAuditoria.PROCESSANDO):
        raise Conflito("Só é possível refazer pareceres de auditorias em andamento ou concluídas.")
    agentes = await run_in_threadpool(catalogo_ia.agentes_configurados)
    jurista = agentes["jurista"]
    ids_teses = [t.id for t in teses if t.status == "concluida"]
    for t in teses:
        if t.status != "concluida":
            continue
        sufixo = f":sub:{uuid.uuid4().hex[:8]}"
        t.status = "substituida"
        t.chave = f"{t.chave[:100]}{sufixo}"
        if t.llm_call_id:
            call = await session.get(LlmCall, t.llm_call_id)
            if call is not None:
                # Libera a chave de idempotência: a nova chamada não pode reaproveitar a resposta antiga.
                call.chave_idempotencia = f"{call.chave_idempotencia[:180]}{sufixo}"
    itens = list(
        await session.scalars(
            select(AuditItem).where(AuditItem.audit_id == a.id, AuditItem.thesis_id.in_(ids_teses or [uuid.uuid4()]))
        )
    )
    reprocessar: list[uuid.UUID] = []
    mantidos = 0
    for i in itens:
        if i.revisao_status == StatusRevisao.APROVADO and not i.aprovado_automaticamente:
            mantidos += 1  # decisão de uma pessoa não é desfeita por reprocessamento
            continue
        if i.revisao_status == StatusRevisao.APROVADO:
            i.revisao_status = StatusRevisao.PENDENTE
        i.tentativa += 1
        i.status, i.etapa, i.motivos, i.perguntas = StatusItem.PENDENTE, None, [], []
        i.aprovado_automaticamente = False
        reprocessar.append(i.id)
    conf = dict(a.configuracao or {})
    conf["modelos"] = {**(conf.get("modelos") or {}), "jurista": jurista["modelo"]}
    conf["esforcos"] = {**(conf.get("esforcos") or {}), "jurista": jurista["esforco"]}
    a.configuracao = conf
    if reprocessar:
        a.status = StatusAuditoria.PROCESSANDO
        a.modo = "tempo_real"
    await registrar(
        session,
        principal,
        Acao.TESE_REFEITA,
        entidade="auditoria",
        entidade_id=a.id,
        detalhes={"teses": [str(t) for t in ids_teses], "modelo": jurista["modelo"], "itens": len(reprocessar)},
    )
    await session.commit()
    if reprocessar:
        enfileirar_itens(a.id, a.org_id, reprocessar)
    info = await run_in_threadpool(catalogo_ia.info_modelo, jurista["modelo"])
    nome = info.nome if info else jurista["modelo"]
    msg = f"{len(ids_teses)} parecer(es) serão refeitos com {nome}; {len(reprocessar)} item(ns) em reprocessamento."
    if mantidos:
        msg += f" {mantidos} item(ns) aprovados por pessoas foram mantidos."
    return RefazerOut(
        teses=len(ids_teses), itens=len(reprocessar), aprovados_mantidos=mantidos, modelo=nome, mensagem=msg
    )


class RefazerIn(BaseModel):
    audit_id: uuid.UUID


@router.post("/teses/{tese_id}/refazer", response_model=RefazerOut)
async def refazer_tese(tese_id: uuid.UUID, dados: RefazerIn, principal: Revisar, session: SessionDep) -> RefazerOut:
    """Refaz o parecer desta família com o modelo atual do Jurista (gera custo de IA)."""
    t = await session.get(TaxThesis, tese_id)
    if t is None:
        raise NaoEncontrado("Tese não encontrada.")
    a = await _carregar_auditoria(session, principal, dados.audit_id)
    return await _refazer(session, principal, a, [t])


@router.post("/auditorias/{audit_id}/teses/refazer", response_model=RefazerOut)
async def refazer_teses_auditoria(audit_id: uuid.UUID, principal: Revisar, session: SessionDep) -> RefazerOut:
    """Refaz todos os pareceres usados por esta auditoria com o modelo atual do Jurista."""
    a = await _carregar_auditoria(session, principal, audit_id)
    ids = set(
        await session.scalars(
            select(AuditItem.thesis_id).where(AuditItem.audit_id == audit_id, AuditItem.thesis_id.is_not(None))
        )
    )
    teses = list(await session.scalars(select(TaxThesis).where(TaxThesis.id.in_(ids or {uuid.uuid4()}))))
    return await _refazer(session, principal, a, teses)
