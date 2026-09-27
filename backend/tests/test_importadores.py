"""Parsers das fontes oficiais (com fixtures pequenas) e validação das regras contra as tabelas."""

import json
import uuid
from datetime import UTC, datetime

import pytest

from app.reference.importers.cclasstrib import extrair_dados
from app.reference.importers.common import FormatoInvalido, parse_data_br
from app.reference.importers.lc214 import extrair_codigos, parse_lc214
from app.reference.importers.nomenclatura import No, limpar_descricao, montar_hierarquia, parse_nbs_csv, parse_ncm_json


def test_hierarquia_ncm_e_descricao_completa():
    nos = [
        No("34", "Sabões."),
        No("3401", "Sabões; produtos..."),
        No("340111", "-- De toucador"),
        No("34011190", "--- Outros"),
        No("34013000", "- Produtos para lavagem da pele, líquido"),
    ]
    linhas = {x["codigo"]: x for x in montar_hierarquia(nos, (2, 4, 5, 6, 7), 8)}
    assert linhas["34011190"]["codigo_pai"] == "340111"
    assert linhas["34011190"]["descricao_completa"] == "Sabões. › Sabões; produtos... › De toucador › Outros"
    assert linhas["34011190"]["folha"] and not linhas["3401"]["folha"]
    assert limpar_descricao("-- <i>Aedes</i> aegypti:") == "Aedes aegypti"


def test_ncm_json_formato_oficial_e_incompleto():
    doc = {
        "Data_Ultima_Atualizacao_NCM": "Vigente em 26/09/2026",
        "Ato": "Res. Gecex",
        "Nomenclaturas": [
            {"Codigo": f"{i:04d}.10.00", "Descricao": "x", "Data_Inicio": "01/04/2022", "Data_Fim": "31/12/9999"}
            for i in range(1200)
        ],
    }
    nos, meta = parse_ncm_json(json.dumps(doc).encode())
    assert len(nos) == 1200 and nos[0].data_fim is None
    assert meta["Ato"] == "Res. Gecex"
    with pytest.raises(FormatoInvalido):
        parse_ncm_json(json.dumps({"Nomenclaturas": doc["Nomenclaturas"][:10]}).encode())
    with pytest.raises(FormatoInvalido):
        parse_ncm_json(b"<html>manutencao</html>")


def test_nbs_csv():
    linhas = ["NBS 2.0;DESCRIÇÃO"] + [f"1.{i:04d}.1{j}.00;Serviço {i}{j}" for i in range(100, 200) for j in range(6)]
    nos = parse_nbs_csv("\n".join(linhas).encode("cp1252"))
    assert nos[0].codigo == "101001000"  # 1.0100.10.00


def test_cclasstrib_da_pagina_svrs():
    dados = [
        {
            "Cst": "200",
            "NomeCst": "Alíquota reduzida",
            "ClassificacoesTributarias": [
                {
                    "CodClassTrib": "200035",
                    "NomeClassTrib": "Higiene",
                    "Anexos": [{"CodNcmNbs": "34011190", "TipoCodigo": "NCM", "TipoPermissao": "PERMITIDO"}],
                }
            ],
        }
    ]
    html = f"<script>\n        var dadosOriginais = {json.dumps(dados)};\n</script>".encode()
    assert extrair_dados(html)[0]["ClassificacoesTributarias"][0]["CodClassTrib"] == "200035"
    with pytest.raises(FormatoInvalido):
        extrair_dados(b"<html>sem dados</html>")


def test_extrai_codigos_citados_em_varios_niveis():
    assert extrair_codigos("87.03; 8704.21 (exceto os caminhões); 8704.41.00", coluna_codigos=True) == [
        "87044100",
        "870421",
        "8703",
    ]
    assert extrair_codigos("Capítulo 31 3824.99.77", coluna_codigos=True) == ["38249977", "31"]
    assert extrair_codigos("classificados no código 3401.11.90 da NCM/SH", coluna_codigos=False) == ["34011190"]
    assert extrair_codigos("1.0604.21.00", coluna_codigos=True) == ["106042100"]


