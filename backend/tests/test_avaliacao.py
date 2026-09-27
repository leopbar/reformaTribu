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
        ouro=o, status=status, codigo=codigo, cclasstrib=cct, confianca=0.95, escalonado=False, custo=0.01, segundos=1.0
    )


def test_falso_confirmado_e_a_metrica_principal():
    rs = [
        res(ouro("34011190", "200035"), "confirmado", "34011190", "200035"),
        res(ouro("34013000"), "confirmado", "34011190"),  # falso confirmado
        res(ouro("20096100"), "analise_humana", "20096100"),
        res(ouro("19053100"), "corrigido", "19059020"),  # falso corrigido (acerta a posição 1905)
    ]
    m = metricas(rs)
    assert m["taxa_falsos_confirmados"] == 0.25
    assert m["falsos_confirmados_entre_confirmados"] == 0.5
    assert m["taxa_falsos_corrigidos"] == 0.25
    assert m["acerto_ncm_4_digitos"] == 1.0
    assert m["acerto_ncm_8_digitos"] == 0.5
    assert m["taxa_analise_humana"] == 0.25


def test_exemplo_marcado_como_nao_validado():
    if not EXEMPLO.exists():
        EXEMPLO_ALT = Path("/evals/conjunto_ouro/exemplo_nao_validado.csv")
        itens, validado = carregar_conjunto(EXEMPLO_ALT)
    else:
        itens, validado = carregar_conjunto(EXEMPLO)
    assert not validado
    assert itens[2].ncm_informado == "4012010" and itens[2].esperado_codigo == "04012010"
