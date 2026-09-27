"""Códigos de motivo padronizados, com textos para a interface."""

from __future__ import annotations

from enum import StrEnum


class Motivo(StrEnum):
    NCM_INEXISTENTE = "NCM_INEXISTENTE"
    NCM_NAO_VIGENTE = "NCM_NAO_VIGENTE"
    NCM_NIVEL_INCOMPLETO = "NCM_NIVEL_INCOMPLETO"
    NCM_ZERO_A_ESQUERDA_SUSPEITO = "NCM_ZERO_A_ESQUERDA_SUSPEITO"
    NCM_INCOERENTE_COM_DESCRICAO = "NCM_INCOERENTE_COM_DESCRICAO"
    NBS_INEXISTENTE = "NBS_INEXISTENTE"
    NBS_NIVEL_INCOMPLETO = "NBS_NIVEL_INCOMPLETO"
    CODIGO_AUSENTE = "CODIGO_AUSENTE"
    DESCRICAO_INSUFICIENTE = "DESCRICAO_INSUFICIENTE"
    CONDICAO_LEGAL_NAO_VERIFICAVEL = "CONDICAO_LEGAL_NAO_VERIFICAVEL"
    EXCECAO_LEGAL_POSSIVEL = "EXCECAO_LEGAL_POSSIVEL"
    CASO_CONTROVERSO = "CASO_CONTROVERSO"
    BAIXA_CONFIANCA = "BAIXA_CONFIANCA"
    DIVERGENCIA_ENTRE_MODELOS = "DIVERGENCIA_ENTRE_MODELOS"
    DIVERGENCIA_BUSCA_JULGAMENTO = "DIVERGENCIA_BUSCA_JULGAMENTO"
    REGRA_PENDENTE_DE_REVISAO = "REGRA_PENDENTE_DE_REVISAO"
    MULTIPLAS_REGRAS_APLICAVEIS = "MULTIPLAS_REGRAS_APLICAVEIS"
    BASE_REFERENCIA_INCOMPLETA = "BASE_REFERENCIA_INCOMPLETA"
    SUJEITO_A_IMPOSTO_SELETIVO = "SUJEITO_A_IMPOSTO_SELETIVO"
    CST_CCLASSTRIB_ATUAL_DIVERGENTE = "CST_CCLASSTRIB_ATUAL_DIVERGENTE"
    CODIGO_SUGERIDO_INVALIDO = "CODIGO_SUGERIDO_INVALIDO"
    NENHUM_CANDIDATO_ADEQUADO = "NENHUM_CANDIDATO_ADEQUADO"
    TIPO_ITEM_INDEFINIDO = "TIPO_ITEM_INDEFINIDO"
    FALHA_NA_ANALISE_IA = "FALHA_NA_ANALISE_IA"
    ORCAMENTO_ESGOTADO = "ORCAMENTO_ESGOTADO"
    ITEM_DUPLICADO = "ITEM_DUPLICADO"


