"""Estimativa de custo e tempo antes de iniciar uma auditoria."""

from __future__ import annotations

import math
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.llm.pricing import custo_chamada
from app.llm.prompts import carregar
from app.models import AuditItem, LlmCall

# Tamanhos médios por chamada (tokens). O bloco de sistema vai para o cache após a 1ª chamada.
USUARIO_PRINCIPAL = 1600
SAIDA_PRINCIPAL = 1400  # inclui raciocínio adaptativo
USUARIO_ESCALONAMENTO = 2100
SAIDA_ESCALONAMENTO = 2600
TAXA_ESCALONAMENTO_PADRAO = 0.2
# Investigação jurídica por família (uma por código NCM/NBS): pacote de evidências grande, saída longa.
USUARIO_INVESTIGACAO = 8000
SAIDA_INVESTIGACAO = 5000
# Fatos do item (modelo leve), só nas famílias com condição que depende do item.
USUARIO_FATOS = 700
SAIDA_FATOS = 250
TAXA_ITENS_COM_FATOS = 0.3
# Parte dos itens com NCM/NBS válido que a busca confirma sem IA (o código é o mais provável).
TAXA_CONFIRMACAO_SEM_IA = 0.6
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


def estimar(
    n_com_ia: int,
    modelo_principal: str,
    modelo_escalonamento: str,
    taxa_escalonamento: float,
    lote: bool,
    familias: int = 0,
    modelo_investigacao: str | None = None,
    modelo_leve: str | None = None,
    previsao: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sp, se = _tokens_sistema("julgar_coerencia"), _tokens_sistema("escalar")
    si, sf = _tokens_sistema("investigar_enquadramento"), _tokens_sistema("extrair_fatos")
    modelo_investigacao = modelo_investigacao or modelo_escalonamento
    n_fatos = math.ceil(n_com_ia * TAXA_ITENS_COM_FATOS)
    n_esc = math.ceil(n_com_ia * taxa_escalonamento)
    # 1ª chamada escreve o cache; as demais leem.
    custo_p = (
        custo_chamada(modelo_principal, USUARIO_PRINCIPAL, SAIDA_PRINCIPAL, sp, 0, lote) if n_com_ia else 0
    ) + custo_chamada(modelo_principal, USUARIO_PRINCIPAL, SAIDA_PRINCIPAL, 0, sp, lote) * max(0, n_com_ia - 1)
    custo_e = custo_chamada(modelo_escalonamento, USUARIO_ESCALONAMENTO, SAIDA_ESCALONAMENTO, 0, se, lote) * n_esc
    custo_i = custo_chamada(modelo_investigacao, USUARIO_INVESTIGACAO, SAIDA_INVESTIGACAO, 0, si, lote) * familias
    custo_f = custo_chamada(modelo_leve, USUARIO_FATOS, SAIDA_FATOS, 0, sf, lote) * n_fatos if modelo_leve else 0
    total = float(custo_p + custo_e + custo_i + custo_f)
    s = get_settings()
    if lote:
        tempo_min = (30, 24 * 60)
        texto_tempo = "Em lote: normalmente até 1 hora; no máximo 24 horas."
    else:
        seg = n_com_ia * 9 / 4 + n_esc * 14 / 4 + familias * 45 / 4  # 4 processos em paralelo
        tempo_min = (max(1, math.ceil(seg / 60 * 0.7)), max(1, math.ceil(seg / 60 * 1.5)))
        texto_tempo = f"Cerca de {tempo_min[0]} a {tempo_min[1]} minutos."
    return {
        "itens_com_ia": n_com_ia,
        "escalonamentos_estimados": n_esc,
        "familias_estimadas": familias,
        "taxa_escalonamento": round(taxa_escalonamento, 3),
        "tokens_entrada_estimados": n_com_ia * (USUARIO_PRINCIPAL + sp)
        + n_esc * (USUARIO_ESCALONAMENTO + se)
        + familias * (USUARIO_INVESTIGACAO + si),
        "tokens_saida_estimados": n_com_ia * SAIDA_PRINCIPAL
        + n_esc * SAIDA_ESCALONAMENTO
        + familias * SAIDA_INVESTIGACAO,
        "custo_usd_estimado": round(total, 2),
        "custo_usd_faixa": [round(total * 0.6, 2), round(total * 1.6, 2)],
        "modo": "lote" if lote else "tempo_real",
        "limite_lote": s.llm_batch_min_itens,
        "tempo_minutos": list(tempo_min),
        "tempo_texto": texto_tempo,
        "modelos": {
            "principal": modelo_principal,
            "escalonamento": modelo_escalonamento,
            "investigacao": modelo_investigacao,
        },
        "previsao": previsao or {},
        "observacao": "Estimativa aproximada. O custo real de cada chamada é registrado e exibido durante a auditoria.",
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
