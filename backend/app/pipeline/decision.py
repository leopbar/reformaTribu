"""Decisão final do status de um item (função pura, testável).

Regras:
- Qualquer motivo bloqueante → Análise humana.
- Confirmado: código atual coerente e igual ao final, enquadramento definido sem pendências,
  CST/cClassTrib atuais (se informados) iguais aos sugeridos, confiança ≥ limiar de confirmação.
- Corrigido: há correção (código e/ou CST/cClassTrib), enquadramento definido, concordância entre
  as etapas (o escalonamento é obrigatório quando o código muda) e confiança ≥ limiar de correção.
- Todo o resto → Análise humana, sempre com ao menos um motivo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.pipeline.confidence import Componentes, sinal_busca
from app.pipeline.reasons import BLOQUEANTES, Motivo


@dataclass
class EntradaDecisao:
    motivos: list[str]
    codigo_atual: str | None  # código informado (normalizado) ou provável com zero restaurado
    codigo_atual_valido: bool  # existe, é folha e está vigente
    codigo_final: str | None
    memoria: bool
    julgamento: dict[str, Any] | None
    julgamento_valido: bool
    escalonado: bool
    escalonamento: dict[str, Any] | None
    escalonamento_valido: bool
    posicao_busca: int | None
    enquadramento: dict[str, Any]
    cst_atual: str | None
    cclasstrib_atual: str | None
    descricao_curta: bool
    busca_semantica: bool
    limiar_confirmado: float
    limiar_corrigido: float
    is_exige_analise: bool


@dataclass
class Decisao:
    status: str
    motivos: list[str]
    confianca: float
    componentes: dict[str, float]
    observacoes: list[str] = field(default_factory=list)


def _conf(d: dict[str, Any] | None) -> float:
    return float(d.get("confianca", 0.0)) if d else 0.0


def decidir(e: EntradaDecisao) -> Decisao:
    motivos = list(dict.fromkeys(e.motivos))
    enq = e.enquadramento or {}

    def add(m: str) -> None:
        if m not in motivos:
            motivos.append(m)

    # --- componentes de confiança -------------------------------------------------------------
    if e.memoria:
        c_modelo, concordancia = 0.99, 1.0
    elif e.julgamento_valido:
        c_prim = _conf(e.julgamento)
        if e.escalonado and e.escalonamento_valido:
            c_esc = _conf(e.escalonamento)
            mesmo = (e.escalonamento or {}).get("codigo_sugerido") == (e.julgamento or {}).get("codigo_sugerido")
            c_modelo = 0.4 * c_prim + 0.6 * c_esc
            concordancia = 1.0 if mesmo else 0.0
            if not mesmo:
                add(Motivo.DIVERGENCIA_ENTRE_MODELOS)
        elif e.escalonado:
            c_modelo, concordancia = c_prim, 0.0
            add(Motivo.FALHA_NA_ANALISE_IA)
        else:
            c_modelo, concordancia = c_prim, 1.0
    else:
        c_modelo, concordancia = 0.0, 0.0

    julg = e.escalonamento if (e.escalonado and e.escalonamento_valido) else e.julgamento
    if julg is not None and not julg.get("descricao_suficiente", True):
        add(Motivo.DESCRICAO_INSUFICIENTE)
    if julg is not None and julg.get("nenhum_candidato_serve"):
        add(Motivo.NENHUM_CANDIDATO_ADEQUADO)
    if julg is not None and julg.get("ncm_atual_coerente") is False and e.codigo_atual:
        add(Motivo.NCM_INCOERENTE_COM_DESCRICAO)

    c_desc = 0.2 if Motivo.DESCRICAO_INSUFICIENTE in motivos else (0.6 if e.descricao_curta else 1.0)
    c_estr = 1.0 if (e.codigo_atual is None or e.codigo_atual_valido) else 0.8
    c_regra = float(enq.get("certeza", 0.0))
    c_busca = 1.0 if e.memoria else sinal_busca(e.posicao_busca)
    if not e.busca_semantica and not e.memoria:
        c_busca = min(c_busca, 0.7)
    comp = Componentes(
        modelo=c_modelo, busca=c_busca, concordancia=concordancia, regra=c_regra, descricao=c_desc, estrutura=c_estr
    )
    confianca = comp.final()

    # --- motivos do enquadramento --------------------------------------------------------------
    for m in enq.get("motivos", []):
        add(m)
    if not e.is_exige_analise and Motivo.SUJEITO_A_IMPOSTO_SELETIVO in motivos:
        bloqueantes = BLOQUEANTES
    else:
        bloqueantes = BLOQUEANTES | {Motivo.SUJEITO_A_IMPOSTO_SELETIVO}

    cst_sug, cct_sug = enq.get("cst"), enq.get("cclasstrib")
    divergencia_cst = bool(
        (e.cst_atual and cst_sug and e.cst_atual != cst_sug)
        or (e.cclasstrib_atual and cct_sug and e.cclasstrib_atual != cct_sug)
    )
    if divergencia_cst:
        add(Motivo.CST_CCLASSTRIB_ATUAL_DIVERGENTE)

    enquadramento_definido = bool(cct_sug) and not enq.get("perguntas")
    if e.codigo_final is None:
        if not any(
            m in motivos
            for m in (
                Motivo.NENHUM_CANDIDATO_ADEQUADO,
                Motivo.FALHA_NA_ANALISE_IA,
                Motivo.CODIGO_SUGERIDO_INVALIDO,
                Motivo.BASE_REFERENCIA_INCOMPLETA,
                Motivo.ORCAMENTO_ESGOTADO,
            )
        ):
            add(Motivo.NENHUM_CANDIDATO_ADEQUADO)
        return Decisao("analise_humana", motivos, confianca, comp.como_dict())

    if any(m in bloqueantes for m in motivos):
        return Decisao("analise_humana", motivos, confianca, comp.como_dict())

    if not enquadramento_definido:
        add(Motivo.BASE_REFERENCIA_INCOMPLETA)
        return Decisao("analise_humana", motivos, confianca, comp.como_dict())

    codigo_mudou = e.codigo_atual is None or e.codigo_final != e.codigo_atual or not e.codigo_atual_valido
    if not codigo_mudou and not divergencia_cst:
        coerente = e.memoria or (julg is not None and julg.get("ncm_atual_coerente") is True)
        if coerente and confianca >= e.limiar_confirmado:
            return Decisao("confirmado", motivos, confianca, comp.como_dict())
        add(Motivo.BAIXA_CONFIANCA)
        return Decisao("analise_humana", motivos, confianca, comp.como_dict())

    # Há correção. Mudança de código exige concordância com o escalonamento (ou memória aprovada).
    if codigo_mudou and not e.memoria and not (e.escalonado and e.escalonamento_valido and concordancia == 1.0):
        add(Motivo.BAIXA_CONFIANCA)
        return Decisao("analise_humana", motivos, confianca, comp.como_dict())
    if confianca >= e.limiar_corrigido:
        return Decisao("corrigido", motivos, confianca, comp.como_dict())
    add(Motivo.BAIXA_CONFIANCA)
    return Decisao("analise_humana", motivos, confianca, comp.como_dict())
