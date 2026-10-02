"""Memória de decisões (ADR 0028): 1 decisão vira nota, 2 dispensam avisos leves, 3 confirmam.

Funções puras: nada de banco nem de IA. Os códigos são FIXTURES de teste, não a base legal.
"""

from __future__ import annotations

from typing import Any

from test_analista import entrada, fato

from app.analise.avaliacao import avaliar
from app.analise.decisoes import chave_fatos, consolidar, resultado

SEM_ACUCAR = {"adicao_acucar": fato("nao")}
CHAVE = "adicao_acucar=nao"


def decisao(
    auditoria: str, cct: str = "200034", *, peso: int = 1, fatos: str = CHAVE, empresa: str = "e1"
) -> dict[str, Any]:
    return {
        "audit_id": auditoria,
        "company_id": empresa,
        "resultado": resultado(cct, "nao_sujeito"),
        "cclasstrib": cct,
        "fatos_chave": fatos,
        "peso": peso,
        "origem": "correcao" if peso > 1 else "aprovacao",
    }


def dims(av: Any) -> dict[str, Any]:
    return {d.chave: d for d in av.dimensoes}


# ------------------------------------------------------------------------------ contagem --
def test_chave_dos_fatos_ignora_ordem_e_caixa():
    a = chave_fatos([{"atributo": "B", "valor": "Sim"}, {"atributo": "a", "valor": "nao"}])
    assert a == chave_fatos([{"atributo": "a", "valor": "NAO"}, {"atributo": "b", "valor": "sim"}]) == "a=nao;b=sim"


def test_cada_auditoria_conta_uma_vez_e_correcao_pesa_dois():
    alvo = resultado("200034", "nao_sujeito")
    c = consolidar([decisao("a1"), decisao("a1"), decisao("a1", empresa="e2")], alvo, CHAVE)
    assert c.a_favor == 1  # três itens da mesma planilha: uma ocasião só
    c = consolidar([decisao("a1"), decisao("a2", peso=2)], alvo, CHAVE)
    assert c.a_favor == 3 and c.correcoes == 1


def test_decisao_tomada_com_outros_fatos_nao_vale():
    c = consolidar([decisao("a1", fatos="adicao_acucar=sim")], resultado("200034", "nao_sujeito"), CHAVE)
    assert c.vazio


# ------------------------------------------------------------------------------ efeito --
def test_uma_decisao_igual_vira_nota_sem_mudar_o_resultado():
    av = avaliar(entrada(SEM_ACUCAR, decisoes=[decisao("a1")]))
    assert av.status == "classificado"
    assert "decidido igual por pessoas 1 vez" in dims(av)["fonte"].texto


def test_aviso_leve_dispensado_com_duas_decisoes():
    # Correlação oficial que o Jurista não analisou: aviso leve (revisão do contador).
    base = {"correlacionados": ["200034", "200099"]}
    assert avaliar(entrada(SEM_ACUCAR, **base)).status == "revisao_contador"
    uma = avaliar(entrada(SEM_ACUCAR, decisoes=[decisao("a1")], **base))
    assert uma.status == "revisao_contador"
    duas = avaliar(entrada(SEM_ACUCAR, decisoes=[decisao("a1"), decisao("a2")], **base))
    assert duas.status == "classificado"
    assert "Aviso dispensado por 2 decisões" in dims(duas)["conflito"].texto


def test_tres_decisoes_resolvem_a_divergencia_entre_lei_e_tabela():
    alerta = {"descricao": "a tabela oficial exclui o código", "gravidade": "alta", "cclasstrib": "200034"}
    base = {"alertas": [alerta]}
    duas = avaliar(entrada(SEM_ACUCAR, decisoes=[decisao("a1"), decisao("a2")], **base))
    assert duas.status == "revisao_especialista"
    tres = avaliar(entrada(SEM_ACUCAR, decisoes=[decisao("a1"), decisao("a2"), decisao("a3")], **base))
    assert tres.status == "classificado" and tres.confianca_global == "alta"
    assert "CONFLITO_NORMATIVO" not in tres.motivos
    assert "Resolvido por 3 decisões" in dims(tres)["conflito"].texto
    assert "confirmado pelo uso" in dims(tres)["fonte"].texto
    # Uma correção (peso 2) e uma aprovação também confirmam.
    mista = avaliar(entrada(SEM_ACUCAR, decisoes=[decisao("a1", peso=2), decisao("a2")], **base))
    assert mista.status == "classificado"


def test_decisao_diferente_manda_para_revisao():
    uma = avaliar(entrada(SEM_ACUCAR, decisoes=[decisao("a1", "000001")]))
    assert uma.status == "revisao_contador"
    assert "DECISAO_ANTERIOR_DIVERGENTE" in uma.motivos
    assert "Pessoas já decidiram 000001" in dims(uma)["conflito"].texto
    tres = avaliar(entrada(SEM_ACUCAR, decisoes=[decisao(f"a{n}", "000001") for n in range(3)]))
    assert tres.status == "revisao_especialista"


def test_decisoes_que_divergem_entre_si_nao_reforcam():
    av = avaliar(entrada(SEM_ACUCAR, decisoes=[decisao("a1"), decisao("a2"), decisao("a3", "000001")]))
    assert av.status == "revisao_contador"
    assert "Decisões anteriores divergem" in dims(av)["conflito"].texto


def test_sem_conclusao_a_memoria_nao_entra():
    # Falta o fato decisivo: a pergunta continua, nenhuma decisão anterior responde por ela.
    av = avaliar(entrada({}, decisoes=[decisao(f"a{n}") for n in range(3)]))
    assert av.status == "aguardando_informacao"
