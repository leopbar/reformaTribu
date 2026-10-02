"""Analista fiscal: escolha de hipóteses, perguntas decisivas, confiança por dimensão e validação da tese.

Funções puras: nada de banco nem de IA. Os códigos são FIXTURES de teste, não a base legal.
"""

from __future__ import annotations

from typing import Any

from app.analise.avaliacao import EntradaAvaliacao, avaliar, escolher
from app.analise.evidencias import Evidencias
from app.analise.fatos import chave, valor
from app.analise.identidade import consolidar
from app.analise.investigacao import validar

SUCO = [
    {
        "id": "H1",
        "titulo": "Anexo VII — suco sem açúcar",
        "tipo": "beneficio",
        "cclasstrib": "200034",
        "condicoes": [{"fato": "adicao_acucar", "valor_exigido": "nao", "explicacao": ""}],
        "excecoes": [],
        "fundamentos": [{"ref": "P1", "trecho": "sucos sem adição de açúcar"}],
        "explicacao": "Redução de 60%.",
    },
    {
        "id": "H2",
        "titulo": "Tributação integral",
        "tipo": "regra_geral",
        "cclasstrib": "000001",
        "condicoes": [],
        "excecoes": [],
        "fundamentos": [{"ref": "T000001", "trecho": "regra geral"}],
        "explicacao": "",
    },
]
CCT = {
    "200034": {
        "codigo": "200034",
        "cst": "200",
        "nome": "Anexo VII",
        "vigente_na_data": True,
        "permitido_no_documento": True,
        "reducao_ibs_pct": 60.0,
        "reducao_cbs_pct": 60.0,
    },
    "000001": {
        "codigo": "000001",
        "cst": "000",
        "nome": "Integral",
        "vigente_na_data": True,
        "permitido_no_documento": True,
        "reducao_ibs_pct": 0.0,
        "reducao_cbs_pct": 0.0,
    },
}
REFS = {
    "P1": {"tipo": "trecho", "norma": "LC 214/2025", "local": "Anexo VII, item 9", "id": "x"},
    "C1": {"tipo": "correlacao", "cclasstrib": "200034"},
    "T000001": {"tipo": "cclasstrib", "nome": "Integral"},
    "T200034": {"tipo": "cclasstrib", "nome": "Anexo VII"},
}
IDENTIDADE_OK = {
    "situacao": "confirmado",
    "tipo_codigo": "ncm",
    "codigo": "20096100",
    "codigo_formatado": "2009.61.00",
    "confianca_modelo": 0.96,
    "descricao_suficiente": True,
    "concordancia": True,
    "sinais_de_duvida": [],
}


def tese(hipoteses: list[dict[str, Any]] = SUCO, **extra: Any) -> dict[str, Any]:
    return {
        "entendimento": "sucos de uva",
        "hipoteses": hipoteses,
        "fatos_necessarios": [
            {
                "fato": "adicao_acucar",
                "escopo": "item",
                "pergunta": "O suco tem adição de açúcar?",
                "opcoes": ["sim", "nao"],
                "como_identificar_na_descricao": "INTEGRAL",
            }
        ],
        "imposto_seletivo": {"situacao": "nao_sujeito", "condicoes": [], "fundamentos": [], "explicacao": ""},
        "conflitos": [],
        "observacoes": "",
        **extra,
    }


def fato(v: str, origem: str = "usuario") -> dict[str, Any]:
    return {"valor": v, "origem": origem, "origem_rotulo": origem}


def entrada(fatos: dict[str, Any] | None = None, **kw: Any) -> EntradaAvaliacao:
    base: dict[str, Any] = {
        "identidade": IDENTIDADE_OK,
        "tese": tese(),
        "cclasstrib": CCT,
        "refs": REFS,
        "fatos": fatos or {},
        "correlacionados": ["200034"],
    }
    base.update(kw)
    return EntradaAvaliacao(**base)


# ------------------------------------------------------------------------------ hipóteses --
def test_fato_desconhecido_gera_pergunta_com_efeitos():
    h, faltando, _ = escolher(SUCO, {})
    assert h is None and faltando == ["adicao_acucar"]
    av = avaliar(entrada())
    assert av.status == "aguardando_informacao"
    assert av.nivel == "operacional"
    assert av.confianca_global == "incompleta"
    p = av.perguntas[0]
    assert p.atributo == "adicao_acucar" and p.escopo == "item"
    efeitos = {o["valor"]: o["efeito"] for o in p.opcoes}
    assert "200034" in efeitos["nao"] and "000001" in efeitos["sim"]
    assert av.cclasstrib is None


