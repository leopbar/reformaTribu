from app.core.codes import (
    cnpj_valido,
    formatar_cnpj,
    formatar_nbs,
    formatar_ncm,
    gtin_valido,
    normalizar_ncm,
    somente_digitos,
)


def test_cnpj_numerico_e_alfanumerico():
    assert cnpj_valido("11.222.333/0001-81")
    assert not cnpj_valido("11.222.333/0001-82")
    # Exemplo oficial da Receita Federal para o CNPJ alfanumérico (IN RFB nº 2.229/2024).
    assert cnpj_valido("12.ABC.345/01DE-35")
    assert not cnpj_valido("12.ABC.345/01DE-36")
    assert not cnpj_valido("00000000000000")
    assert formatar_cnpj("12abc34501de35") == "12.ABC.345/01DE-35"


def test_gtin():
    assert gtin_valido("7891000100103")
    assert not gtin_valido("7891000100104")
    assert not gtin_valido("123")


def test_ncm_zero_a_esquerda_e_sinalizado_nao_corrigido():
    n = normalizar_ncm(4011000)
    assert n.codigo == "4011000"  # não corrige em silêncio
    assert n.candidato_zero_esquerda == "04011000"
    assert n.problemas[0]["codigo"] == "NCM_ZERO_A_ESQUERDA_SUSPEITO"


def test_ncm_formatos():
    assert normalizar_ncm("3401.11.90").codigo == "34011190"
    assert normalizar_ncm("3401.11.90").problemas == []
    assert normalizar_ncm("3401").problemas[0]["codigo"] == "NCM_NIVEL_INCOMPLETO"
    assert somente_digitos("4011000.0") == "4011000"
    assert formatar_ncm("34011190") == "3401.11.90"
    assert formatar_ncm("03061") == "0306.1"
    assert formatar_nbs("101011100") == "1.0101.11.00"
    assert formatar_nbs("101011") == "1.0101.1"
