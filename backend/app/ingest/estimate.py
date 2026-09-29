"""Estimativa de custo e tempo antes de iniciar uma auditoria."""

from __future__ import annotations

import math
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.llm import catalogo
from app.llm.pricing import custo_chamada
from app.llm.prompts import carregar
from app.models import AuditItem, LlmCall

# Tamanhos médios por chamada (tokens). O bloco de sistema vai para o cache após a 1ª chamada.
USUARIO_PRINCIPAL = 1600
SAIDA_PRINCIPAL = 1400  # inclui raciocínio adaptativo
USUARIO_ESCALONAMENTO = 2100
SAIDA_ESCALONAMENTO = 2600
TAXA_ESCALONAMENTO_PADRAO = 0.4  # piloto de supermercado: cerca de metade dos itens
# Investigação jurídica por família (uma por código NCM/NBS): pacote de evidências grande, saída longa.
USUARIO_INVESTIGACAO = 8000
SAIDA_INVESTIGACAO = 5000
# Fatos do item (modelo leve), só nas famílias com condição que depende do item.
USUARIO_FATOS = 700
SAIDA_FATOS = 250
TAXA_ITENS_COM_FATOS = 0.3
# Busca guiada pela árvore oficial (itens sem código): 2 a 3 passos curtos por item.
USUARIO_NAVEGACAO = 2500
SAIDA_NAVEGACAO = 350
PASSOS_NAVEGACAO = 3
# Parte dos itens com NCM/NBS válido que a busca confirma sem IA (o NCM do ERP em 1º nas duas buscas).
# Medido no piloto de supermercado: quase nunca acontece com a busca atual.
TAXA_CONFIRMACAO_SEM_IA = 0.1
# Itens sem código válido: a IA sugere um código; muitos caem em famílias já vistas.
TAXA_FAMILIAS_SEM_CODIGO = 0.7


def _tokens_sistema(nome: str) -> int:
    return math.ceil(len(carregar(nome).texto) / 3.2)


def taxa_escalonamento_historica(session: Session, org_id: Any) -> float:
    total = session.scalar(
        select(func.count())
        .select_from(LlmCall)
        .where(LlmCall.org_id == org_id, LlmCall.no == "julgar_coerencia", LlmCall.status == "concluida")
    )
    esc = session.scalar(
        select(func.count())
        .select_from(LlmCall)
        .where(LlmCall.org_id == org_id, LlmCall.no == "escalar", LlmCall.status == "concluida")
    )
    if not total or total < 50:
        return TAXA_ESCALONAMENTO_PADRAO
    return min(1.0, (esc or 0) / total)


def _custo_agente(modelo: str, chamadas: int, usuario: int, saida: int, sistema: int, lote: bool) -> Decimal:
    """A 1ª chamada escreve o bloco de sistema no cache; as demais o leem."""
    if chamadas <= 0:
        return Decimal(0)
    primeira = custo_chamada(modelo, usuario, saida, sistema, 0, lote)
    demais = custo_chamada(modelo, usuario, saida, 0, sistema, lote) * (chamadas - 1)
    return primeira + demais