def test_fato_confirmado_escolhe_beneficio_com_fundamento():
    av = avaliar(entrada({"adicao_acucar": fato("nao")}))
    assert av.status == "classificado" and av.confianca_global == "alta"
    assert (av.hipotese, av.cclasstrib, av.cst) == ("H1", "200034", "200")
    assert av.perc_red_cbs == 60.0
    assert av.fatos_usados[0]["atributo"] == "adicao_acucar"
    assert av.fundamentos[0]["local"] == "Anexo VII, item 9"
    assert "Fatos determinantes" in av.conclusao
    assert all(d.situacao == "ok" for d in av.dimensoes)


def test_condicao_nao_atendida_cai_na_regra_geral():
    av = avaliar(entrada({"adicao_acucar": fato("sim")}))
    assert av.status == "classificado" and av.cclasstrib == "000001"
    h1 = next(a for a in av.hipoteses_avaliadas if a["id"] == "H1")
    assert h1["situacao"] == "afastada"


def test_pergunta_irrelevante_nao_e_feita():
    # As duas hipóteses levam ao mesmo cClassTrib: a informação que falta não muda nada.
    iguais = [dict(SUCO[0], cclasstrib="000001"), SUCO[1]]
    av = avaliar(entrada(tese=tese(iguais)))
    assert av.perguntas == [] and av.cclasstrib == "000001"


def test_excecao_confirmada_afasta_hipotese():
    com_excecao = [
        dict(
            SUCO[0],
            condicoes=[],
            excecoes=[{"descricao": "néctar", "fato": "e_nectar", "valor_que_exclui": "sim"}],
        ),
        SUCO[1],
    ]
    av = avaliar(entrada({"e_nectar": fato("sim")}, tese=tese(com_excecao)))
    assert av.cclasstrib == "000001"


def test_beneficio_sem_fundamento_normativo_vai_ao_especialista():
    sem_fonte = [dict(SUCO[0], fundamentos=[{"ref": "P99", "trecho": "inventado"}]), SUCO[1]]
    av = avaliar(entrada({"adicao_acucar": fato("nao")}, tese=tese(sem_fonte)))
    assert av.status == "revisao_especialista"
    assert next(d for d in av.dimensoes if d.chave == "fonte").situacao == "falha"


def test_correlacao_oficial_ignorada_e_conflito():
    so_geral = [SUCO[1]]
    av = avaliar(entrada(tese=tese(so_geral), correlacionados=["200034"]))
    d = next(d for d in av.dimensoes if d.chave == "conflito")
    assert d.situacao == "atencao" and "200034" in d.texto
    assert av.status == "revisao_contador"


def test_regra_aprovada_divergente_e_conflito_grave():
    prec = [{"ref": "R1", "cclasstrib": "200034", "condicoes": [], "dispositivo": "Anexo VII"}]
    av = avaliar(entrada({"adicao_acucar": fato("sim")}, precedentes=prec))
    assert av.status == "revisao_especialista"
    assert "CONFLITO_NORMATIVO" in av.motivos


def test_identificacao_duvidosa_vai_ao_contador_mesmo_com_tese():
    idt = {**IDENTIDADE_OK, "situacao": "corrigido", "concordancia": False, "codigo_anterior": "20096900"}
    av = avaliar(entrada({"adicao_acucar": fato("nao")}, identidade=idt))
    assert av.status == "revisao_contador" and av.nivel == "contador"


def test_sem_codigo_nao_ha_tese():
    av = avaliar(entrada(identidade={"situacao": "indefinido", "motivo": "descrição genérica"}, tese=None))
    assert av.status == "revisao_contador"
    assert av.cclasstrib is None


def test_imposto_seletivo_dependente_de_fato():
    t = tese(
        [SUCO[1]],
        imposto_seletivo={
            "situacao": "depende",
            "condicoes": [{"fato": "adicao_acucar", "valor_exigido": "sim", "explicacao": ""}],
            "fundamentos": [],
            "explicacao": "bebidas açucaradas",
        },
    )
    pend = avaliar(entrada(tese=t, correlacionados=[]))
    assert pend.is_situacao == "indefinido" and pend.status == "aguardando_informacao"
    fabrica = {"adicao_acucar": fato("sim"), "fabrica_ou_importa_seletivo": fato("sim")}
    sujeito = avaliar(entrada(fabrica, tese=t, correlacionados=[]))
    assert sujeito.is_situacao == "sujeito"
    assert sujeito.status == "revisao_contador"  # a organização exige conferência do IS
    livre = avaliar(entrada(fabrica, tese=t, correlacionados=[], is_exige_analise=False))
    assert livre.status == "classificado"


# ---------------------------------------------------------------------------- validação --
def test_validacao_descarta_cclasstrib_fora_da_lista_e_garante_regra_geral():
    ev = Evidencias(pacote={}, refs=REFS, cclasstrib=CCT)
    dados = tese(
        [
            dict(SUCO[0], cclasstrib="999999"),
            dict(SUCO[0], id="H3", condicoes=[{"fato": "Adição de Açúcar", "valor_exigido": "Não", "explicacao": ""}]),
        ]
    )
    resultado, rel = validar(dados, ev)
    assert rel["hipoteses_descartadas"][0]["cclasstrib"] == "999999"
    assert [h["id"] for h in resultado["hipoteses"]] == ["H3", "HG"]
    assert resultado["hipoteses"][0]["condicoes"][0]["fato"] == "adicao_de_acucar"
    assert rel["regra_geral_incluida"] is True


