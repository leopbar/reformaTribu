"""Motor de regras: abrangência por prefixo, exceções, condições, pendências e Imposto Seletivo.

As regras abaixo são estruturas de TESTE (não dados legais): servem só para exercitar o motor.
"""

import uuid
from datetime import date

from app.pipeline.reasons import Motivo
from app.rules.engine import ConjuntoRegras, RegraMem, avaliar_condicoes, enquadrar

HOJE = date(2026, 9, 26)


def regra(
    slug: str,
    codigos: tuple[str, ...],
    cct: str | None = "200034",
    *,
    tratamento: str = "reducao_60",
    status: str = "aprovada",
    excecoes_codigo: tuple[str, ...] = (),
    excecoes_texto: tuple[str, ...] = (),
    condicoes: tuple[dict, ...] = (),
    tipo: str | None = "ncm",
    universal: bool = False,
    controverso: bool = False,
    vig_fim: date | None = None,
    prioridade: int = 100,
) -> RegraMem:
    return RegraMem(
        id=uuid.uuid4(),
        slug=slug,
        versao=1,
        status=status,
        anexo="VII",
        item="1",
        descricao_legal=slug,
        dispositivo_legal=f"LC 214/2025, teste {slug}",
        tipo_tratamento=tratamento,
        tipo_codigo=tipo,
        universal=universal,
        codigos=codigos,
        excecoes_codigo=excecoes_codigo,
        excecoes_texto=excecoes_texto,
        condicoes=condicoes,
        cst="200" if cct else None,
        cclasstrib=cct,
        vigencia_inicio=None,
        vigencia_fim=vig_fim,
        prioridade=prioridade,
        controverso=controverso,
        nota_controversia=None,
    )


PADRAO = regra("padrao", (), "000001", tratamento="tributacao_integral", tipo=None, universal=True, prioridade=1000)


def conjunto(*regras: RegraMem) -> ConjuntoRegras:
    aprov = [r for r in regras if r.status == "aprovada"]
    pend = [r for r in regras if r.status != "aprovada"]
    return ConjuntoRegras(aprovadas=[*aprov, PADRAO], pendentes=pend)


def atributos(**item):  # type: ignore[no-untyped-def]
    return {"item": item, "empresa": {"regime_tributario": "lucro_real"}, "operacao": {}}


def test_casa_por_prefixo_em_qualquer_nivel():
    c = conjunto(regra("crustaceos", ("03061",)))
    r = enquadrar(c, "ncm", "03061690", "camarão congelado", atributos(), HOJE)
    assert r.cclasstrib == "200034"
    assert r.certeza == 1.0 and not r.motivos


def test_excecao_por_codigo_leva_a_tributacao_integral():
    c = conjunto(regra("crustaceos", ("03061",), excecoes_codigo=("030611", "03061500")))
    r = enquadrar(c, "ncm", "03061190", "lagosta congelada", atributos(), HOJE)
    assert r.cclasstrib == "000001"
    assert any(x["resultado"] == "excecao_por_codigo" for x in r.consideradas)


def test_excecao_textual_possivel_vai_para_analise():
    c = conjunto(regra("crustaceos", ("03061",), excecoes_texto=("Lagostas e lagostim",)))
    r = enquadrar(c, "ncm", "03061690", "LAGOSTAS INTEIRAS CONGELADAS", atributos(), HOJE)
    assert Motivo.EXCECAO_LEGAL_POSSIVEL in r.motivos
    assert r.cclasstrib is None


def test_condicao_desconhecida_gera_pergunta_exata():
    cond = (
        {"atributo": "adicao_acucar", "fonte": "item", "deve_ser": "nao", "pergunta": "O suco tem adição de açúcar?"},
    )
    c = conjunto(regra("sucos", ("200961",), condicoes=cond))
    r = enquadrar(c, "ncm", "20096100", "SUCO UVA 1L", atributos(adicao_acucar="desconhecido"), HOJE)
    assert Motivo.CONDICAO_LEGAL_NAO_VERIFICAVEL in r.motivos
    assert [p.pergunta for p in r.perguntas] == ["O suco tem adição de açúcar?"]
    assert r.cclasstrib is None  # nunca cai silenciosamente na tributação integral


