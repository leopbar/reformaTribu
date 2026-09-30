"""Regimes decididos pela operação (ADR 0026): valem por ramo de atividade, antes das hipóteses do produto.

Funções puras: nada de banco nem de IA. Os trechos e cClassTrib aqui são FIXTURES de teste; a lei real
vem da base oficial do snapshot. Cobre restaurante, padaria, supermercado, farmácia e um varejo sem
regime da operação (autopeças), para garantir que corrigir um ramo não quebra outro.
"""

from __future__ import annotations

from typing import Any

from app.analise import operacao
from app.analise.avaliacao import EntradaAvaliacao, avaliar
from app.analise.identidade import consolidar

GERAL = {
    "id": "HG",
    "titulo": "Tributação integral",
    "tipo": "regra_geral",
    "cclasstrib": "000001",
    "condicoes": [],
    "excecoes": [],
    "fundamentos": [{"ref": "T000001", "trecho": "regra geral"}],
    "explicacao": "",
}
CCT = {
    "000001": {
        "codigo": "000001",
        "cst": "000",
        "nome": "Integral",
        "vigente_na_data": True,
        "permitido_no_documento": True,
        "reducao_ibs_pct": 0.0,
        "reducao_cbs_pct": 0.0,
    },
    "200047": {
        "codigo": "200047",
        "cst": "200",
        "nome": "Bares e Restaurantes",
        "vigente_na_data": True,
        "permitido_no_documento": True,
        "reducao_ibs_pct": 40.0,
        "reducao_cbs_pct": 40.0,
    },
    "200032": {
        "codigo": "200032",
        "cst": "200",
        "nome": "Medicamentos",
        "vigente_na_data": True,
        "permitido_no_documento": True,
        "reducao_ibs_pct": 60.0,
        "reducao_cbs_pct": 60.0,
    },
    "200003": {
        "codigo": "200003",
        "cst": "200",
        "nome": "Cesta básica",
        "vigente_na_data": True,
        "permitido_no_documento": True,
        "reducao_ibs_pct": 100.0,
        "reducao_cbs_pct": 100.0,
    },
}
MATERIAL = operacao.Material(
    refs={
        "OP273": {"tipo": "trecho", "norma": "LC 214/2025", "local": "Art. 273", "id": "a", "texto": "Art. 273 …"},
        "OP274": {"tipo": "trecho", "norma": "LC 214/2025", "local": "Art. 274", "id": "b", "texto": "Art. 274 …"},
        "OP275": {"tipo": "trecho", "norma": "LC 214/2025", "local": "Art. 275", "id": "c", "texto": "Art. 275 …"},
        "OP133": {"tipo": "trecho", "norma": "LC 214/2025", "local": "Art. 133", "id": "d", "texto": "Art. 133 …"},
        "T000001": {"tipo": "cclasstrib", "nome": "Integral"},
        "T200047": {"tipo": "cclasstrib", "nome": "Bares e Restaurantes"},
        "T200032": {"tipo": "cclasstrib", "nome": "Medicamentos"},
        "T200003": {"tipo": "cclasstrib", "nome": "Cesta básica"},
        "P1": {"tipo": "trecho", "norma": "LC 214/2025", "local": "Anexo I, item 1", "id": "e"},
    },
    cclasstrib=CCT,
)
RESTAURANTE = {"segmento": "restaurante", "fornece_refeicoes": "sim"}
PADARIA = {"segmento": "padaria", "fornece_refeicoes": "sim", "produz_alimentos": "sim"}
MERCADO = {"segmento": "supermercado", "fornece_refeicoes": "nao"}
FARMACIA = {"segmento": "farmacia", "manipula_medicamentos": "sim"}
AUTOPECAS = {"segmento": "varejo_geral"}

SEM_NCM = {
    "situacao": "indefinido",
    "tipo_codigo": None,
    "codigo": None,
    "motivo": "nenhum código da tabela oficial descreve o item com segurança",
}