def test_normalizacao_de_fatos():
    assert chave("Adição de açúcar?") == "adicao_de_acucar"
    assert valor("Não") == "nao" and valor(True) == "sim" and valor(None) == "desconhecido"


# ---------------------------------------------------------------------------- identidade --
def _consolidar(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "descricao_normalizada": "sabonete liquido",
        "tipo": "produto",
        "estrutura": {"codigo_atual": {"tipo": "ncm", "codigo": "34011190", "existe": True, "folha": True}},
        "memoria": None,
        "julgamento": {"codigo_sugerido": "34013000", "confianca": 0.9, "descricao_suficiente": True},
        "julgamento_valido": True,
        "escalonamento": {"codigo_sugerido": "34013000", "confianca": 0.95, "descricao_suficiente": True},
        "escalonamento_valido": True,
        "escalonado": True,
        "codigo_final": "34013000",
        "tipo_codigo_final": "ncm",
        "candidatos": [{"codigo": "34013000", "descricao_completa": "líquido"}],
        "motivos": ["NCM_INCOERENTE_COM_DESCRICAO"],
    }
    base.update(kw)
    return consolidar(**base)


def test_identidade_corrigida_com_concordancia():
    i = _consolidar()
    assert i["situacao"] == "corrigido" and i["concordancia"] is True
    assert i["codigo_anterior"] == "34011190"
    assert i["problemas_cadastro"] == ["NCM_INCOERENTE_COM_DESCRICAO"]


def test_identidade_confirmada_e_indefinida():
    ok = _consolidar(
        codigo_final="34011190",
        julgamento={"codigo_sugerido": "34011190", "confianca": 0.97, "ncm_atual_coerente": True},
        escalonado=False,
        escalonamento=None,
        escalonamento_valido=False,
    )
    assert ok["situacao"] == "confirmado"
    nada = _consolidar(codigo_final=None, julgamento={"nenhum_candidato_serve": True}, escalonado=False)
    assert nada["situacao"] == "indefinido" and "nenhum código" in nada["motivo"]


# ------------------------------------------------------------------------------ economia --
def test_marca_nao_entra_na_analise():
    from app.pipeline.normalize import remover_marca

    assert remover_marca("ARROZ TIPO 1 ESTRELA 5KG", "Estrela") == "ARROZ TIPO 1 5KG"
    assert remover_marca("LEITE UHT INTEG VALE VERDE 1L", "Vale Verde") == "LEITE UHT INTEG 1L"
    assert remover_marca("CAFÉ SÃO JOSÉ 500G", "Sao Jose") == "CAFÉ 500G"
    assert remover_marca("PAO FRANCES KG", "Produção própria") == "PAO FRANCES KG"
    assert remover_marca("ARROZ 5KG", None) == "ARROZ 5KG"


def test_confirmacao_sem_ia_exige_dois_sinais():
    from app.pipeline.nodes import _confirmacao_sem_ia
    from app.pipeline.state import ItemState

    st = ItemState(item_id="1", audit_id="1", org_id="1")
    atual = {"tipo": "ncm", "codigo": "10063021", "existe": True, "folha": True, "vigente": True}

    def cand(pos: int, sem: int | None, txt: int | None) -> list[dict[str, Any]]:
        return [{"codigo": "10063021", "posicao": pos, "rank_semantico": sem, "rank_textual": txt}]

    assert _confirmacao_sem_ia(st, atual, cand(1, 1, 1)) == {
        "confirmado_sem_ia": True,
        "tipo_codigo_final": "ncm",
        "codigo_final": "10063021",
        "posicao_confirmacao": 1,
    }
    assert _confirmacao_sem_ia(st, atual, cand(1, 1, 4)) is None  # as palavras apontam outro código
    assert _confirmacao_sem_ia(st, atual, cand(1, None, 1)) is None
    assert _confirmacao_sem_ia(st, {**atual, "vigente": False}, cand(1, 1, 1)) is None
    curta = ItemState(item_id="1", audit_id="1", org_id="1", estrutura={"descricao_curta": True})
    assert _confirmacao_sem_ia(curta, atual, cand(1, 1, 1)) is None


