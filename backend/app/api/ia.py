"""Administração de IA (superadministrador): chaves das plataformas, catálogo de modelos e modelo de cada agente."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from starlette.concurrency import run_in_threadpool

from app.core.audit_trail import Acao, registrar
from app.core.deps import RefSessionDep, SuperAdminDep
from app.core.errors import AppError, NaoEncontrado
from app.ingest import estimate
from app.llm import catalogo, provedores
from app.llm.pricing import custo_chamada
from app.models import LlmAgent, LlmModel, LlmProvider

router = APIRouter(prefix="/ia", tags=["administração de IA"])


def _mudou() -> None:
    catalogo.limpar_cache()


# ================================================================================ chaves ==
class ProvedorOut(BaseModel):
    provedor: str
    nome: str
    ativo: bool
    tem_chave: bool
    chave_final: str | None
    chave_no_servidor: bool  # há uma chave de reserva no arquivo .env
    base_url: str
    base_url_padrao: str
    testado_em: datetime | None
    teste_ok: bool | None
    teste_mensagem: str | None
    lote: str
    site: str
    modelos_ativos: int
    atualizado_por: str | None
    updated_at: datetime


class ProvedorIn(BaseModel):
    chave: str | None = Field(None, min_length=10, max_length=400)
    remover_chave: bool = False
    ativo: bool | None = None
    base_url: str | None = Field(None, max_length=300)


class TesteOut(BaseModel):
    ok: bool
    mensagem: str


async def _provedores(session: Any) -> list[ProvedorOut]:
    ativos = dict(
        (await session.execute(text("SELECT provedor, count(*) FROM llm_modelos WHERE ativo GROUP BY 1"))).all()
    )
    saida = []
    for p in await session.scalars(select(LlmProvider).order_by(LlmProvider.provedor)):
        meta = catalogo.PROVEDORES.get(p.provedor, {})
        saida.append(
            ProvedorOut(
                provedor=p.provedor,
                nome=p.nome,
                ativo=p.ativo,
                tem_chave=p.chave_cifrada is not None,
                chave_final=p.chave_final,
                chave_no_servidor=catalogo._chave_env(p.provedor) is not None,
                base_url=p.base_url or meta.get("base_url", ""),
                base_url_padrao=meta.get("base_url", ""),
                testado_em=p.testado_em,
                teste_ok=p.teste_ok,
                teste_mensagem=p.teste_mensagem,
                lote=meta.get("lote", ""),
                site=meta.get("site", ""),
                modelos_ativos=int(ativos.get(p.provedor, 0)),
                atualizado_por=p.atualizado_por,
                updated_at=p.updated_at,
            )
        )
    return saida


async def _provedor(session: Any, provedor: str) -> LlmProvider:
    p = await session.get(LlmProvider, provedor)
    if p is None:
        raise NaoEncontrado("Plataforma não encontrada.")
    return p  # type: ignore[no-any-return]


@router.get("/provedores", response_model=list[ProvedorOut])
async def listar_provedores(principal: SuperAdminDep, session: RefSessionDep) -> list[ProvedorOut]:
    return await _provedores(session)


@router.put("/provedores/{provedor}", response_model=list[ProvedorOut])
async def salvar_provedor(
    provedor: str, dados: ProvedorIn, principal: SuperAdminDep, session: RefSessionDep
) -> list[ProvedorOut]:
    """Cadastra ou troca a chave (guardada cifrada; nunca devolvida), ativa/desativa e ajusta o endereço."""
    p = await _provedor(session, provedor)
    detalhes: dict[str, Any] = {}
    if dados.chave:
        chave = dados.chave.strip()
        await session.execute(
            text("UPDATE llm_provedores SET chave_cifrada = pgp_sym_encrypt(:k, :s) WHERE provedor = :p"),
            {"k": chave, "s": catalogo.segredo_chaves(), "p": provedor},
        )
        p.chave_final = chave[-4:]
        p.teste_ok, p.teste_mensagem, p.testado_em = None, None, None
        detalhes["chave"] = f"nova chave terminada em {chave[-4:]}"
    elif dados.remover_chave:
        p.chave_cifrada, p.chave_final = None, None
        p.teste_ok, p.teste_mensagem, p.testado_em = None, None, None
        detalhes["chave"] = "removida"
    if dados.ativo is not None:
        p.ativo = dados.ativo
        detalhes["ativo"] = dados.ativo
    if dados.base_url is not None:
        p.base_url = dados.base_url.strip() or None
        detalhes["base_url"] = p.base_url
    p.atualizado_por = principal.email
    p.updated_at = datetime.now(UTC)
    await registrar(
        session,
        principal,
        Acao.IA_CHAVE,
        entidade="plataforma_ia",
        entidade_id=provedor,
        detalhes=detalhes,
        plataforma=True,
    )
    await session.flush()
    _mudou()
    return await _provedores(session)


class TesteIn(BaseModel):
    chave: str | None = Field(None, max_length=400)


@router.post("/provedores/{provedor}/testar", response_model=TesteOut)
async def testar_provedor(provedor: str, dados: TesteIn, principal: SuperAdminDep, session: RefSessionDep) -> TesteOut:
    """Confere a chave (a informada ou a cadastrada) listando os modelos da plataforma. Não gasta tokens."""
    p = await _provedor(session, provedor)
    base = p.base_url or catalogo.PROVEDORES.get(provedor, {}).get("base_url", "")
    chave = (dados.chave or "").strip()
    if not chave and p.chave_cifrada is not None:
        chave = str(
            await session.scalar(
                text("SELECT pgp_sym_decrypt(chave_cifrada, :s) FROM llm_provedores WHERE provedor = :p"),
                {"s": catalogo.segredo_chaves(), "p": provedor},
            )
        )
    if not chave:
        chave = catalogo._chave_env(provedor) or ""
    if not chave:
        return TesteOut(ok=False, mensagem="Nenhuma chave cadastrada para testar.")
    ok, msg = await run_in_threadpool(provedores.testar, provedor, chave, base)
    if not dados.chave:
        p.testado_em, p.teste_ok, p.teste_mensagem = datetime.now(UTC), ok, msg
    return TesteOut(ok=ok, mensagem=msg)


# =============================================================================== modelos ==
class ModeloIAOut(BaseModel):
    modelo: str
    provedor: str
    provedor_nome: str
    nome: str
    preco_entrada: float
    preco_saida: float
    preco_cache_leitura: float
    mult_cache_escrita: float
    suporta_lote: bool
    suporta_esforco: bool
    ativo: bool
    notas: str | None
    em_uso_por: list[str]
    plataforma_pronta: bool  # plataforma ativa e com chave


class ModeloIn(BaseModel):
    nome: str | None = Field(None, min_length=2, max_length=120)
    preco_entrada: float | None = Field(None, ge=0, le=1000)
    preco_saida: float | None = Field(None, ge=0, le=1000)
    preco_cache_leitura: float | None = Field(None, ge=0, le=1000)
    mult_cache_escrita: float | None = Field(None, ge=0, le=5)
    suporta_lote: bool | None = None
    suporta_esforco: bool | None = None
    ativo: bool | None = None
    notas: str | None = Field(None, max_length=1000)


class NovoModeloIn(ModeloIn):
    modelo: str = Field(min_length=3, max_length=80, pattern=r"^[A-Za-z0-9._:-]+$")
    provedor: str
    nome: str = Field(min_length=2, max_length=120)
    preco_entrada: float = Field(ge=0, le=1000)
    preco_saida: float = Field(ge=0, le=1000)


def _prontos(provs: list[LlmProvider]) -> set[str]:
    return {p.provedor for p in provs if p.ativo and (p.chave_cifrada is not None or catalogo._chave_env(p.provedor))}


async def _modelos(session: Any) -> list[ModeloIAOut]:
    provs = list(await session.scalars(select(LlmProvider)))
    nomes = {p.provedor: p.nome for p in provs}
    prontos = _prontos(provs)
    uso: dict[str, list[str]] = {}
    for a in await session.scalars(select(LlmAgent)):
        uso.setdefault(a.modelo, []).append(catalogo.AGENTES.get(a.agente, {}).get("nome", a.agente))
    ordem = {"anthropic": 0, "openai": 1, "deepseek": 2}
    rows = sorted(await session.scalars(select(LlmModel)), key=lambda m: (ordem.get(m.provedor, 9), m.preco_saida))
    return [
        ModeloIAOut(
            modelo=m.modelo,
            provedor=m.provedor,
            provedor_nome=nomes.get(m.provedor, m.provedor),
            nome=m.nome,
            preco_entrada=float(m.preco_entrada),
            preco_saida=float(m.preco_saida),
            preco_cache_leitura=float(m.preco_cache_leitura),
            mult_cache_escrita=float(m.mult_cache_escrita),
            suporta_lote=m.suporta_lote,
            suporta_esforco=m.suporta_esforco,
            ativo=m.ativo,
            notas=m.notas,
            em_uso_por=uso.get(m.modelo, []),
            plataforma_pronta=m.provedor in prontos,
        )
        for m in rows
    ]


@router.get("/modelos", response_model=list[ModeloIAOut])
async def listar_modelos(principal: SuperAdminDep, session: RefSessionDep) -> list[ModeloIAOut]:
    return await _modelos(session)


def _aplicar(m: LlmModel, dados: ModeloIn) -> dict[str, Any]:
    mudancas = dados.model_dump(exclude_unset=True, exclude={"modelo", "provedor"})
    for campo, valor in mudancas.items():
        setattr(m, campo, Decimal(str(valor)) if isinstance(valor, float) else valor)
    return mudancas


@router.put("/modelos/{modelo}", response_model=list[ModeloIAOut])
async def salvar_modelo(
    modelo: str, dados: ModeloIn, principal: SuperAdminDep, session: RefSessionDep
) -> list[ModeloIAOut]:
    m = await session.get(LlmModel, modelo)
    if m is None:
        raise NaoEncontrado("Modelo não encontrado.")
    if dados.ativo is False and await session.scalar(select(LlmAgent.agente).where(LlmAgent.modelo == modelo)):
        raise AppError(
            "Este modelo está em uso por um agente.",
            acao="Escolha outro modelo para o agente antes de desativar este.",
            codigo="modelo_em_uso",
        )
    mudancas = _aplicar(m, dados)
    m.atualizado_por = principal.email
    m.updated_at = datetime.now(UTC)
    await registrar(
        session,
        principal,
        Acao.IA_MODELO,
        entidade="modelo_ia",
        entidade_id=modelo,
        detalhes=mudancas,
        plataforma=True,
    )
    await session.flush()
    _mudou()
    return await _modelos(session)


@router.post("/modelos", response_model=list[ModeloIAOut], status_code=201)
async def criar_modelo(dados: NovoModeloIn, principal: SuperAdminDep, session: RefSessionDep) -> list[ModeloIAOut]:
    """Cadastra um modelo que ainda não está no catálogo (ex.: lançamento novo de uma plataforma)."""
    if await session.get(LlmProvider, dados.provedor) is None:
        raise NaoEncontrado("Plataforma não encontrada.")
    if await session.get(LlmModel, dados.modelo) is not None:
        raise AppError("Este modelo já está no catálogo.", codigo="modelo_existente")
    m = LlmModel(
        modelo=dados.modelo,
        provedor=dados.provedor,
        nome=dados.nome,
        preco_entrada=Decimal(str(dados.preco_entrada)),
        preco_saida=Decimal(str(dados.preco_saida)),
        preco_cache_leitura=Decimal(str(dados.preco_cache_leitura if dados.preco_cache_leitura is not None else 0)),
        mult_cache_escrita=Decimal(str(dados.mult_cache_escrita if dados.mult_cache_escrita is not None else 1)),
        suporta_lote=bool(dados.suporta_lote) and dados.provedor == "anthropic",
        suporta_esforco=bool(dados.suporta_esforco),
        ativo=dados.ativo if dados.ativo is not None else True,
        notas=dados.notas,
        atualizado_por=principal.email,
    )
    session.add(m)
    await registrar(
        session,
        principal,
        Acao.IA_MODELO,
        entidade="modelo_ia",
        entidade_id=dados.modelo,
        detalhes={"criado": True, "provedor": dados.provedor},
        plataforma=True,
    )
    await session.flush()
    _mudou()
    return await _modelos(session)


# =============================================================================== agentes ==
class OpcaoModelo(BaseModel):
    modelo: str
    nome: str
    provedor: str
    provedor_nome: str
    posicao: int | None  # posição no ranking recomendado (None = outros modelos ativos)
    motivo: str | None
    preco_entrada: float
    preco_saida: float
    custo_1000_chamadas: float  # custo típico de 1.000 chamadas deste agente com o modelo
    disponivel: bool
    aviso: str | None


class AgenteOut(BaseModel):
    agente: str
    nome: str
    funcao: str
    exige: str
    modelo: str
    esforco: str
    esforcos: list[str]
    recomendados: list[OpcaoModelo]
    outros: list[OpcaoModelo]
    atualizado_por: str | None
    updated_at: datetime | None


class AgenteIn(BaseModel):
    modelo: str
    esforco: str = Field("medium", pattern="^(low|medium|high)$")


# Tamanho típico de uma chamada de cada agente (tokens de sistema + usuário, e de saída).
TAMANHOS = {
    "identificador": ("julgar_coerencia", estimate.USUARIO_PRINCIPAL, estimate.SAIDA_PRINCIPAL),
    "segundo_parecer": ("escalar", estimate.USUARIO_ESCALONAMENTO, estimate.SAIDA_ESCALONAMENTO),
    "navegador": ("navegar_arvore", estimate.USUARIO_NAVEGACAO, estimate.SAIDA_NAVEGACAO),
    "jurista": ("investigar_enquadramento", estimate.USUARIO_INVESTIGACAO, estimate.SAIDA_INVESTIGACAO),
    "leitor_fatos": ("extrair_fatos", estimate.USUARIO_FATOS, estimate.SAIDA_FATOS),
    "abreviacoes": ("expandir_abreviacoes", 150, 150),
}


def _custo_1000(agente: str, modelo: str) -> float:
    prompt, usuario, saida = TAMANHOS[agente]
    try:
        sistema = estimate._tokens_sistema(prompt)
    except Exception:
        sistema = 800
    return round(float(custo_chamada(modelo, usuario, saida, 0, sistema)) * 1000, 2)


async def _agentes(session: Any) -> list[AgenteOut]:
    provs = list(await session.scalars(select(LlmProvider)))
    nomes = {p.provedor: p.nome for p in provs}
    prontos = _prontos(provs)
    modelos = {m.modelo: m for m in await session.scalars(select(LlmModel))}
    salvos = {a.agente: a for a in await session.scalars(select(LlmAgent))}

    def opcao(agente: str, m: LlmModel, posicao: int | None, motivo: str | None) -> OpcaoModelo:
        aviso = None
        if not m.ativo:
            aviso = "Modelo desativado no catálogo."
        elif m.provedor not in prontos:
            aviso = f"Falta cadastrar a chave da {nomes.get(m.provedor, m.provedor)}."
        return OpcaoModelo(
            modelo=m.modelo,
            nome=m.nome,
            provedor=m.provedor,
            provedor_nome=nomes.get(m.provedor, m.provedor),
            posicao=posicao,
            motivo=motivo,
            preco_entrada=float(m.preco_entrada),
            preco_saida=float(m.preco_saida),
            custo_1000_chamadas=_custo_1000(agente, m.modelo),
            disponivel=m.ativo and m.provedor in prontos,
            aviso=aviso,
        )

    saida = []
    for chave, meta in catalogo.AGENTES.items():
        a = salvos.get(chave)
        recomendados = [
            opcao(chave, modelos[mod], i, motivo)
            for i, (mod, motivo) in enumerate(catalogo.RECOMENDACOES.get(chave, []), start=1)
            if mod in modelos and modelos[mod].ativo
        ]
        ja = {o.modelo for o in recomendados}
        outros = sorted(
            (opcao(chave, m, None, None) for m in modelos.values() if m.ativo and m.modelo not in ja),
            key=lambda o: (o.provedor, o.custo_1000_chamadas),
        )
        saida.append(
            AgenteOut(
                agente=chave,
                nome=meta["nome"],
                funcao=meta["funcao"],
                exige=meta["exige"],
                modelo=a.modelo if a else meta["padrao"],
                esforco=a.esforco if a else meta["esforco"],
                esforcos=list(catalogo.ESFORCOS),
                recomendados=recomendados,
                outros=outros,
                atualizado_por=a.atualizado_por if a else None,
                updated_at=a.updated_at if a else None,
            )
        )
    return saida


@router.get("/agentes", response_model=list[AgenteOut])
async def listar_agentes(principal: SuperAdminDep, session: RefSessionDep) -> list[AgenteOut]:
    return await _agentes(session)


@router.put("/agentes/{agente}", response_model=list[AgenteOut])
async def salvar_agente(
    agente: str, dados: AgenteIn, principal: SuperAdminDep, session: RefSessionDep
) -> list[AgenteOut]:
    """Escolhe o modelo do agente. Vale para as próximas auditorias (as em andamento mantêm o seu)."""
    if agente not in catalogo.AGENTES:
        raise NaoEncontrado("Agente não encontrado.")
    m = await session.get(LlmModel, dados.modelo)
    if m is None or not m.ativo:
        raise AppError("Escolha um modelo ativo do catálogo.", codigo="modelo_invalido")
    a = await session.get(LlmAgent, agente)
    anterior = a.modelo if a else None
    if a is None:
        a = LlmAgent(agente=agente, modelo=dados.modelo, esforco=dados.esforco)
        session.add(a)
    a.modelo, a.esforco = dados.modelo, dados.esforco
    a.atualizado_por = principal.email
    a.updated_at = datetime.now(UTC)
    await registrar(
        session,
        principal,
        Acao.IA_AGENTE,
        entidade="agente_ia",
        entidade_id=agente,
        detalhes={"de": anterior, "para": dados.modelo, "esforco": dados.esforco},
        plataforma=True,
    )
    await session.flush()
    _mudou()
    return await _agentes(session)