def ncm(codigo: str) -> dict[str, Any]:
    return {
        "situacao": "confirmado",
        "tipo_codigo": "ncm",
        "codigo": codigo,
        "codigo_formatado": codigo,
        "confianca_modelo": 0.96,
        "descricao_suficiente": True,
        "concordancia": True,
        "sinais_de_duvida": [],
    }


def tese(hipoteses: list[dict[str, Any]], is_: str = "nao_sujeito") -> dict[str, Any]:
    return {
        "entendimento": "",
        "hipoteses": hipoteses,
        "fatos_necessarios": [],
        "imposto_seletivo": {"situacao": is_, "condicoes": [], "fundamentos": [], "explicacao": ""},
        "conflitos": [],
        "observacoes": "",
    }


def fato(v: str, origem: str = "descricao") -> dict[str, Any]:
    return {"valor": v, "origem": origem, "origem_rotulo": origem}


def entrada(
    empresa: dict[str, str],
    identidade: dict[str, Any],
    fatos: dict[str, Any] | None = None,
    tese_produto: dict[str, Any] | None = None,
    **kw: Any,
) -> EntradaAvaliacao:
    """Monta a entrada como `aplicacao.entrada` faz: regimes do dossiê, fatos implícitos e material."""
    todos = {k: fato(v, "usuario") for k, v in empresa.items()} | (fatos or {})
    aplic = operacao.regimes_da_empresa(todos)
    todos = {
        **operacao.fatos_implicitos(aplic.regimes, todos, identidade.get("tipo_codigo"), identidade.get("codigo")),
        **todos,
    }
    return EntradaAvaliacao(
        identidade=identidade,
        tese=tese_produto,
        cclasstrib=MATERIAL.cclasstrib,
        refs=MATERIAL.refs,
        fatos=todos,
        operacao=operacao.fundamentar(operacao.hipoteses(aplic.regimes), MATERIAL),
        operacao_fatos=operacao.fatos_necessarios(aplic.regimes),
        operacao_afastada=[f"{r.titulo}: {m}" for r, m in aplic.afastados],
        **kw,
    )


# ------------------------------------------------------------------------------- catálogo --
def test_catalogo_consistente():
    for r in operacao.REGIMES:
        assert len(f"OP-{r.id}") <= 20  # cabe na coluna `hipotese`
        for f, *_ in (*r.condicoes, *r.excecoes):
            assert f in operacao.FATOS, f
    # Só o 200047 é exclusivo: o 200032 também vale para medicamento industrializado (pelo produto).
    assert operacao.cclasstrib_da_operacao() == {"200047"}


def test_regimes_ativados_pelo_dossie_de_cada_ramo():
    ids = lambda e: [r.id for r in operacao.regimes_da_empresa(e).regimes]  # noqa: E731
    assert ids(RESTAURANTE) == ["restaurante"]
    assert ids({"segmento": "restaurante"}) == ["restaurante"]  # o segmento basta
    assert ids(PADARIA) == ["restaurante"]  # padaria com lanchonete
    assert ids(MERCADO) == []
    assert ids(FARMACIA) == ["manipulacao"]
    assert ids(AUTOPECAS) == []
    # Alimentação para empresas sob contrato fica fora do regime (art. 273, § 2º, I).
    aplic = operacao.regimes_da_empresa({**RESTAURANTE, "cnae": "5620-1/01"})
    assert aplic.regimes == [] and aplic.afastados[0][0].id == "restaurante"
    av = avaliar(entrada({**RESTAURANTE, "cnae": "5620-1/01"}, ncm("02013000"), {}, tese([GERAL])))
    assert av.cclasstrib == "000001"
    assert "sob contrato" in av.dimensoes_dict()["contexto"]["texto"]


