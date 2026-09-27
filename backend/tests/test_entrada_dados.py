"""Leitura de planilhas, mapeamento automático e limpeza (sem IA), com as planilhas de exemplo."""

import io
import zipfile
from pathlib import Path

import pytest
from openpyxl import Workbook

from app.ingest.cleaning import limpar, resumir_problemas
from app.ingest.mapping import sugerir_mapeamento, validar_mapeamento
from app.ingest.reader import ArquivoInvalido, detectar_formato, ler_planilha

_LOCAL = Path(__file__).resolve().parents[2] / "data" / "samples"
AMOSTRAS = _LOCAL if _LOCAL.exists() else Path("/data/samples")
sem_amostras = pytest.mark.skipif(not AMOSTRAS.exists(), reason="planilhas de exemplo indisponíveis no contêiner")


def xlsx(linhas: list[list[object]]) -> bytes:
    wb = Workbook()
    ws = wb.active
    for linha in linhas:
        ws.append(linha)
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def test_preserva_zeros_e_codigos_longos():
    p = ler_planilha(
        xlsx(
            [
                ["Cód", "Descrição", "NCM", "EAN"],
                ["001", "LEITE", "04012010", "7891000100103"],
                [2, "FEIJAO", 7133319, 7891000100103],
            ]
        ),
        "a.xlsx",
    )
    assert p.linhas[0] == ["001", "LEITE", "04012010", "7891000100103"]
    assert p.linhas[1][2] == "7133319" and p.linhas[1][3] == "7891000100103"


def test_detecta_cabecalho_abaixo_de_titulo():
    p = ler_planilha(
        xlsx([["Relatório"], [], ["Código", "Descrição do produto", "NCM"], ["1", "ARROZ", "10063021"]]), "a.xlsx"
    )
    assert p.colunas == ["Código", "Descrição do produto", "NCM"]
    assert p.linha_cabecalho == 2


def test_csv_latin1_ponto_e_virgula():
    dados = "Código;Descrição;NCM\n1;AÇÚCAR REFINADO;1701.99.00\n".encode("cp1252")
    p = ler_planilha(dados, "x.csv")
    assert p.separador == ";" and p.encoding == "windows-1252"
    assert p.linhas[0][1] == "AÇÚCAR REFINADO"


def test_rejeita_macros_e_tipo_falso():
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("xl/workbook.xml", "<workbook/>")
        z.writestr("xl/vbaProject.bin", b"\x00")
    with pytest.raises(ArquivoInvalido, match="macros"):
        detectar_formato(b.getvalue(), "planilha.xlsm")
    with pytest.raises(ArquivoInvalido):
        detectar_formato(b"%PDF-1.7 \x00\x01", "falso.xlsx")


def test_mapeamento_por_nome_e_conteudo():
    colunas = ["COD", "PRODUTO", "CLASS FISCAL", "Cod. Barras", "Grupo"]
    linhas = [
        ["1", "SABONETE BARRA 90G", "34011190", "7891000100103", "HIGIENE"],
        ["2", "ARROZ TIPO 1 5KG", "10063021", "7891000100103", "MERCEARIA"],
    ]
    m = sugerir_mapeamento(colunas, linhas)
    assert m["descricao"] == "PRODUTO"
    assert m["ncm"] == "CLASS FISCAL"
    assert m["gtin"] == "Cod. Barras"
    assert m["categoria"] == "Grupo"
    assert validar_mapeamento(m, colunas) == []
    assert validar_mapeamento({**m, "descricao": None}, colunas)


def test_limpeza_sinaliza_problemas_sem_corrigir_em_silencio():
    m = {"descricao": "d", "codigo_interno": "c", "ncm": "n", "gtin": "g"}
    regs = [
        {"c": "1", "d": "LEITE UHT", "n": "4012010", "g": "7891000100103"},
        {"c": "1", "d": "LEITE UHT", "n": "04012010", "g": "7891000100104"},
        {"c": "", "d": "", "n": "", "g": ""},
        {"c": "3", "d": "", "n": "1234", "g": ""},
        {"c": "", "d": "SERVICO X", "n": "", "g": ""},
    ]
    itens = limpar(regs, m)
    assert len(itens) == 4  # linha totalmente vazia descartada
    zero = itens[0]
    assert zero.ncm == "4012010" and zero.ncm_candidato_zero == "04012010"
    codigos = [{p["codigo"] for p in i.problemas} for i in itens]
    assert "NCM_ZERO_A_ESQUERDA_SUSPEITO" in codigos[0]
    assert {"DUPLICADO", "GTIN_INVALIDO"} <= codigos[1]
    assert itens[2].ignorado and "LINHA_VAZIA" in codigos[2]
    assert {"CODIGO_INTERNO_GERADO", "SEM_CODIGO"} <= codigos[3]
    r = resumir_problemas(itens)
    assert r["itens_validos"] == 3 and r["ignorados"] == 1


@sem_amostras
@pytest.mark.parametrize(
    "arquivo",
    ["supermercado_ficticio.xlsx", "padaria_ficticia.csv", "farmacia_ficticia.xlsx", "servicos_ficticios.xlsx"],
)
def test_amostras_sao_lidas_e_mapeadas(arquivo: str):
    p = ler_planilha((AMOSTRAS / arquivo).read_bytes(), arquivo)
    m = sugerir_mapeamento(p.colunas, p.linhas)
    assert m["descricao"] and m["codigo_interno"]
    assert m["ncm"] or m["nbs"]
    itens = limpar(p.registros(), m)
    assert len([i for i in itens if not i.ignorado]) >= 30