TEXTOS: dict[str, tuple[str, str]] = {
    # código: (rótulo curto, explicação)
    "NCM_INEXISTENTE": ("NCM inexistente", "O NCM cadastrado não existe na tabela oficial vigente."),
    "NCM_NAO_VIGENTE": ("NCM fora de vigência", "O NCM cadastrado não está vigente na data de referência."),
    "NCM_NIVEL_INCOMPLETO": ("NCM incompleto", "O NCM cadastrado não tem os 8 dígitos exigidos."),
    "NCM_ZERO_A_ESQUERDA_SUSPEITO": (
        "Zero à esquerda perdido",
        "O NCM tem 7 dígitos; provavelmente a planilha removeu o zero inicial.",
    ),
    "NCM_INCOERENTE_COM_DESCRICAO": ("NCM não combina com a descrição", "O código cadastrado não descreve o item."),
    "NBS_INEXISTENTE": ("NBS inexistente", "A NBS cadastrada não existe na tabela oficial vigente."),
    "NBS_NIVEL_INCOMPLETO": ("NBS incompleta", "A NBS cadastrada não tem os 9 dígitos do código completo."),
    "CODIGO_AUSENTE": ("Sem código cadastrado", "O item não tem NCM nem NBS; o sistema sugeriu um."),
    "DESCRICAO_INSUFICIENTE": ("Descrição insuficiente", "A descrição não permite identificar o item com segurança."),
    "CONDICAO_LEGAL_NAO_VERIFICAVEL": (
        "Condição legal a confirmar",
        "O benefício depende de uma condição que a descrição não informa.",
    ),
    "EXCECAO_LEGAL_POSSIVEL": ("Possível exceção legal", "O item pode estar numa exceção prevista na lei."),
    "CASO_CONTROVERSO": ("Caso controverso", "Há divergência entre fontes especializadas para este enquadramento."),
    "BAIXA_CONFIANCA": ("Baixa confiança", "A confiança final ficou abaixo do limite configurado."),
    "DIVERGENCIA_ENTRE_MODELOS": (
        "Pareceres divergentes",
        "A análise principal e a de escalonamento chegaram a códigos diferentes.",
    ),
    "DIVERGENCIA_BUSCA_JULGAMENTO": (
        "Busca e julgamento divergem",
        "O código escolhido não está entre os mais prováveis da busca.",
    ),
    "REGRA_PENDENTE_DE_REVISAO": (
        "Regra legal em revisão",
        "Uma regra que pode se aplicar ainda não foi aprovada na base de referência.",
    ),
    "MULTIPLAS_REGRAS_APLICAVEIS": (
        "Mais de um enquadramento",
        "Mais de uma regra legal se aplica e a escolha depende da operação.",
    ),
    "BASE_REFERENCIA_INCOMPLETA": (
        "Base de referência incompleta",
        "Falta uma tabela oficial ou regra necessária para decidir.",
    ),
    "SUJEITO_A_IMPOSTO_SELETIVO": ("Imposto Seletivo", "O item está na lista de bens sujeitos ao Imposto Seletivo."),
    "CST_CCLASSTRIB_ATUAL_DIVERGENTE": (
        "CST/cClassTrib atual diverge",
        "O CST ou cClassTrib cadastrado é diferente do sugerido.",
    ),
    "CODIGO_SUGERIDO_INVALIDO": (
        "Sugestão descartada",
        "O modelo sugeriu um código fora da lista ou inexistente; a resposta foi descartada.",
    ),
    "NENHUM_CANDIDATO_ADEQUADO": ("Nenhum código adequado", "Nenhum dos códigos candidatos descreve o item."),
    "TIPO_ITEM_INDEFINIDO": ("Produto ou serviço?", "Não foi possível determinar se é produto ou serviço."),
    "FALHA_NA_ANALISE_IA": ("Falha na análise por IA", "A análise por IA não pôde ser concluída."),
    "ORCAMENTO_ESGOTADO": ("Orçamento de IA esgotado", "O orçamento mensal de IA foi atingido."),
    "ITEM_DUPLICADO": ("Item duplicado", "Há outra linha com o mesmo código interno ou descrição."),
}

# Motivos que, sozinhos, impedem Confirmado/Corrigido (vão para análise humana).
BLOQUEANTES = frozenset(
    {
        Motivo.NCM_INEXISTENTE,
        Motivo.NCM_NAO_VIGENTE,
        Motivo.DESCRICAO_INSUFICIENTE,
        Motivo.CONDICAO_LEGAL_NAO_VERIFICAVEL,
        Motivo.EXCECAO_LEGAL_POSSIVEL,
        Motivo.CASO_CONTROVERSO,
        Motivo.BAIXA_CONFIANCA,
        Motivo.DIVERGENCIA_ENTRE_MODELOS,
        Motivo.REGRA_PENDENTE_DE_REVISAO,
        Motivo.MULTIPLAS_REGRAS_APLICAVEIS,
        Motivo.BASE_REFERENCIA_INCOMPLETA,
        Motivo.CODIGO_SUGERIDO_INVALIDO,
        Motivo.NENHUM_CANDIDATO_ADEQUADO,
        Motivo.TIPO_ITEM_INDEFINIDO,
        Motivo.FALHA_NA_ANALISE_IA,
        Motivo.ORCAMENTO_ESGOTADO,
        Motivo.NBS_INEXISTENTE,
        Motivo.DIVERGENCIA_BUSCA_JULGAMENTO,
    }
)