def test_condicao_atendida_e_nao_atendida():
    cond = ({"atributo": "adicao_acucar", "fonte": "item", "deve_ser": "nao", "pergunta": "?"},)
    c = conjunto(regra("sucos", ("200961",), condicoes=cond))
    assert enquadrar(c, "ncm", "20096100", "suco", atributos(adicao_acucar="nao"), HOJE).cclasstrib == "200034"
    r = enquadrar(c, "ncm", "20096100", "suco", atributos(adicao_acucar="sim"), HOJE)
    assert r.cclasstrib == "000001"


def test_condicao_da_empresa():
    cond = ({"atributo": "regime_tributario", "fonte": "empresa", "deve_ser": "simples_nacional", "pergunta": "?"},)
    c = conjunto(regra("so_simples", ("1905",), condicoes=cond))
    assert enquadrar(c, "ncm", "19059090", "pão", atributos(), HOJE).cclasstrib == "000001"


def test_regra_pendente_bloqueia_a_regra_padrao():
    c = conjunto(regra("nova", ("0401",), status="pendente_revisao"))
    r = enquadrar(c, "ncm", "04012010", "leite uht", atributos(), HOJE)
    assert Motivo.REGRA_PENDENTE_DE_REVISAO in r.motivos
    assert r.cclasstrib is None


def test_nova_versao_pendente_nao_bloqueia_versao_aprovada():
    aprovada = regra("leite", ("0401",), cct="200003")
    pendente = regra("leite", ("0401",), cct="200099", status="pendente_revisao")
    r = enquadrar(conjunto(aprovada, pendente), "ncm", "04012010", "leite", atributos(), HOJE)
    assert r.cclasstrib == "200003"


def test_multiplas_regras_com_cclasstrib_diferentes():
    c = conjunto(regra("a", ("9018",), cct="200005"), regra("b", ("901831",), cct="200030"))
    r = enquadrar(c, "ncm", "90183111", "seringa", atributos(), HOJE)
    assert Motivo.MULTIPLAS_REGRAS_APLICAVEIS in r.motivos
    assert r.cclasstrib is None


def test_imposto_seletivo_sinaliza_sem_definir_cclasstrib():
    c = conjunto(regra("is-bebidas", ("2203",), cct=None, tratamento="imposto_seletivo", prioridade=10))
    r = enquadrar(c, "ncm", "22030000", "cerveja", atributos(), HOJE)
    assert r.imposto_seletivo
    assert Motivo.SUJEITO_A_IMPOSTO_SELETIVO in r.motivos
    assert r.cclasstrib == "000001"  # IBS/CBS segue a regra padrão; o IS é sinalizado à parte


def test_fora_de_vigencia_nao_aplica():
    c = conjunto(regra("antiga", ("0401",), vig_fim=date(2025, 12, 31)))
    assert enquadrar(c, "ncm", "04012010", "leite", atributos(), HOJE).cclasstrib == "000001"


def test_caso_controverso():
    c = conjunto(regra("polêmica", ("2106",), controverso=True))
    r = enquadrar(c, "ncm", "21069090", "suplemento", atributos(), HOJE)
    assert Motivo.CASO_CONTROVERSO in r.motivos
    assert r.certeza < 1


def test_sem_regra_padrao_aprovada_base_incompleta():
    c = ConjuntoRegras(aprovadas=[], pendentes=[])
    r = enquadrar(c, "ncm", "84713012", "notebook", atributos(), HOJE)
    assert Motivo.BASE_REFERENCIA_INCOMPLETA in r.motivos


def test_avaliar_condicoes_normaliza_valores():
    r = regra("x", ("01",), condicoes=({"atributo": "a", "fonte": "item", "deve_ser": "sim", "pergunta": "?"},))
    assert avaliar_condicoes(r, {"item": {"a": True}})[0] == "ok"
    assert avaliar_condicoes(r, {"item": {"a": "Não"}})[0] == "falha"
    assert avaliar_condicoes(r, {"item": {}})[0] == "pendente"
