"""Métricas do harness de avaliação (sem chamar a API)."""

from pathlib import Path

from app.evals.runner import ItemOuro, Resultado, carregar_conjunto, metricas

EXEMPLO = Path(__file__).resolve().parents[2] / "evals" / "conjunto_ouro" / "exemplo_nao_validado.csv"


def ouro(codigo: str, cct: str | None = None) -> ItemOuro:
    return ItemOuro(
        id="x",
        descricao="x",
        ncm_informado=None,
        nbs_informado=None,
        tipo=None,
        esperado_tipo_codigo="ncm",
        esperado_codigo=codigo,
        esperado_cst=None,
        esperado_cclasstrib=cct,
        esperado_status=None,
        validado_por=None,
    )


def res(o: ItemOuro, status: str, codigo: str | None, cct: str | None = None) -> Resultado:
    return Resultado(
        ouro=o,
        status=status,
        codigo=codigo,
        cclasstrib=cct,
        confianca="alta",
        escalonado=False,
        custo=0.01,
        segundos=1.0,
    )


def test_falso_classificado_e_a_metrica_principal():
    rs = [
        res(ouro("34011190", "200035"), "classificado", "34011190", "200035"),
        res(ouro("34013000"), "classificado", "34011190"),  # falso classificado
        res(ouro("20096100"), "aguardando_informacao", "20096100"),
        res(ouro("19053100"), "revisao_contador", "19059020"),  # errado, mas foi para revisão
    ]
    m = metricas(rs)
    assert m["taxa_falsos_classificados"] == 0.25
    assert m["falsos_entre_classificados"] == 0.5
    assert m["taxa_classificados"] == 0.5
    assert m["taxa_aguardando_informacao"] == 0.25
    assert m["taxa_revisao"] == 0.25
    assert m["acerto_ncm_4_digitos"] == 1.0
    assert m["acerto_ncm_8_digitos"] == 0.5


def test_exemplo_marcado_como_nao_validado():
    if not EXEMPLO.exists():
        EXEMPLO_ALT = Path("/evals/conjunto_ouro/exemplo_nao_validado.csv")
        itens, validado = carregar_conjunto(EXEMPLO_ALT)
    else:
        itens, validado = carregar_conjunto(EXEMPLO)
    assert not validado
    assert itens[2].ncm_informado == "4012010" and itens[2].esperado_codigo == "04012010"
