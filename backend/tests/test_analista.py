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
    sujeito = avaliar(entrada({"adicao_acucar": fato("sim")}, tese=t, correlacionados=[]))
    assert sujeito.is_situacao == "sujeito"
    assert sujeito.status == "revisao_contador"  # a organização exige conferência do IS
    livre = avaliar(entrada({"adicao_acucar": fato("sim")}, tese=t, correlacionados=[], is_exige_analise=False))
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