def test_lc214_descarta_texto_revogado():
    artigos = "".join(f"<p>Art. {i}º Texto do artigo {i}.</p>" for i in range(1, 120))
    html = f"""<html><body><p>Lei Complementar nº 214</p>{artigos}
      <p>Art. 5º <strike>Redação revogada</strike> Redação vigente.</p>
      <p><a name="anexo8"></a>ANEXO VIII</p><p>PRODUTOS DE HIGIENE SUBMETIDOS À REDUÇÃO</p>
      <table><tr><td>ITEM</td><td>DESCRIÇÃO DO PRODUTO</td></tr>
      <tr><td>1</td><td>Sabões de toucador classificados no código 3401.11.90 da NCM/SH</td></tr></table>
    </body></html>""".encode()
    arts, itens, titulos = parse_lc214(html)
    art5 = next(a for a in arts if a.numero == "5")
    assert "revogada" not in art5.texto and "vigente" in art5.texto
    assert itens[0].anexo == "VIII" and itens[0].codigos == ["34011190"]
    assert titulos["VIII"].startswith("PRODUTOS DE HIGIENE")


def test_datas():
    assert parse_data_br("31/12/9999") is None
    assert parse_data_br("2025-05-01T00:00:00").isoformat() == "2025-05-01"


@pytest.mark.usefixtures("limpo")
def test_validacao_sinaliza_codigo_inexistente_e_cclasstrib_errado():
    from app.db.session import TenantContext, sync_reference_admin_session
    from app.models import CClassTribCode, LegalRule, NcmNode, RefVersion
    from app.rules.validation import validar_regra

    agora = datetime.now(UTC)
    with sync_reference_admin_session(TenantContext(org_id=None, platform_admin=True)) as s:
        v = RefVersion(
            fonte="ncm",
            rotulo="t",
            modo_coleta="upload_manual",
            coletado_em=agora,
            sha256=uuid.uuid4().hex,
            arquivo_path="x",
            status="ativa",
            estatisticas={},
            avisos=[],
        )
        c = RefVersion(
            fonte="cclasstrib",
            rotulo="t",
            modo_coleta="upload_manual",
            coletado_em=agora,
            sha256=uuid.uuid4().hex,
            arquivo_path="x",
            status="ativa",
            estatisticas={},
            avisos=[],
        )
        s.add_all([v, c])
        s.flush()
        s.add(
            NcmNode(
                version_id=v.id,
                codigo="34011190",
                codigo_formatado="3401.11.90",
                nivel="item",
                descricao="x",
                descricao_completa="x",
                folha=True,
            )
        )
        s.add(CClassTribCode(version_id=c.id, codigo="200035", cst="200", nome="x", indicadores={}))
        s.flush()
        boa = LegalRule(
            slug="ok",
            descricao_legal="x",
            dispositivo_legal="x",
            tipo_tratamento="reducao_60",
            tipo_codigo="ncm",
            abrangencia={"codigos": [{"codigo": "340111"}]},
            cst_ibs_cbs="200",
            cclasstrib="200035",
            status="pendente_revisao",
            origem="manual",
        )
        ruim = LegalRule(
            slug="ruim",
            descricao_legal="x",
            dispositivo_legal="x",
            tipo_tratamento="reducao_60",
            tipo_codigo="ncm",
            abrangencia={"codigos": [{"codigo": "99999999"}]},
            cst_ibs_cbs="000",
            cclasstrib="200035",
            status="pendente_revisao",
            origem="manual",
        )
        s.add_all([boa, ruim])
        s.flush()
        assert validar_regra(s, boa) == []
        codigos = {e["codigo"] for e in validar_regra(s, ruim)}
        assert codigos == {"CST_INCOMPATIVEL", "CODIGO_INEXISTENTE"}
        assert ruim.status == "invalida"