def test_impressao_da_tese_ignora_metadados_dos_alertas() -> None:
    """Uma nova coleta da base com o mesmo material jurídico não pode refazer a tese."""
    from app.analise.investigacao import impressao_evidencias

    alerta = {"regra": "Anexo IX", "descricao": "restrição textual", "gravidade": "media", "cclasstrib": "200038"}
    antes = {
        "codigo": {"codigo": "10063021"},
        "trechos_normativos": [{"ref": "P1", "texto": "Arroz"}],
        "alertas_de_divergencia": [alerta],
    }
    depois = {**antes, "alertas_de_divergencia": [{**alerta, "codigos": ["1006"]}]}
    assert impressao_evidencias(antes) == impressao_evidencias(depois)
    mudou = {**antes, "trechos_normativos": [{"ref": "P1", "texto": "Arroz e feijão"}]}
    assert impressao_evidencias(antes) != impressao_evidencias(mudou)


# ------------------------------------------------------------------------ conflitos reais --
def test_conflito_que_nao_muda_o_resultado_nao_trava_o_item() -> None:
    coerente = {"descricao": "C1 é consistente com o Anexo VII.", "refs": ["C1", "P1"], "muda_resultado": False}
    av = avaliar(entrada({"adicao_acucar": fato("nao")}, tese=tese(conflitos=[coerente])))
    assert av.status == "classificado"


def test_conflito_antigo_so_trava_se_apontar_outro_cclasstrib_permitido() -> None:
    # Versão antiga do parecer (sem `muda_resultado`): cita só o cClassTrib aplicado e um vedado.
    refs = {**REFS, "C2": {"tipo": "correlacao", "cclasstrib": "000001", "permissao": "VEDADO"}}
    so_vedado = {"descricao": "C2 veda o código por já estar no Anexo VII.", "refs": ["C1", "C2"]}
    av = avaliar(entrada({"adicao_acucar": fato("nao")}, tese=tese(conflitos=[so_vedado]), refs=refs))
    assert av.status == "classificado"
    # Aponta outro cClassTrib permitido: vai ao especialista.
    real = {"descricao": "A lei diz 200034, a correlação diz 000001.", "refs": ["P1"], "muda_resultado": True}
    av = avaliar(entrada({"adicao_acucar": fato("nao")}, tese=tese(conflitos=[real])))
    assert av.status == "revisao_especialista"
    assert "CONFLITO_NORMATIVO" in av.motivos


# ------------------------------------------------------ dúvida de identificação imaterial --
DUVIDA = {
    **IDENTIDADE_OK,
    "confianca_modelo": 0.8,
    "sinais_de_duvida": ["não informa se tem açúcar"],
    "codigos_alternativos": ["20096900"],
}


def test_duvida_que_nao_muda_o_imposto_nao_manda_ao_contador() -> None:
    mesmo = {"20096900": "200034|nao_sujeito"}
    av = avaliar(entrada({"adicao_acucar": fato("nao")}, identidade=DUVIDA, tratamento_alternativas=mesmo))
    assert av.status == "classificado"
    ident = next(d for d in av.dimensoes if d.chave == "identificacao")
    assert "não muda o imposto" in ident.texto


def test_duvida_que_muda_o_imposto_vira_pergunta_ao_operador() -> None:
    muda = {"20096900": "000001|nao_sujeito"}
    av = avaliar(entrada({"adicao_acucar": fato("nao")}, identidade=DUVIDA, tratamento_alternativas=muda))
    assert av.status == "aguardando_informacao" and av.nivel == "operacional"
    p = next(p for p in av.perguntas if p.atributo == "codigo_do_item")
    assert [o["valor"] for o in p.opcoes] == ["20096100", "20096900", "outro"]
    assert "200034" in p.opcoes[0]["efeito"] and "000001" in p.opcoes[1]["efeito"]
    assert p.grupo == "ident:20096100-20096900"
    # Respondida com "nenhuma destas": o contador decide.
    outro = {"adicao_acucar": fato("nao"), "codigo_do_item": fato("outro")}
    av = avaliar(entrada(outro, identidade=DUVIDA, tratamento_alternativas=muda))
    assert av.status == "revisao_contador"
    # Imposto de uma opção ainda desconhecido (pode mudar): também pergunta, e diz o que a lei cita.
    av = avaliar(
        entrada(
            {"adicao_acucar": fato("nao")},
            identidade=DUVIDA,
            tratamento_alternativas={"20096900": None},
            beneficios_em_disputa={"20096900": "Anexo VII – Alimentos"},
        )
    )
    assert av.status == "aguardando_informacao"
    p = next(p for p in av.perguntas if p.atributo == "codigo_do_item")
    assert "depois da resposta" in p.opcoes[1]["efeito"] and "Anexo VII" in p.opcoes[1]["efeito"]
    assert "O imposto depende da resposta" in p.pergunta