def test_fatos_implicitos_pelo_codigo_e_pelo_perfil():
    regimes = operacao.regimes_da_empresa(RESTAURANTE).regimes
    imp = operacao.fatos_implicitos(regimes, RESTAURANTE, "ncm", "22030000")
    assert imp["bebida_alcoolica"]["valor"] == "sim" and imp["bebida_alcoolica"]["origem"] == "codigo"
    assert imp["servido_como_alimentacao"]["valor"] == "sim"  # restaurante: presunção da própria lei
    assert operacao.fatos_implicitos(regimes, RESTAURANTE, "ncm", "22011000")["bebida_alcoolica"]["valor"] == "nao"
    assert operacao.fatos_implicitos(regimes, RESTAURANTE, "ncm", "02013000")["bebida_alcoolica"]["valor"] == "nao"
    assert operacao.fatos_implicitos(regimes, RESTAURANTE, "nbs", "103011000")["bebida_alcoolica"]["valor"] == "nao"
    # 22.06 reúne fermentados com e sem álcool (ex.: kombucha): o código não decide.
    assert "bebida_alcoolica" not in operacao.fatos_implicitos(regimes, RESTAURANTE, "ncm", "22060090")
    assert "bebida_alcoolica" not in operacao.fatos_implicitos(regimes, RESTAURANTE, None, None)
    # Padaria não é restaurante: servir como refeição não é presumido.
    reg_pad = operacao.regimes_da_empresa(PADARIA).regimes
    assert "servido_como_alimentacao" not in operacao.fatos_implicitos(reg_pad, PADARIA, "ncm", "19059090")


# ------------------------------------------------------------------------------ restaurante --
def test_espresso_sem_ncm_sai_com_200047():
    """O caso que motivou a ADR: sem NCM, o regime da operação decide o cClassTrib."""
    av = avaliar(
        entrada(RESTAURANTE, SEM_NCM, {"preparado_no_estabelecimento": fato("sim"), "bebida_alcoolica": fato("nao")})
    )
    assert (av.cclasstrib, av.cst, av.hipotese) == ("200047", "200", "OP-restaurante")
    assert av.perc_red_ibs == 40.0
    dims = av.dimensoes_dict()
    assert dims["codigo_fiscal"]["situacao"] == "atencao"  # o NCM segue em paralelo
    assert "não depende" in dims["codigo_fiscal"]["texto"]
    assert dims["imposto_seletivo"]["situacao"] == "atencao"  # sem NCM, o IS não foi avaliado
    assert av.status == "revisao_contador"  # alguém precisa definir o NCM da nota
    assert any(f["local"] == "Art. 273" for f in av.fundamentos)


def test_espresso_sem_ncm_pergunta_se_foi_preparado_quando_nao_sabe():
    av = avaliar(entrada(RESTAURANTE, SEM_NCM, {"bebida_alcoolica": fato("nao")}))
    assert av.cclasstrib is None
    p = next(p for p in av.perguntas if p.atributo == "preparado_no_estabelecimento")
    efeitos = {o["valor"]: o["efeito"] for o in p.opcoes}
    assert "200047" in efeitos["sim"]
    assert "tratamento do produto" in efeitos["nao"]


def test_agua_revendida_nao_vira_200047_mesmo_se_o_jurista_disser():
    """O Jurista escreveu uma hipótese de restaurante sem condição; ela é ignorada (só a operação decide)."""
    jurista = {
        **GERAL,
        "id": "H1",
        "titulo": "Bares e restaurantes",
        "tipo": "regime_especifico",
        "cclasstrib": "200047",
    }
    av = avaliar(
        entrada(RESTAURANTE, ncm("22011000"), {"preparado_no_estabelecimento": fato("nao")}, tese([jurista, GERAL]))
    )
    assert av.cclasstrib == "000001"
    assert av.status == "classificado"


