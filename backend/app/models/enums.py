"""Enumerações do domínio (valores gravados no banco em português)."""

from enum import StrEnum


class TipoOrganizacao(StrEnum):
    ESCRITORIO_CONTABIL = "escritorio_contabil"
    EMPRESA = "empresa"


class Papel(StrEnum):
    ADMINISTRADOR = "administrador"
    REVISOR = "revisor"
    OPERADOR = "operador"
    LEITURA = "leitura"


class RegimeTributario(StrEnum):
    MEI = "mei"
    SIMPLES_NACIONAL = "simples_nacional"
    LUCRO_PRESUMIDO = "lucro_presumido"
    LUCRO_REAL = "lucro_real"


class FonteReferencia(StrEnum):
    NCM = "ncm"
    NBS = "nbs"
    CCLASSTRIB = "cclasstrib"
    LC214 = "lc214"


class StatusVersao(StrEnum):
    IMPORTANDO = "importando"
    ATIVA = "ativa"
    SUBSTITUIDA = "substituida"
    FALHOU = "falhou"


class TipoCodigo(StrEnum):
    NCM = "ncm"
    NBS = "nbs"


class TipoTratamento(StrEnum):
    TRIBUTACAO_INTEGRAL = "tributacao_integral"
    ALIQUOTA_ZERO = "aliquota_zero"
    REDUCAO_60 = "reducao_60"
    REDUCAO_30 = "reducao_30"
    REDUCAO_40 = "reducao_40"
    REDUCAO_OUTRA = "reducao_outra"
    ISENCAO = "isencao"
    IMUNIDADE = "imunidade"
    REGIME_ESPECIFICO = "regime_especifico"
    IMPOSTO_SELETIVO = "imposto_seletivo"


class StatusRegra(StrEnum):
    PENDENTE_REVISAO = "pendente_revisao"
    APROVADA = "aprovada"
    REJEITADA = "rejeitada"
    INVALIDA = "invalida"
    SUBSTITUIDA = "substituida"


class OrigemRegra(StrEnum):
    CORRELACAO_OFICIAL = "correlacao_oficial"
    TEXTO_LEGAL = "texto_legal"
    EXTRACAO_IA = "extracao_ia"
    MANUAL = "manual"
    YAML = "yaml"


class StatusAuditoria(StrEnum):
    RASCUNHO = "rascunho"
    PREPARANDO = "preparando"
    PRONTA = "pronta"
    PROCESSANDO = "processando"
    AGUARDANDO_LOTE = "aguardando_lote"
    PAUSADA_ORCAMENTO = "pausada_orcamento"
    CONCLUIDA = "concluida"
    FALHOU = "falhou"
    CANCELADA = "cancelada"


class ModoProcessamento(StrEnum):
    TEMPO_REAL = "tempo_real"
    LOTE = "lote"


class TipoItem(StrEnum):
    PRODUTO = "produto"
    SERVICO = "servico"
    DESCONHECIDO = "desconhecido"


class StatusItem(StrEnum):
    PENDENTE = "pendente"
    PROCESSANDO = "processando"
    CONFIRMADO = "confirmado"
    CORRIGIDO = "corrigido"
    ANALISE_HUMANA = "analise_humana"
    ERRO = "erro"


class StatusRevisao(StrEnum):
    PENDENTE = "pendente"
    APROVADO = "aprovado"
    REJEITADO = "rejeitado"


class AcaoRevisao(StrEnum):
    APROVAR = "aprovar"
    EDITAR = "editar"
    REJEITAR = "rejeitar"
    DESFAZER = "desfazer"
    RESPONDER = "responder"


class StatusChamadaLLM(StrEnum):
    NA_FILA = "na_fila"
    ENVIADA = "enviada"
    CONCLUIDA = "concluida"
    FALHOU = "falhou"


class StatusLote(StrEnum):
    ENVIADO = "enviado"
    CONCLUIDO = "concluido"
    FALHOU = "falhou"
    CANCELADO = "cancelado"


class StatusExportacao(StrEnum):
    NA_FILA = "na_fila"
    GERANDO = "gerando"
    CONCLUIDA = "concluida"
    FALHOU = "falhou"