def test_duvida_entre_capitulos_com_certeza_media_pergunta_o_que_e_o_item() -> None:
    """Salada pronta (ADR 0029): sem NCM no ERP, o Navegador sugeriu "hortícolas preparados" com 60% e trouxe
    o código do outro capítulo (verdura fresca). Os impostos diferem: pergunta ao operador, não ao contador."""
    idt = {
        **IDENTIDADE_OK,
        "situacao": "sugerido",
        "via_arvore": True,
        "codigo": "20059900",
        "codigo_formatado": "2005.99.00",
        "codigo_erp": None,
        "confianca_modelo": 0.6,
        "codigos_em_disputa": ["07099990", "20051000"],
        "rotulos_em_disputa": {"20059900": "salada temperada ou com molho", "07099990": "verduras frescas cortadas"},
        "descricoes_em_disputa": {"20051000": "Outros produtos hortícolas › Produtos hortícolas homogeneizados"},
    }
    trat = {"07099990": "200014|nao_sujeito", "20051000": "="}
    av = avaliar(entrada({"adicao_acucar": fato("nao")}, identidade=idt, tratamento_alternativas=trat))
    assert av.status == "aguardando_informacao"
    p = next(p for p in av.perguntas if p.atributo == "codigo_do_item")
    # A opção de mesmo imposto (homogeneizados) não ajuda a decidir: fica fora da lista.
    assert [o["valor"] for o in p.opcoes] == ["20059900", "07099990", "outro"]
    assert p.opcoes[1]["rotulo"].startswith("verduras frescas cortadas") and "200014" in p.opcoes[1]["efeito"]
    # Com certeza muito baixa, nem a pergunta: o contador.
    av = avaliar(
        entrada(
            {"adicao_acucar": fato("nao")}, identidade={**idt, "confianca_modelo": 0.3}, tratamento_alternativas=trat
        )
    )
    assert av.status == "revisao_contador"
    # Com o mesmo imposto em todas as opções, a certeza média não basta para liberar sozinho.
    av = avaliar(
        entrada(
            {"adicao_acucar": fato("nao")}, identidade=idt, tratamento_alternativas={"07099990": "=", "20051000": "="}
        )
    )
    assert av.status == "revisao_contador"


def test_capitulo_em_duvida_sem_codigo_impede_liberar_sozinho() -> None:
    """Salada pronta, 2ª reanálise: certeza de 70% e alternativas do mesmo capítulo (mesmo imposto), mas o
    capítulo de verdura fresca ficou sem código. Não dá para dizer que o imposto não muda: contador."""
    idt = {
        **IDENTIDADE_OK,
        "situacao": "sugerido",
        "via_arvore": True,
        "codigo_erp": None,
        "confianca_modelo": 0.7,
        "codigos_em_disputa": ["20051000"],
        "arvore": {"capitulos_em_aberto": ["07"]},
    }
    av = avaliar(entrada({"adicao_acucar": fato("nao")}, identidade=idt, tratamento_alternativas={"20051000": "="}))
    assert av.status == "revisao_contador" and not av.ajuste_cadastro
    # Sem capítulo em aberto, a mesma situação libera o IBS/CBS e manda o NCM para "Ajustes de cadastro".
    idt["arvore"] = {}
    av = avaliar(entrada({"adicao_acucar": fato("nao")}, identidade=idt, tratamento_alternativas={"20051000": "="}))
    assert av.status == "classificado" and av.ajuste_cadastro


def test_titulo_do_anexo_curto_com_a_reducao() -> None:
    from app.analise.aplicacao import _titulo_do_anexo

    longo = "PRODUTOS HORTÍCOLAS, FRUTAS E OVOS SUBMETIDOS À REDUÇÃO DE 100% (CEM POR CENTO) DAS ALÍQUOTAS DO IBS"
    assert _titulo_do_anexo(longo) == "Produtos hortícolas, frutas e ovos (redução de 100%)"
    assert _titulo_do_anexo("Alimentos submetidos à redução a zero das alíquotas") == "Alimentos (redução a zero)"
    assert _titulo_do_anexo("Dispositivos médicos") == "Dispositivos médicos"


def test_nome_oficial_pula_os_niveis_outros() -> None:
    from app.analise.avaliacao import _nome_oficial

    desc = "Outros produtos hortícolas preparados › Outros produtos hortícolas e misturas › Outros"
    assert _nome_oficial(desc) == "Outros produtos hortícolas e misturas (outros)"
    assert _nome_oficial("Suco de uva › Com valor Brix até 30") == "Com valor Brix até 30"
    assert _nome_oficial("") == ""


# ------------------------------------------------------------ checagem cruzada com os anexos --
def test_nome_do_produto_no_anexo() -> None:
    from app.analise.anexos import _cita, nome_do_produto

    assert nome_do_produto("Água sanitária classificada no código 3808.94.19 da NCM/SH") == "agua sanitaria"
    assert nome_do_produto("Arroz das subposições 1006.20 e 1006.30") == "arroz"
    assert _cita("agua sanitaria 2 l", "agua sanitaria")
    assert _cita("arroz branco tipo 1", "arroz")
    assert not _cita("biscoito de arroz", "arroz")


