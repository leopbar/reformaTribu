"""Decisão de status: o objetivo principal é nunca produzir um "falso confirmado"."""

from app.pipeline.decision import EntradaDecisao, decidir
from app.pipeline.reasons import Motivo

ENQ_OK = {"cst": "200", "cclasstrib": "200035", "perguntas": [], "motivos": [], "certeza": 1.0}


def julg(codigo="34011190", conf=0.97, coerente=True, **extra):  # type: ignore[no-untyped-def]
    return {
        "codigo_sugerido": codigo,
        "confianca": conf,
        "ncm_atual_coerente": coerente,
        "descricao_suficiente": True,
        "nenhum_candidato_serve": False,
        **extra,
    }


def entrada(**kw):  # type: ignore[no-untyped-def]
    base = dict(
        motivos=[],
        codigo_atual="34011190",
        codigo_atual_valido=True,
        codigo_final="34011190",
        memoria=False,
        julgamento=julg(),
        julgamento_valido=True,
        escalonado=False,
        escalonamento=None,
        escalonamento_valido=False,
        posicao_busca=1,
        enquadramento=ENQ_OK,
        cst_atual=None,
        cclasstrib_atual=None,
        descricao_curta=False,
        busca_semantica=True,
        limiar_confirmado=0.9,
        limiar_corrigido=0.85,
        is_exige_analise=True,
    )
    base.update(kw)
    return EntradaDecisao(**base)


def test_confirmado_quando_tudo_concorda():
    d = decidir(entrada())
    assert d.status == "confirmado"
    assert d.confianca >= 0.9


def test_confianca_nao_e_copia_do_modelo():
    d = decidir(entrada(posicao_busca=12, busca_semantica=False))
    assert d.confianca < 0.97


def test_baixa_confianca_vai_para_analise():
    d = decidir(entrada(julgamento=julg(conf=0.6)))
    assert d.status == "analise_humana"
    assert Motivo.BAIXA_CONFIANCA in d.motivos


def test_codigo_coerente_mas_modelo_nao_afirma_coerencia_nao_confirma():
    d = decidir(entrada(julgamento=julg(coerente=None)))
    assert d.status != "confirmado"


def test_correcao_exige_escalonamento_concordante():
    sem_esc = decidir(entrada(codigo_final="34013000", julgamento=julg("34013000", coerente=False)))
    assert sem_esc.status == "analise_humana"
    com_esc = decidir(
        entrada(
            codigo_final="34013000",
            julgamento=julg("34013000", coerente=False),
            escalonado=True,
            escalonamento=julg("34013000", conf=0.96, coerente=False),
            escalonamento_valido=True,
        )
    )
    assert com_esc.status == "corrigido"
    assert Motivo.NCM_INCOERENTE_COM_DESCRICAO in com_esc.motivos


def test_divergencia_entre_modelos_zera_confianca():
    d = decidir(
        entrada(
            codigo_final="34013000",
            julgamento=julg("34011190", coerente=True),
            escalonado=True,
            escalonamento=julg("34013000", conf=0.95, coerente=False),
            escalonamento_valido=True,
        )
    )
    assert d.status == "analise_humana"
    assert Motivo.DIVERGENCIA_ENTRE_MODELOS in d.motivos
    assert d.confianca == 0.0


def test_pergunta_pendente_nunca_confirma():
    enq = {
        **ENQ_OK,
        "cclasstrib": None,
        "perguntas": [{"pergunta": "?"}],
        "motivos": ["CONDICAO_LEGAL_NAO_VERIFICAVEL"],
    }
    d = decidir(entrada(enquadramento=enq))
    assert d.status == "analise_humana"


def test_imposto_seletivo_respeita_configuracao():
    enq = {**ENQ_OK, "motivos": [Motivo.SUJEITO_A_IMPOSTO_SELETIVO]}
    assert decidir(entrada(enquadramento=enq)).status == "analise_humana"
    assert decidir(entrada(enquadramento=enq, is_exige_analise=False)).status == "confirmado"


def test_cst_atual_divergente_vira_correcao_do_enquadramento():
    d = decidir(
        entrada(cclasstrib_atual="000001", escalonado=True, escalonamento=julg(conf=0.96), escalonamento_valido=True)
    )
    assert Motivo.CST_CCLASSTRIB_ATUAL_DIVERGENTE in d.motivos
    assert d.status == "corrigido"


def test_sem_codigo_final_sempre_analise():
    d = decidir(entrada(codigo_final=None, julgamento=julg(None, conf=0.2, nenhum_candidato_serve=True)))
    assert d.status == "analise_humana"
    assert Motivo.NENHUM_CANDIDATO_ADEQUADO in d.motivos


def test_memoria_aprovada_confirma_sem_ia():
    d = decidir(entrada(memoria=True, julgamento=None, julgamento_valido=False, posicao_busca=None))
    assert d.status == "confirmado"


def test_descricao_insuficiente_bloqueia():
    d = decidir(entrada(julgamento=julg(descricao_suficiente=False)))
    assert d.status == "analise_humana"
    assert Motivo.DESCRICAO_INSUFICIENTE in d.motivos
