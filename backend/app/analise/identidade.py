"""Identidade fiscal do item (o que ele é e qual NCM/NBS o descreve), a partir das etapas de identificação.

Função pura: recebe o que o grafo apurou (código atual, julgamento, segundo parecer, memória) e
devolve o "cadastro enriquecido" do item.
"""

from __future__ import annotations

from typing import Any

from app.core.codes import formatar_codigo

# Problemas do cadastro legado: o cadastro antigo é evidência, não verdade.
MOTIVOS_CADASTRO = {
    "NCM_INEXISTENTE",
    "NCM_NAO_VIGENTE",
    "NCM_NIVEL_INCOMPLETO",
    "NCM_ZERO_A_ESQUERDA_SUSPEITO",
    "NCM_INCOERENTE_COM_DESCRICAO",
    "NBS_INEXISTENTE",
    "NBS_NIVEL_INCOMPLETO",
    "CODIGO_AUSENTE",
    "ITEM_DUPLICADO",
    "CST_CCLASSTRIB_ATUAL_DIVERGENTE",
}


def consolidar(
    *,
    descricao_normalizada: str,
    tipo: str,
    estrutura: dict[str, Any],
    memoria: dict[str, Any] | None,
    julgamento: dict[str, Any] | None,
    julgamento_valido: bool,
    escalonamento: dict[str, Any] | None,
    escalonamento_valido: bool,
    escalonado: bool,
    codigo_final: str | None,
    tipo_codigo_final: str | None,
    candidatos: list[dict[str, Any]],
    motivos: list[str],
    confirmado_sem_ia: int | None = None,
    arvore: dict[str, Any] | None = None,
) -> dict[str, Any]:
    atual = (estrutura or {}).get("codigo_atual") or {}
    anterior = atual.get("provavel") or atual.get("codigo")
    anterior_valido = bool(atual.get("existe") and atual.get("folha") and atual.get("vigente", True))
    base: dict[str, Any] = {
        "tipo": tipo,
        "descricao_normalizada": descricao_normalizada,
        "codigo_anterior": anterior,
        "codigo_anterior_formatado": formatar_codigo(atual.get("tipo") or "ncm", anterior) if anterior else None,
        "problemas_cadastro": sorted(m for m in motivos if m in MOTIVOS_CADASTRO),
    }
    if memoria:
        return {
            **base,
            "situacao": "memoria",
            "tipo_codigo": memoria["tipo_codigo"],
            "codigo": memoria["codigo"],
            "codigo_formatado": formatar_codigo(memoria["tipo_codigo"], memoria["codigo"]),
            "descricao_oficial": memoria.get("descricao_completa"),
            "confianca_modelo": 0.99,
            "descricao_suficiente": True,
            "concordancia": True,
            "entendimento": "classificação aprovada anteriormente para este item",
            "sinais_de_duvida": [],
        }
    if confirmado_sem_ia is not None and codigo_final and tipo_codigo_final:
        desc = next((c["descricao_completa"] for c in candidatos if c["codigo"] == codigo_final), None)
        return {
            **base,
            "situacao": "confirmado",
            "tipo_codigo": tipo_codigo_final,
            "codigo": codigo_final,
            "codigo_formatado": formatar_codigo(tipo_codigo_final, codigo_final),
            "descricao_oficial": desc,
            "confianca_modelo": 0.9,
            "descricao_suficiente": True,
            "concordancia": True,
            "sem_ia": True,
            "entendimento": f"Código informado confirmado sem IA: na busca pela descrição na tabela oficial, "
            f"ele é o {confirmado_sem_ia}º mais provável.",
            "sinais_de_duvida": [],
        }
    if arvore and arvore.get("codigo") and codigo_final == arvore["codigo"] and tipo_codigo_final:
        # Sugestão da busca guiada pela árvore oficial: vale como ponto de partida, a confirmar por uma pessoa.
        return {
            **base,
            "situacao": "corrigido" if anterior else "sugerido",
            "via_arvore": True,
            "tipo_codigo": tipo_codigo_final,
            "codigo": codigo_final,
            "codigo_formatado": formatar_codigo(tipo_codigo_final, codigo_final),
            "descricao_oficial": next(
                (c["descricao_completa"] for c in candidatos if c["codigo"] == codigo_final), None
            ),
            "confianca_modelo": float(arvore.get("confianca") or 0),
            "descricao_suficiente": True,
            "concordancia": False,
            "entendimento": arvore.get("justificativa"),
            "sinais_de_duvida": [],
            "arvore": arvore,
        }
    if arvore is not None and not arvore.get("codigo") and codigo_final and codigo_final == anterior:
        # Nem a prova nem a busca guiada acharam código melhor: o do ERP fica como referência, não confirmado.
        duvida = (escalonamento or julgamento or {}).get("justificativa") or arvore.get("justificativa") or ""
        return {
            **base,
            "situacao": "nao_confirmado",
            "erp_mantido": True,
            "tipo_codigo": tipo_codigo_final,
            "codigo": codigo_final,
            "codigo_formatado": formatar_codigo(tipo_codigo_final or "ncm", codigo_final),
            "descricao_oficial": atual.get("descricao_completa"),
            "confianca_modelo": 0.3,
            "descricao_suficiente": (escalonamento or julgamento or {}).get("descricao_suficiente"),
            "concordancia": False,
            "entendimento": f"A análise indica que o NCM do ERP pode não descrever o item: {duvida}"[:600],
            "sinais_de_duvida": (escalonamento or julgamento or {}).get("sinais_de_duvida", []),
            "arvore": arvore,
        }
    parecer = escalonamento if (escalonado and escalonamento_valido) else (julgamento if julgamento_valido else None)
    if parecer is None or not codigo_final or not tipo_codigo_final:
        motivo = "a identificação por IA não pôde ser concluída"
        # O parecer que decide é o segundo, quando houve; o primeiro pode ter sugerido um código que o
        # segundo recusou (ex.: café torrado para um café espresso).
        decisivo = parecer or (julgamento if julgamento_valido else None)
        if decisivo and decisivo.get("nenhum_candidato_serve"):
            motivo = "nenhum código da tabela oficial descreve o item com segurança"
            if decisivo.get("justificativa"):
                motivo += ": " + str(decisivo["justificativa"])
        elif julgamento and julgamento.get("_descartado"):
            motivo = "a sugestão da IA foi descartada: " + str(julgamento["_descartado"])
        if arvore is not None and not arvore.get("codigo") and not arvore.get("erro"):
            motivo += " (a busca guiada pela tabela oficial também não achou um código)"
        return {
            **base,
            # A busca guiada também não achou código: o caminho dela fica registrado para a revisão.
            **({"arvore": arvore} if arvore else {}),
            "situacao": "indefinido",
            "tipo_codigo": None,
            "codigo": None,
            "motivo": motivo,
            "descricao_suficiente": (parecer or julgamento or {}).get("descricao_suficiente"),
            "sinais_de_duvida": (parecer or julgamento or {}).get("sinais_de_duvida", []),
            "confianca_modelo": float((parecer or {}).get("confianca", 0) or 0),
        }
    concordancia = (
        escalonado
        and escalonamento_valido
        and (escalonamento or {}).get("codigo_sugerido") == (julgamento or {}).get("codigo_sugerido")
    )
    if anterior and codigo_final == anterior and anterior_valido and parecer.get("ncm_atual_coerente") is not False:
        situacao = "confirmado"
    elif not anterior or (not anterior_valido and atual.get("provavel") is None and not atual.get("existe")):
        situacao = "sugerido"
    else:
        situacao = "corrigido"
    if anterior and parecer.get("ncm_atual_coerente") is False:
        base["problemas_cadastro"] = sorted({*base["problemas_cadastro"], "NCM_INCOERENTE_COM_DESCRICAO"})
    desc = next((c["descricao_completa"] for c in candidatos if c["codigo"] == codigo_final), None)
    pela_lei = next((c.get("citado_na_lei") for c in candidatos if c["codigo"] == codigo_final), None)
    if pela_lei and situacao == "confirmado":
        pela_lei = None  # a lei cita o próprio código do cadastro: nada foi trocado
    conf = float(parecer.get("confianca", 0) or 0)
    if escalonado and escalonamento_valido and julgamento_valido:
        conf = 0.4 * float((julgamento or {}).get("confianca", 0) or 0) + 0.6 * conf
    return {
        **base,
        "situacao": situacao,
        "tipo_codigo": tipo_codigo_final,
        "codigo": codigo_final,
        "codigo_formatado": formatar_codigo(tipo_codigo_final, codigo_final),
        "descricao_oficial": desc,
        "confianca_modelo": round(conf, 3),
        "descricao_suficiente": parecer.get("descricao_suficiente", True),
        "concordancia": bool(concordancia) or not escalonado,
        "segundo_parecer": escalonado,
        "entendimento": parecer.get("justificativa"),
        "sinais_de_duvida": parecer.get("sinais_de_duvida", []),
        **({"corrigido_pela_lei": pela_lei} if pela_lei else {}),
        # Códigos que a dúvida poderia justificar (só os oficiais da prova): a avaliação confere se o imposto muda.
        "codigos_alternativos": [
            c
            for c in dict.fromkeys(
                [*(parecer.get("codigos_alternativos") or []), *((julgamento or {}).get("codigos_alternativos") or [])]
            )
            if c != codigo_final and any(x["codigo"] == c for x in candidatos)
        ],
    }