def test_produto_citado_na_lei_com_outro_codigo_vai_ao_contador() -> None:
    citado = [{"anexo": "VIII", "item": "5", "produto": "agua sanitaria", "codigos": ["3808.94.19"]}]
    av = avaliar(entrada({"adicao_acucar": fato("nao")}, produtos_na_lei=citado))
    assert av.status == "revisao_contador"
    assert "PRODUTO_CITADO_NA_LEI" in av.motivos
    cod = next(d for d in av.dimensoes if d.chave == "codigo_fiscal")
    assert "3808.94.19" in cod.texto


def test_ncm_criado_com_imposto_igual_vai_para_ajuste_de_cadastro() -> None:
    """ADR 0029: o IBS/CBS sai; o NCM novo é confirmado na lista "Ajustes de cadastro", sem travar o item."""
    mesmo = {"20096900": "200034|nao_sujeito"}
    idt = {**DUVIDA, "situacao": "sugerido", "codigo_erp": None}
    av = avaliar(entrada({"adicao_acucar": fato("nao")}, identidade=idt, tratamento_alternativas=mesmo))
    assert av.status == "classificado" and av.cclasstrib == "200034"
    assert av.ajuste_cadastro["sugerido"] == "20096100" and av.ajuste_cadastro["erp"] is None
    cod = next(d for d in av.dimensoes if d.chave == "codigo_fiscal")
    assert "a confirmar no cadastro" in cod.texto


def test_duvida_imaterial_com_descricao_vaga_ou_certeza_baixa_continua_com_o_contador() -> None:
    mesmo = {"20096900": "200034|nao_sujeito"}
    casos = [
        {**DUVIDA, "situacao": "sugerido", "codigo_erp": None, "descricao_suficiente": False},  # sem âncora
        {**DUVIDA, "situacao": "sugerido", "codigo_erp": None, "confianca_modelo": 0.64},  # certeza baixa
    ]
    for idt in casos:
        av = avaliar(entrada({"adicao_acucar": fato("nao")}, identidade=idt, tratamento_alternativas=mesmo))
        assert av.status == "revisao_contador", idt
    # Com o NCM do ERP entre as opções (âncora), a descrição vaga não impede.
    ancorado = {**DUVIDA, "descricao_suficiente": False, "codigo_erp": "20096100"}
    av = avaliar(entrada({"adicao_acucar": fato("nao")}, identidade=ancorado, tratamento_alternativas=mesmo))
    assert av.status == "classificado" and not av.ajuste_cadastro


# ---------------------------------------------------- menos revisão humana (ADR 0029) --
def test_erp_e_segundo_parecer_formam_dois_votos() -> None:
    """O primeiro parecer errou (açúcar → "em bruto"); o segundo ficou com o NCM do ERP: confirmado."""
    i = _consolidar(
        estrutura={"codigo_atual": {"tipo": "ncm", "codigo": "17019900", "existe": True, "folha": True}},
        julgamento={"codigo_sugerido": "17011400", "confianca": 0.95, "ncm_atual_coerente": False},
        escalonamento={"codigo_sugerido": "17019900", "confianca": 0.95, "ncm_atual_coerente": True},
        codigo_final="17019900",
        candidatos=[
            {"codigo": "17019900", "descricao_completa": "outros"},
            {"codigo": "17011400", "descricao_completa": "em bruto"},
        ],
        motivos=[],
    )
    assert i["situacao"] == "confirmado" and i["dois_votos"] is True and i["concordancia"] is True
    assert "17011400" not in i["codigos_em_disputa"]  # o primeiro parecer perdeu de dois a um
    assert "NCM_INCOERENTE_COM_DESCRICAO" not in i["problemas_cadastro"]


def test_codigo_mantido_com_marcacao_contraditoria_nao_vira_correcao_de_a_para_a() -> None:
    """Café: o segundo parecer escolheu o NCM do ERP, mas marcou "não coerente". Antes: "corrigido de A para A"."""
    i = _consolidar(
        estrutura={"codigo_atual": {"tipo": "ncm", "codigo": "09012100", "existe": True, "folha": True}},
        julgamento={"codigo_sugerido": "09019000", "confianca": 0.95, "ncm_atual_coerente": False},
        escalonamento={"codigo_sugerido": "09012100", "confianca": 0.78, "ncm_atual_coerente": False},
        codigo_final="09012100",
        candidatos=[{"codigo": "09012100", "descricao_completa": "torrado"}],
        motivos=[],
    )
    assert i["situacao"] == "confirmado"
    assert i["codigo_erp"] == "09012100"


