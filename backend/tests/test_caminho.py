"""Caminho do item pelos agentes: as rotas precisam reproduzir as decisões do grafo."""

from __future__ import annotations

from app.analise.caminho import Registro, montar, rota


def _situacoes(r: Registro) -> dict[str, str]:
    return {p.caixa: p.situacao for p in montar(r)}


def _base(**kw: object) -> Registro:
    dados: dict[str, object] = {
        "descricao": "ACUCAR REFINADO 1KG",
        "status": "classificado",
        "descricao_normalizada": "acucar refinado 1 kg",
        "candidatos": [{"codigo": "17019900", "tipo_codigo": "ncm", "posicao": 1, "codigo_atual": True}],
        "julgamento": {"codigo_sugerido": "17019900", "confianca": 0.92},
        "tese": {"codigo": "1701.99.00", "hipoteses": [{"id": "H1", "titulo": "Cesta básica", "cclasstrib": "200003"}]},
        "cclasstrib": "200003",
    }
    dados.update(kw)
    return Registro(**dados)  # type: ignore[arg-type]


def test_caminho_simples_sem_segundo_parecer() -> None:
    r = _base()
    assert rota(r) == ["arrumador", "fiscal", "arquivista", "pesquisador", "identificador", "jurista", "leitor", "juiz"]
    s = _situacoes(r)
    assert s["segundo_parecer"] == "pulado"
    assert s["secretario"] == "pulado"
    passos = {p.caixa: p for p in montar(r)}
    assert passos["identificador"].proximo == "jurista"
    assert passos["juiz"].proximo == "resultado"


def test_alarme_leva_ao_segundo_parecer() -> None:
    r = _base(gatilhos=["codigo_atual_incoerente"], escalonamento={"codigo_sugerido": "17019900", "confianca": 0.9})
    assert "segundo_parecer" in rota(r)
    assert _situacoes(r)["segundo_parecer"] == "feito"


def test_memoria_pula_identificacao() -> None:
    r = _base(memoria={"codigo": "17019900", "tipo_codigo": "ncm"}, julgamento=None, candidatos=[])
    assert rota(r) == ["arrumador", "fiscal", "arquivista", "jurista", "leitor", "juiz"]
    s = _situacoes(r)
    assert s["pesquisador"] == s["identificador"] == "pulado"


def test_sem_candidatos_vai_ao_juiz() -> None:
    r = _base(candidatos=[], julgamento=None, tese=None, status="revisao_contador")
    assert rota(r)[-1] == "juiz"
    assert _situacoes(r)["identificador"] == "pulado"


def test_resposta_descartada_vai_ao_juiz() -> None:
    r = _base(
        julgamento={"codigo_sugerido": "99999999", "_descartado": "fora da lista"}, tese=None, status="revisao_contador"
    )
    assert rota(r)[-2:] == ["identificador", "juiz"]
    assert _situacoes(r)["identificador"] == "falhou"


def test_base_incompleta() -> None:
    r = _base(base_incompleta=True, julgamento=None, tese=None, status="revisao_contador")
    assert rota(r) == ["arrumador", "fiscal", "juiz"]
    assert _situacoes(r)["fiscal"] == "falhou"


def test_perguntas_passam_pelo_secretario() -> None:
    r = _base(status="aguardando_informacao", perguntas=[{"pergunta": "É fresca?", "grupo": "Hortifruti"}])
    assert rota(r)[-1] == "secretario"
    assert _situacoes(r)["secretario"] == "feito"


def test_em_andamento_marca_caixa_atual() -> None:
    r = _base(status="processando", caixa_atual="identificador", julgamento=None, tese=None)
    s = _situacoes(r)
    assert s["pesquisador"] == "feito"
    assert s["identificador"] == "atual"
    assert s["jurista"] == s["juiz"] == "aguardando"


def test_em_andamento_na_lei_depois_de_pular_o_segundo_parecer() -> None:
    r = _base(status="processando", caixa_atual="jurista", tese=None)
    s = _situacoes(r)
    assert s["segundo_parecer"] == "pulado"
    assert s["jurista"] == "atual"
    assert s["leitor"] == "aguardando"


def test_sem_ncm_passa_pelo_navegador_e_segue_para_o_jurista() -> None:
    arvore = {"codigo": "19059090", "codigo_formatado": "1905.90.90", "confianca": 0.8, "caminho": [], "passos": []}
    r = _base(
        julgamento={"codigo_sugerido": None, "confianca": 0.2},
        gatilhos=["sem_codigo_atual_valido"],
        escalonamento={"codigo_sugerido": None, "confianca": 0.15},
        arvore=arvore,
        status="revisao_contador",
    )
    assert rota(r) == [
        "arrumador",
        "fiscal",
        "arquivista",
        "pesquisador",
        "identificador",
        "segundo_parecer",
        "navegador",
        "jurista",
        "leitor",
        "juiz",
    ]
    assert _situacoes(r)["navegador"] == "feito"


def test_navegador_sem_resultado_vai_ao_juiz() -> None:
    r = _base(
        candidatos=[], julgamento=None, tese=None, arvore={"codigo": None, "passos": []}, status="revisao_contador"
    )
    assert rota(r)[-2:] == ["navegador", "juiz"]
    assert _situacoes(r)["navegador"] == "falhou"