def estimar(
    previsao: dict[str, Any],
    taxa_escalonamento: float,
    lote: bool,
    modelos: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Custo e tempo previstos, com o preço do modelo escolhido para cada agente (tela "Modelos de IA").

    O lote dá 50% de desconto só nos modelos que têm Batch API (Anthropic); os demais saem em tempo real.
    """
    modelos = modelos or {k: v["modelo"] for k, v in catalogo.agentes_configurados().items()}
    n_com_ia = int(previsao.get("itens_com_ia") or 0)
    familias = int(previsao.get("familias_novas") or 0)
    n_esc = math.ceil(n_com_ia * taxa_escalonamento)
    n_fatos = math.ceil(n_com_ia * TAXA_ITENS_COM_FATOS)
    n_nav = PASSOS_NAVEGACAO * int(previsao.get("sem_codigo_valido") or 0)
    plano = [
        ("identificador", n_com_ia, USUARIO_PRINCIPAL, SAIDA_PRINCIPAL, "julgar_coerencia"),
        ("segundo_parecer", n_esc, USUARIO_ESCALONAMENTO, SAIDA_ESCALONAMENTO, "escalar"),
        ("navegador", n_nav, USUARIO_NAVEGACAO, SAIDA_NAVEGACAO, "navegar_arvore"),
        ("jurista", familias, USUARIO_INVESTIGACAO, SAIDA_INVESTIGACAO, "investigar_enquadramento"),
        ("leitor_fatos", n_fatos, USUARIO_FATOS, SAIDA_FATOS, "extrair_fatos"),
    ]
    agentes: list[dict[str, Any]] = []
    total = Decimal(0)
    entrada_total = saida_total = 0
    for agente, chamadas, usuario, saida, prompt in plano:
        modelo = modelos.get(agente) or catalogo.AGENTES[agente]["padrao"]
        info = catalogo.info_modelo(modelo)
        com_lote = lote and catalogo.suporta_lote(modelo)
        sistema = _tokens_sistema(prompt)
        custo = _custo_agente(modelo, chamadas, usuario, saida, sistema, com_lote)
        total += custo
        entrada_total += chamadas * (usuario + sistema)
        saida_total += chamadas * saida
        agentes.append(
            {
                "agente": agente,
                "nome": catalogo.AGENTES[agente]["nome"],
                "modelo": modelo,
                "modelo_nome": info.nome if info else modelo,
                "provedor": catalogo.provedor_de(modelo),
                "chamadas": chamadas,
                "custo_usd": round(float(custo), 4),
                "lote": com_lote,
            }
        )
    sem_lote = sorted({a["modelo_nome"] for a in agentes if lote and not a["lote"] and a["chamadas"]})
    s = get_settings()
    if lote:
        tempo_min = (30, 24 * 60)
        texto_tempo = "Em lote: normalmente até 1 hora; no máximo 24 horas."
    else:
        seg = n_com_ia * 9 / 4 + n_esc * 14 / 4 + familias * 45 / 4  # 4 processos em paralelo
        tempo_min = (max(1, math.ceil(seg / 60 * 0.7)), max(1, math.ceil(seg / 60 * 1.5)))
        texto_tempo = f"Cerca de {tempo_min[0]} a {tempo_min[1]} minutos."
    total_f = float(total)
    return {
        "itens_com_ia": n_com_ia,
        "escalonamentos_estimados": n_esc,
        "familias_estimadas": familias,
        "taxa_escalonamento": round(taxa_escalonamento, 3),
        "tokens_entrada_estimados": entrada_total,
        "tokens_saida_estimados": saida_total,
        "custo_usd_estimado": round(total_f, 2),
        "custo_usd_faixa": [round(total_f * 0.6, 2), round(total_f * 1.6, 2)],
        "modo": "lote" if lote else "tempo_real",
        "limite_lote": s.llm_batch_min_itens,
        "tempo_minutos": list(tempo_min),
        "tempo_texto": texto_tempo,
        "agentes": agentes,
        "modelos": {a["agente"]: a["modelo"] for a in agentes},
        "sem_lote": sem_lote,
        "previsao": previsao,
        "observacao": "Estimativa aproximada. O custo real de cada chamada é registrado e exibido durante a auditoria.",
    }


def estimativas(previsao: dict[str, Any], taxa: float, limite_lote: int) -> dict[str, Any]:
    """As duas opções (tempo real e lote) com os modelos atuais de cada agente."""
    modelos = {k: v["modelo"] for k, v in catalogo.agentes_configurados().items()}
    return {
        "tempo_real": estimar(previsao, taxa, lote=False, modelos=modelos),
        "lote": estimar(previsao, taxa, lote=True, modelos=modelos),
        "modo_recomendado": "lote" if int(previsao.get("itens_com_ia") or 0) >= limite_lote else "tempo_real",
        "taxa_escalonamento": taxa,
        "limite_lote": limite_lote,
    }


def familias_ja_investigadas(session: Session, data_referencia: Any) -> set[str]:
    """Códigos com tese já feita na organização para a mesma vigência (reaproveitadas sem custo)."""
    from app.models import TaxThesis

    return set(
        session.scalars(
            select(TaxThesis.codigo).where(
                TaxThesis.status == "concluida", TaxThesis.data_referencia == data_referencia
            )
        )
    )


def prever_trabalho(
    itens: list[Any], codigos_validos: set[str], na_memoria: int, familias_ja_investigadas: set[str]
) -> dict[str, Any]:
    """Quanto trabalho de IA a planilha deve gerar, já descontadas as economias do analista:
    memória aprovada, confirmação sem IA, descrições repetidas e famílias já investigadas."""
    from app.pipeline.normalize import remover_marca

    com_codigo = [i for i in itens if (i.ncm or i.nbs) in codigos_validos]
    sem_codigo = [i for i in itens if (i.ncm or i.nbs) not in codigos_validos]
    confirmaveis = math.floor(len(com_codigo) * TAXA_CONFIRMACAO_SEM_IA)

    def chave(i: Any) -> tuple[str, str]:
        return (" ".join(remover_marca(i.descricao, i.marca).lower().split()), i.ncm or i.nbs or "")

    distintos_com = len({chave(i) for i in com_codigo})
    distintos_sem = len({chave(i) for i in sem_codigo})
    repetidos = (len(com_codigo) - distintos_com) + (len(sem_codigo) - distintos_sem)
    com_ia = max(0, round(distintos_com * (1 - TAXA_CONFIRMACAO_SEM_IA)) + distintos_sem - na_memoria)
    codigos = {i.ncm or i.nbs for i in com_codigo}
    familias_codigo = len(codigos - familias_ja_investigadas)
    familias_sem = math.ceil(distintos_sem * TAXA_FAMILIAS_SEM_CODIGO)
    return {
        "itens": len(itens),
        "com_codigo_valido": len(com_codigo),
        "sem_codigo_valido": len(sem_codigo),
        "confirmaveis_sem_ia": confirmaveis,
        "repetidos": repetidos,
        "na_memoria": na_memoria,
        "itens_com_ia": com_ia,
        "familias": len(codigos) + familias_sem,
        "familias_reaproveitadas": len(codigos & familias_ja_investigadas),
        "familias_novas": familias_codigo + familias_sem,
    }


def contar_itens(session: Session, audit_id: Any) -> dict[str, int]:
    rows = session.execute(
        select(AuditItem.ignorado, func.count()).where(AuditItem.audit_id == audit_id).group_by(AuditItem.ignorado)
    ).all()
    d = {bool(r[0]): int(r[1]) for r in rows}
    return {"validos": d.get(False, 0), "ignorados": d.get(True, 0)}