def test_dois_votos_tornam_a_duvida_hipotetica_uma_observacao() -> None:
    idt = {
        **IDENTIDADE_OK,
        "concordancia": False,
        "segundo_parecer": True,
        "dois_votos": True,
        "confianca_modelo": 0.95,
        "confianca_parecer": 0.95,
        "sinais_de_duvida": ["Se for queijo fundido, seria 0406.30.00"],
        "codigos_alternativos": ["04063000"],
    }
    av = avaliar(entrada({"adicao_acucar": fato("nao")}, identidade=idt, tratamento_alternativas={"04063000": None}))
    assert av.status == "classificado"
    assert "pontos observados" in next(d for d in av.dimensoes if d.chave == "identificacao").texto


def test_duvida_sem_palavra_da_descricao_vira_observacao() -> None:
    from app.analise.avaliacao import _separar_duvidas

    duvidas = [
        {"duvida": "zero indica edulcorante", "trecho": "ZERO"},
        {"duvida": "se fosse descafeinado, seria outro código", "trecho": ""},
        {"duvida": "pode ser fundido", "trecho": "FUNDIDO"},
    ]
    apoiadas, hipoteticas = _separar_duvidas(duvidas, "refrigerante cola zero 350ml")
    assert apoiadas == ["zero indica edulcorante (“ZERO”)"]
    assert hipoteticas == ["se fosse descafeinado, seria outro código", "pode ser fundido"]


def test_codigo_novo_com_mesma_assinatura_juridica_nao_muda_o_imposto() -> None:
    idt = {
        **DUVIDA,
        "situacao": "corrigido",
        "concordancia": False,
        "codigo_erp": "20096900",
        "codigo_anterior": "20096900",
    }
    av = avaliar(entrada({"adicao_acucar": fato("nao")}, identidade=idt, tratamento_alternativas={"20096900": "="}))
    assert av.status == "classificado"
    assert av.ajuste_cadastro["erp"] == "20096900" and av.ajuste_cadastro["sugerido"] == "20096100"
    # Sem comparar o código do ERP, nada se conclui.
    av = avaliar(entrada({"adicao_acucar": fato("nao")}, identidade=idt, tratamento_alternativas={}))
    assert av.status == "revisao_contador"


IS_SUJEITO = {"situacao": "sujeito", "condicoes": [], "fundamentos": [], "explicacao": "Anexo XVII"}


def test_imposto_seletivo_na_revenda_nao_vai_ao_contador() -> None:
    t = tese([SUCO[1]], imposto_seletivo=IS_SUJEITO)
    revenda = avaliar(entrada({"fabrica_ou_importa_seletivo": fato("nao")}, tese=t, correlacionados=[]))
    assert revenda.status == "classificado" and revenda.is_situacao == "na_origem"
    assert "SUJEITO_A_IMPOSTO_SELETIVO" not in revenda.motivos
    assert "não incide na revenda" in revenda.conclusao
    # Sem saber se a empresa fabrica ou importa: uma pergunta para a empresa toda, não uma revisão por item.
    nao_sei = avaliar(entrada(tese=t, correlacionados=[]))
    assert nao_sei.status == "aguardando_informacao"
    p = next(p for p in nao_sei.perguntas if p.atributo == "fabrica_ou_importa_seletivo")
    assert p.escopo == "empresa"
    fabrica = avaliar(entrada({"fabrica_ou_importa_seletivo": fato("sim")}, tese=t, correlacionados=[]))
    assert fabrica.status == "revisao_contador" and "SUJEITO_A_IMPOSTO_SELETIVO" in fabrica.motivos


def test_decisao_de_pessoa_com_is_na_origem_conta_como_sujeito() -> None:
    from app.analise.decisoes import resultado

    assert resultado("000001", "na_origem") == resultado("000001", "sujeito") == "000001|sujeito"


def _conflito_com_fato(**kw: Any) -> dict[str, Any]:
    return {
        "descricao": "A correlação do Anexo IX (ração) também cita o código.",
        "refs": ["C1"],
        "muda_resultado": True,
        "cclasstrib_em_jogo": ["200034", "000001"],
        "fato_que_decide": "destinado_a_racao",
        "valor_para_o_outro_enquadramento": "sim",
        **kw,
    }


def test_conflito_amarrado_a_um_fato_e_resolvido_pelo_fato() -> None:
    t = tese(conflitos=[_conflito_com_fato()])
    resolvido = avaliar(entrada({"adicao_acucar": fato("nao"), "destinado_a_racao": fato("nao")}, tese=t))
    assert resolvido.status == "classificado"
    assert "resolvido pelo fato" in next(d for d in resolvido.dimensoes if d.chave == "conflito").texto
    pendente = avaliar(entrada({"adicao_acucar": fato("nao")}, tese=t))
    assert pendente.status == "aguardando_informacao"
    assert any(p.atributo == "destinado_a_racao" for p in pendente.perguntas)
    outro = avaliar(entrada({"adicao_acucar": fato("nao"), "destinado_a_racao": fato("sim")}, tese=t))
    assert outro.status == "revisao_especialista"
    # Sem fato que decida (contradição da própria lei ou tabela): o especialista resolve.
    sem = tese(conflitos=[_conflito_com_fato(fato_que_decide="")])
    assert avaliar(entrada({"adicao_acucar": fato("nao")}, tese=sem)).status == "revisao_especialista"


