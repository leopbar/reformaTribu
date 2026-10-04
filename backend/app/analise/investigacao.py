"""Investigação jurídica por família: chave da tese, conteúdo enviado ao modelo e validação da resposta.

A investigação é feita uma vez por família (mesmo código + cenário + dossiê + data + material jurídico)
e reaproveitada por todos os itens dela, inclusive em auditorias seguintes da organização. A chave usa
o CONTEÚDO do material que o Jurista lê, não a versão da base: uma nova coleta das tabelas oficiais com
o mesmo texto para o código não refaz a tese; uma mudança real na lei ou na tabela desse código refaz.
"""

from __future__ import annotations

import hashlib
from datetime import date
from typing import Any

import orjson

from app.analise import fatos_padrao
from app.analise.evidencias import CCLASSTRIB_REGRA_GERAL, Evidencias
from app.analise.fatos import chave
from app.analise.operacao import regimes_da_empresa

CENARIOS = {"venda_consumidor": "Venda comum de mercadoria ou serviço ao consumidor final (NFC-e/NF-e/NFS-e)."}


# Campos dos alertas que o Jurista lê (outros campos só servem ao filtro da avaliação).
_CAMPOS_ALERTA = ("regra", "descricao", "gravidade", "cclasstrib")


def impressao_evidencias(pacote: dict[str, Any]) -> str:
    """Impressão digital do material jurídico da família (o que vai ao modelo, sem metadados)."""
    p = dict(pacote)
    p["alertas_de_divergencia"] = [
        {k: a.get(k) for k in _CAMPOS_ALERTA} for a in pacote.get("alertas_de_divergencia") or []
    ]
    return hashlib.sha256(orjson.dumps(p, option=orjson.OPT_SORT_KEYS)).hexdigest()


def chave_familia(
    *,
    company_id: str,
    tipo_codigo: str,
    codigo: str,
    cenario: str,
    data_referencia: date,
    evidencias: str,
    dossie: dict[str, str],
) -> str:
    """A versão do prompt não entra na chave: melhorar as instruções não refaz pareceres já guardados
    (para refazer, use "Refazer com o modelo atual")."""
    bruto = orjson.dumps(
        {
            "e": company_id,
            "t": tipo_codigo,
            "c": codigo,
            "s": cenario,
            "d": data_referencia.isoformat(),
            "m": evidencias,
            "f": dossie,
        },
        option=orjson.OPT_SORT_KEYS,
    )
    return hashlib.sha256(bruto).hexdigest()


def conteudo(ev: Evidencias, dossie: dict[str, str], cenario: str) -> dict[str, Any]:
    saida = {
        **ev.pacote,
        "empresa": dossie,
        "cenario": {"codigo": cenario, "descricao": CENARIOS.get(cenario, cenario)},
    }
    # Fatos padronizados (ADR 0030): fora da chave da tese, é instrução sobre como nomear as condições.
    saida["fatos_padronizados"] = fatos_padrao.para_o_jurista()
    regimes = regimes_da_empresa(dossie).regimes
    if regimes:
        # Fora da chave da tese: é instrução, não material jurídico.
        saida["regimes_da_operacao_tratados_a_parte"] = [
            f"{r.titulo} (cClassTrib {r.cclasstrib}): decidido por outra etapa, item a item, conforme o preparo "
            "e a natureza do item. Estude aqui só o tratamento do PRODUTO vendido como mercadoria; não crie "
            "hipóteses nem perguntas sobre este regime."
            for r in regimes
        ]
    return saida


def validar(dados: dict[str, Any], ev: Evidencias) -> tuple[dict[str, Any], dict[str, Any]]:
    """Confere a resposta contra o pacote: cClassTrib só da lista, citações só de referências existentes.

    Devolve (resultado saneado, relatório de validação).
    """
    rel: dict[str, Any] = {"hipoteses_descartadas": [], "referencias_invalidas": [], "regra_geral_incluida": False}
    hipoteses = []
    vistos: set[str] = set()
    for h in dados.get("hipoteses", []):
        if h["cclasstrib"] not in ev.cclasstrib:
            rel["hipoteses_descartadas"].append(
                {"id": h["id"], "cclasstrib": h["cclasstrib"], "motivo": "cClassTrib fora da lista oficial candidata"}
            )
            continue
        hid = h["id"] if h["id"] not in vistos else f"{h['id']}_{len(vistos)}"
        vistos.add(hid)
        for c in h.get("condicoes", []):
            c["fato"] = chave(c["fato"])
        for e in h.get("excecoes", []):
            if e.get("fato"):
                e["fato"] = chave(e["fato"])
        invalidas = [f["ref"] for f in h.get("fundamentos", []) if f["ref"] not in ev.refs]
        if invalidas:
            rel["referencias_invalidas"].append({"hipotese": hid, "refs": invalidas})
        hipoteses.append({**h, "id": hid})
    # A última hipótese precisa ser a regra geral, sem condições (garante que sempre há um destino).
    if not hipoteses or hipoteses[-1]["condicoes"] or hipoteses[-1]["tipo"] != "regra_geral":
        geral = ev.cclasstrib.get(CCLASSTRIB_REGRA_GERAL)
        if geral is not None and not any(
            h["cclasstrib"] == CCLASSTRIB_REGRA_GERAL and not h["condicoes"] for h in hipoteses
        ):
            hipoteses.append(
                {
                    "id": "HG",
                    "titulo": "Tributação integral (regra geral)",
                    "tipo": "regra_geral",
                    "cclasstrib": CCLASSTRIB_REGRA_GERAL,
                    "condicoes": [],
                    "excecoes": [],
                    "fundamentos": [{"ref": f"T{CCLASSTRIB_REGRA_GERAL}", "trecho": geral.get("nome", "")}],
                    "explicacao": "Aplicável quando nenhuma hipótese específica se sustenta.",
                }
            )
            rel["regra_geral_incluida"] = True
    for f in dados.get("fatos_necessarios", []):
        f["fato"] = chave(f["fato"])
    for c in dados.get("imposto_seletivo", {}).get("condicoes", []):
        c["fato"] = chave(c["fato"])
    for c in dados.get("conflitos", []):
        if c.get("fato_que_decide"):
            c["fato_que_decide"] = chave(c["fato_que_decide"])
    return {**dados, "hipoteses": hipoteses}, rel


def fatos_item_necessarios(resultado: dict[str, Any]) -> list[dict[str, Any]]:
    return [f for f in resultado.get("fatos_necessarios", []) if f.get("escopo") == "item"]