def test_cerveja_sai_do_regime_pela_excecao_do_codigo():
    av = avaliar(
        entrada(
            RESTAURANTE, ncm("22030000"), {"preparado_no_estabelecimento": fato("nao")}, tese([GERAL], is_="sujeito")
        )
    )
    assert av.cclasstrib == "000001" and av.is_situacao == "sujeito"
    op = next(h for h in av.hipoteses_avaliadas if h["id"] == "OP-restaurante")
    assert op["situacao"] == "afastada"


def test_drinque_preparado_com_alcool_fica_fora_do_regime():
    av = avaliar(
        entrada(RESTAURANTE, SEM_NCM, {"preparado_no_estabelecimento": fato("sim"), "bebida_alcoolica": fato("sim")})
    )
    assert av.cclasstrib is None
    regra = av.dimensoes_dict()["regra"]["texto"]
    assert "exceção aplicável" in regra and "depende do NCM" in regra


def test_prato_com_ncm_de_cesta_basica_segue_o_regime_do_restaurante():
    """A operação prevalece sobre o benefício do produto: o regime específico vem antes."""
    cesta = {
        **GERAL,
        "id": "H1",
        "titulo": "Cesta básica",
        "tipo": "beneficio",
        "cclasstrib": "200003",
        "fundamentos": [{"ref": "P1", "trecho": "arroz"}],
    }
    av = avaliar(
        entrada(RESTAURANTE, ncm("10063021"), {"preparado_no_estabelecimento": fato("sim")}, tese([cesta, GERAL]))
    )
    assert av.cclasstrib == "200047" and av.status == "classificado"


# ------------------------------------------------------------------------ outros ramos --
def test_supermercado_sem_refeicoes_nao_tem_regime_da_operacao():
    cesta = {
        **GERAL,
        "id": "H1",
        "titulo": "Cesta básica",
        "tipo": "beneficio",
        "cclasstrib": "200003",
        "fundamentos": [{"ref": "P1", "trecho": "arroz"}],
    }
    ent = entrada(MERCADO, ncm("10063021"), {}, tese([cesta, GERAL]))
    assert ent.operacao == []
    av = avaliar(ent)
    assert av.cclasstrib == "200003" and av.status == "classificado"


def test_padaria_pergunta_se_o_pao_e_servido_como_refeicao():
    """Pão feito na padaria pode ser mercadoria (por quilo) ou lanche servido: a pessoa decide."""
    cesta = {
        **GERAL,
        "id": "H1",
        "titulo": "Cesta básica",
        "tipo": "beneficio",
        "cclasstrib": "200003",
        "fundamentos": [{"ref": "P1", "trecho": "pão"}],
    }
    av = avaliar(entrada(PADARIA, ncm("19059010"), {"preparado_no_estabelecimento": fato("sim")}, tese([cesta, GERAL])))
    assert av.cclasstrib is None and av.status == "aguardando_informacao"
    assert [p.atributo for p in av.perguntas] == ["servido_como_alimentacao"]
    av2 = avaliar(
        entrada(
            PADARIA,
            ncm("19059010"),
            {"preparado_no_estabelecimento": fato("sim"), "servido_como_alimentacao": fato("nao", "usuario")},
            tese([cesta, GERAL]),
        )
    )
    assert av2.cclasstrib == "200003"


def test_farmacia_manipulado_e_industrializado():
    anvisa = {
        **GERAL,
        "id": "H1",
        "titulo": "Medicamento registrado na Anvisa",
        "tipo": "beneficio",
        "cclasstrib": "200032",
        "fundamentos": [{"ref": "P1", "trecho": "medicamentos"}],
    }
    # Manipulado: o regime da operação decide, sem depender do NCM.
    av = avaliar(
        entrada(FARMACIA, SEM_NCM, {"manipulado_no_estabelecimento": fato("sim"), "e_medicamento": fato("sim")})
    )
    assert av.cclasstrib == "200032" and av.hipotese == "OP-manipulacao"
    # Industrializado: a hipótese do Jurista com 200032 continua valendo (o código não é exclusivo).
    av2 = avaliar(
        entrada(FARMACIA, ncm("30049099"), {"manipulado_no_estabelecimento": fato("nao")}, tese([anvisa, GERAL]))
    )
    assert av2.cclasstrib == "200032" and av2.hipotese == "H1"
    # Cosmético manipulado: o NCM do capítulo 33 afasta o regime sem perguntar nada.
    av3 = avaliar(entrada(FARMACIA, ncm("33049990"), {}, tese([GERAL])))
    assert av3.cclasstrib == "000001" and not av3.perguntas