def test_cclasstrib_de_outro_cenario_nao_disputa_a_venda_ao_consumidor() -> None:
    cct = {**CCT, "515001": {"codigo": "515001", "cst": "515", "nome": "Operações, sujeitas a diferimento"}}
    c = {"descricao": "A correlação também cita 515001.", "refs": ["C1"], "cclasstrib_em_jogo": ["200034", "515001"]}
    av = avaliar(entrada({"adicao_acucar": fato("nao")}, tese=tese(conflitos=[c]), cclasstrib=cct))
    assert av.status == "classificado"


def test_restricao_em_palavras_conferida_pelos_fatos_nao_trava() -> None:
    alerta = {
        "descricao": "A lei restringe o benefício em palavras, e a regra não tem condição: “sem adição de açúcar”",
        "gravidade": "media",
        "cclasstrib": "200034",
        "codigos": [],
    }
    av = avaliar(entrada({"adicao_acucar": fato("nao")}, alertas=[alerta]))
    assert av.status == "classificado"
    sem_condicao = [dict(SUCO[0], condicoes=[]), SUCO[1]]
    av = avaliar(entrada({"adicao_acucar": fato("nao")}, alertas=[alerta], tese=tese(sem_condicao)))
    assert av.status == "revisao_contador"


def test_servico_de_alimentacao_numa_empresa_sem_refeicoes_vai_ao_contador() -> None:
    nbs = {
        **IDENTIDADE_OK,
        "tipo_codigo": "nbs",
        "codigo": "103012200",
        "codigo_formatado": "1.0301.22.00",
        "situacao": "sugerido",
        "codigo_erp": None,
        "confianca_modelo": 0.9,
    }
    geral = tese([SUCO[1]])
    av = avaliar(entrada({"fornece_refeicoes": fato("nao")}, identidade=nbs, tese=geral, tratamento_alternativas={}))
    assert av.status == "revisao_contador"
    assert "não serve refeições" in next(d for d in av.dimensoes if d.chave == "identificacao").texto
    assert not av.ajuste_cadastro


def test_falha_da_plataforma_nao_e_duvida_sobre_o_item() -> None:
    from app.llm import gateway, provedores

    assert gateway.plataforma_indisponivel(provedores.ErroTransitorio("HTTP 429: no credits remaining"))
    assert gateway.plataforma_indisponivel(provedores.ErroDefinitivo("HTTP 400: credit balance is too low"))
    assert not gateway.plataforma_indisponivel(provedores.ErroDefinitivo("HTTP 400: schema inválido"))
    assert "créditos" in gateway._mensagem_falha(provedores.ErroTransitorio("You have no credits remaining"))


def test_imposto_seletivo_so_para_codigos_do_anexo_xvii() -> None:
    """O parecer disse "depende de açúcar" para 2202.99.00, mas o Anexo XVII só lista 2202.10.00."""
    depende = {
        "situacao": "depende",
        "condicoes": [{"fato": "adicao_acucar", "valor_exigido": "sim", "explicacao": ""}],
        "fundamentos": [],
        "explicacao": "bebida açucarada",
    }
    t = tese([SUCO[1]], imposto_seletivo=depende)
    fora = avaliar(entrada(tese=t, correlacionados=[], is_no_anexo_xvii=False))
    assert fora.is_situacao == "nao_sujeito" and fora.status == "classificado"
    assert not any(p.atributo == "adicao_acucar" for p in fora.perguntas)  # nada a perguntar
    assert "Anexo XVII" in next(d for d in fora.dimensoes if d.chave == "imposto_seletivo").texto
    # Citado no anexo (ou sem como saber): vale o parecer.
    for citado in (True, None):
        av = avaliar(entrada(tese=t, correlacionados=[], is_no_anexo_xvii=citado))
        assert av.is_situacao == "indefinido"


def test_tipo_do_erp_em_texto_livre() -> None:
    from app.ingest.cleaning import tipo_do_erp

    assert tipo_do_erp("Produção interna") == "produto"
    assert tipo_do_erp("Revenda de bebida industrializada") == "produto"
    assert tipo_do_erp("Medicamento sob prescrição") == "produto"
    assert tipo_do_erp("S") == "servico" and tipo_do_erp("P") == "produto"
    assert tipo_do_erp("Prestação de serviço de entrega") == "servico"
    assert tipo_do_erp("Venda de alimentação preparada") is None  # restaurante: pode ser serviço
    assert tipo_do_erp("Múltiplos") is None and tipo_do_erp(None) is None
