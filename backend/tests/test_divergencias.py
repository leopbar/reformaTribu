"""Leitura do texto legal e detecção de divergências entre a lei, a tabela oficial e a regra.

Os textos abaixo reproduzem itens dos anexos da LC 214/2025; a nomenclatura é um recorte de TESTE.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from types import SimpleNamespace
from typing import Any

from app.rules.divergencias import (
    ContextoDivergencias,
    Nomenclatura,
    detectar_divergencias,
    exige_justificativa,
    ler_texto_legal,
)

PEIXES = (
    "Peixes e carnes de peixes (exceto salmonídeos, atuns, bacalhaus, hadoque, saithe e ovas e outros subprodutos) "
    "dos seguintes códigos, subposições e posições da NCM/SH: a) 03.02; exceto os produtos das subposições e dos "
    "códigos 0302.1, 0302.3, 0302.51.00, 0302.52.00, 0302.53.00 e 0302.9 da NCM/SH; b) 03.03; exceto os produtos "
    "das subposições e dos códigos 0303.1, 0303.4, 0303.63.00, 0303.64.00, 0303.65.00 e 0303.9 da NCM/SH; c) 03.04; "
    "exceto os salmonídeos, atuns, bacalhaus, hadoque e saithe classificados nas subposições 0304.4, 0304.5, "
    "0304.7, 0304.8 e 0304.9 da NCM/SH"
)


def test_le_exclusoes_totais_parciais_e_restricoes():
    lei = ler_texto_legal(PEIXES)
    assert lei.incluidos == ["0302", "0303", "0304"]
    assert {"03021", "03023", "03025100", "03029", "03031", "03039"} <= set(lei.excluidos)
    (parcial,) = lei.parciais
    assert parcial.codigos == ["03044", "03045", "03047", "03048", "03049"]
    assert {"salmonideo", "atum", "bacalhau", "hadoque", "saithe"} <= set(parcial.termos)
    assert any("salmonídeos" in r for r in lei.restricoes)


def test_le_coluna_de_codigos_capitulos_e_grafias_irregulares():
    lei = ler_texto_legal("Sementes e cereais, exceto de animais domésticos\nCódigos: Capítulos 10, 11 e 12")
    assert lei.incluidos == ["10", "11", "12"]
    assert lei.restricoes == ["exceto de animais domésticos"]
    lei = ler_texto_legal("Produtos hortícolas das posições 07.01, 07.02.00.00 e 1302.19.9")
    assert set(lei.incluidos) == {"0701", "07020000", "1302199"}


def test_le_referencia_a_outro_anexo_e_varias_excecoes():
    lei = ler_texto_legal(
        "Frutas classificadas nos capítulos 7 e 8 da NCM/SH, ressalvados as frutas de casca rija não regionais e "
        "os produtos relacionados nos Anexos I e XV e excetuadas as posições 07.11, 08.12 e 0814.00.00"
    )
    assert lei.anexos_excluidos == ["I", "XV"]
    assert set(lei.excluidos) == {"0711", "0812", "08140000"}
    assert any("casca rija" in r for r in lei.restricoes)
    lei = ler_texto_legal("Aparelhos de raio X, móveis, exceto os produtos classificados no código 9022.19.91")
    assert lei.excluidos == ["90221991"] and not lei.parciais


# ------------------------------------------------------------------ detecção --
NCM = {
    "03044100": "Filés › Filés frescos › Salmões-do-pacífico, salmões-do-atlântico",
    "03044300": "Filés › Filés frescos › Peixes chatos (linguados)",
    "03044700": "Filés › Filés frescos › Cações",
    "03021100": "Peixes frescos › Salmonídeos › Trutas",
    "03022100": "Peixes frescos › Peixes chatos › Alabotes",
    "03022200": "Peixes frescos › Peixes chatos › Solhas",
    "03031100": "Peixes congelados › Salmonídeos › Salmões-vermelhos",
    "03032300": "Peixes congelados › Tilápias",
}


def _ctx(*outras: Any) -> ContextoDivergencias:
    ctx = ContextoDivergencias.__new__(ContextoDivergencias)
    ctx.nom = {"ncm": Nomenclatura([(c, True, d) for c, d in NCM.items()]), "nbs": None}
    ctx.cclasstrib = {}
    ctx.provisoes = {}
    ctx.cobertura = {"ncm": defaultdict(list), "nbs": defaultdict(list)}
    ctx.por_provisao = defaultdict(dict)
    ctx.por_anexo = defaultdict(set)
    for o in outras:
        ctx.indexar(o)
    return ctx


def _regra(codigos: list[str], excecoes: list[str], provisao: Any, **kw: Any) -> Any:
    return SimpleNamespace(
        slug=kw.get("slug", "peixes"),
        anexo=kw.get("anexo", "I"),
        tipo_codigo="ncm",
        tipo_tratamento=kw.get("tratamento", "aliquota_zero"),
        abrangencia={"universal": False, "codigos": [{"codigo": c} for c in codigos]},
        excecoes=[{"codigo": c} for c in excecoes],
        condicoes=kw.get("condicoes", []),
        cclasstrib=kw.get("cclasstrib", "200003"),
        dispositivo_legal=kw.get("dispositivo", "LC 214/2025, Anexo I, item 20"),
        provision_id=provisao.id if provisao else None,
    )


def _provisao(texto: str, titulo: str = "PRODUTOS SUBMETIDOS À REDUÇÃO A ZERO") -> Any:
    return SimpleNamespace(id=uuid.uuid4(), texto=texto, anexo="I", titulo_anexo=titulo)


def test_tabela_que_veta_subposicao_inteira_contra_excecao_parcial_da_lei():
    prov = _provisao(PEIXES)
    ctx = _ctx()
    ctx.provisoes[prov.id] = prov
    # Como a correlação oficial: benefício para 0302.2x e 0303.23; veto para toda a 0304.4.
    regra = _regra(
        ["03022100", "03022200", "03032300"], ["03021100", "03031100", "03044100", "03044300", "03044700"], prov
    )
    codigos = {a["codigo"]: a for a in detectar_divergencias(ctx, regra)}
    ampliada = codigos["DIV_EXCECAO_PARCIAL_AMPLIADA"]
    # Peixes chatos e cações não são salmonídeos: a lei não os exclui. O salmão, sim.
    assert ampliada["codigos"] == ["03044300", "03044700"]
    assert ampliada["acao"] == "incluir_na_abrangencia"
    assert "DIV_ALEM_DA_LEI" not in codigos and "DIV_EXCECAO_DA_LEI_IGNORADA" not in codigos
    assert exige_justificativa(list(codigos.values()))


def test_regra_que_beneficia_codigo_excluido_ou_nao_citado():
    prov = _provisao("Peixes dos códigos 0302.2 e 0303.23; exceto os produtos do código 0302.22.00")
    ctx = _ctx()
    ctx.provisoes[prov.id] = prov
    regra = _regra(["03022100", "03022200", "03044700"], [], prov)
    codigos = {a["codigo"]: a for a in detectar_divergencias(ctx, regra)}
    assert codigos["DIV_EXCECAO_DA_LEI_IGNORADA"]["codigos"] == ["03022200"]
    assert codigos["DIV_ALEM_DA_LEI"]["codigos"] == ["03044700"]
    assert codigos["DIV_LEI_NAO_COBERTA"]["codigos"] == ["03032300"]


def test_regra_coerente_nao_gera_divergencia():
    prov = _provisao("Peixes dos códigos 0302.2 e 0303.23")
    ctx = _ctx()
    ctx.provisoes[prov.id] = prov
    assert detectar_divergencias(ctx, _regra(["03022100", "03022200", "03032300"], [], prov)) == []


def test_codigo_citado_pela_lei_que_nao_existe_mais():
    prov = _provisao("Peixes do código 0302.29.99 e 0302.21.00")
    ctx = _ctx()
    ctx.provisoes[prov.id] = prov
    avisos = detectar_divergencias(ctx, _regra(["03022100"], [], prov))
    assert [a["codigo"] for a in avisos] == ["DIV_LEI_CODIGO_INEXISTENTE"]
    assert "0302.29.99" in avisos[0]["mensagem"]


def test_tratamento_diferente_do_titulo_do_anexo_exige_condicao():
    prov = _provisao("Peixes do código 0302.21.00", titulo="PRODUTOS SUBMETIDOS À REDUÇÃO DE 60%")
    ctx = _ctx()
    ctx.provisoes[prov.id] = prov
    assert [a["codigo"] for a in detectar_divergencias(ctx, _regra(["03022100"], [], prov))] == ["DIV_TRATAMENTO"]
    cond = [{"atributo": "adquirente_publico", "deve_ser": "sim"}]
    assert detectar_divergencias(ctx, _regra(["03022100"], [], prov, condicoes=cond)) == []


def test_sobreposicao_com_outra_regra_e_informativa():
    prov_a = _provisao("Peixes do código 0302.21.00")
    prov_b = _provisao("Alabotes do código 0302.21.00")
    outra = _regra(["03022100"], [], prov_b, slug="outra", cclasstrib="200034", dispositivo="Anexo VII, item 1")
    ctx = _ctx(outra)
    ctx.provisoes[prov_a.id] = prov_a
    avisos = detectar_divergencias(ctx, _regra(["03022100"], [], prov_a))
    assert [a["codigo"] for a in avisos] == ["DIV_SOBREPOSICAO"]
    assert "Anexo VII, item 1" in avisos[0]["mensagem"]
    assert exige_justificativa(avisos) == []
    # Com condição em uma das regras, o motor consegue diferenciá-las.
    assert detectar_divergencias(ctx, _regra(["03022100"], [], prov_a, condicoes=[{"atributo": "x"}])) == []


def test_referencia_a_outro_anexo_justifica_o_veto():
    prov = _provisao("Peixes do capítulo 03, ressalvados os produtos relacionados no Anexo I")
    anexo_i = _regra(["03022100"], [], _provisao("x"), slug="cesta", anexo="I")
    ctx = _ctx(anexo_i)
    ctx.provisoes[prov.id] = prov
    regra = _regra(
        [c for c in NCM if c != "03022100"], ["03022100"], prov, slug="vii", anexo="VII", cclasstrib="200034"
    )
    codigos = [a["codigo"] for a in detectar_divergencias(ctx, regra)]
    assert "DIV_VETO_SEM_BASE_NA_LEI" not in codigos