def test_autopecas_segue_so_o_produto_e_nada_muda():
    ent = entrada(AUTOPECAS, ncm("87089990"), {}, tese([GERAL]))
    assert ent.operacao == [] and ent.operacao_fatos == []
    av = avaliar(ent)
    assert av.cclasstrib == "000001" and av.status == "classificado" and not av.perguntas


def test_sem_ncm_e_sem_regime_continua_como_antes():
    av = avaliar(entrada(AUTOPECAS, SEM_NCM))
    assert av.cclasstrib is None and av.status == "revisao_contador"
    assert av.dimensoes_dict()["codigo_fiscal"]["situacao"] == "falha"


# ------------------------------------------------------------------ mensagem da identidade --
def test_motivo_usa_o_parecer_que_decidiu():
    julgamento = {
        "codigo_sugerido": "09019000",
        "confianca": 0.9,
        "nenhum_candidato_serve": False,
        "justificativa": "café torrado",
    }
    segundo = {
        "codigo_sugerido": None,
        "confianca": 0.9,
        "nenhum_candidato_serve": True,
        "justificativa": "bebida pronta; nenhum candidato serve",
    }
    idt = consolidar(
        descricao_normalizada="CAFE ESPRESSO 50ML",
        tipo="produto",
        estrutura={},
        memoria=None,
        julgamento=julgamento,
        julgamento_valido=True,
        escalonamento=segundo,
        escalonamento_valido=True,
        escalonado=True,
        codigo_final=None,
        tipo_codigo_final=None,
        candidatos=[],
        motivos=[],
        arvore={"codigo": None, "erro": None},
    )
    assert idt["situacao"] == "indefinido"
    assert idt["motivo"].startswith("nenhum código da tabela oficial descreve o item")
    assert "busca guiada" in idt["motivo"]


# ------------------------------------------------------- ligações da lei pela natureza (ADR 0027) --
def test_ligacoes_pela_natureza_do_produto():
    from app.analise.natureza import ligacoes

    cods = lambda c: [lg.cclasstrib for lg in ligacoes("ncm", c)]  # noqa: E731
    assert cods("30049036") == ["200009", "200032"]  # Naldecon: medicamento humano
    assert cods("30021590") == ["200053"]  # soros e vacinas
    assert cods("07099990") == ["200036"]  # hortícola in natura fora do Anexo XV
    assert cods("49019900") == ["410008"]  # livro
    assert cods("85234990") == ["410009"]  # fonograma
    assert cods("34011190") == [] and cods("87089990") == [] and cods("22021000") == []
    assert ligacoes("nbs", "103011000") == []


def test_marca_que_e_o_proprio_produto_fica_na_descricao():
    from app.pipeline.normalize import remover_marca

    assert remover_marca("NALDECON PACK", "Naldecon") == "NALDECON PACK"
    assert remover_marca("DORFLEX 36 COMPRIMIDOS", "Dorflex") == "DORFLEX 36 COMPRIMIDOS"
    assert remover_marca("COCA COLA LATA 350ML", "Coca Cola") == "COCA COLA LATA 350ML"
    # A marca continua saindo quando o resto diz o que o produto é.
    assert remover_marca("CAFÉ SÃO JOSÉ 500G", "Sao Jose") == "CAFÉ 500G"
    assert remover_marca("DIPIRONA EMS 500MG 10 COMP", "EMS") == "DIPIRONA 500MG 10 COMP"
