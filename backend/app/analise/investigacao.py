"""Investigação jurídica por família: chave da tese, conteúdo enviado ao modelo e validação da resposta.

A investigação é feita uma vez por família (mesmo código + cenário + dossiê + data + base) e
reaproveitada por todos os itens dela, inclusive em auditorias seguintes da mesma empresa.
"""

from __future__ import annotations

import hashlib
from datetime import date
from typing import Any

import orjson

from app.analise.evidencias import CCLASSTRIB_REGRA_GERAL, Evidencias
from app.analise.fatos import chave

CENARIOS = {"venda_consumidor": "Venda comum de mercadoria ou serviço ao consumidor final (NFC-e/NF-e/NFS-e)."}


def chave_familia(
    *,
    company_id: str,
    tipo_codigo: str,
    codigo: str,
    cenario: str,
    data_referencia: date,
    snapshot_id: str,
    dossie: dict[str, str],
    prompt: str,
) -> str:
    bruto = orjson.dumps(
        {
            "e": company_id,
            "t": tipo_codigo,
            "c": codigo,
            "s": cenario,
            "d": data_referencia.isoformat(),
            "b": snapshot_id,
            "f": dossie,
            "p": prompt,
        },
        option=orjson.OPT_SORT_KEYS,
    )
    return hashlib.sha256(bruto).hexdigest()


def conteudo(ev: Evidencias, dossie: dict[str, str], cenario: str) -> dict[str, Any]:
    return {
        **ev.pacote,
        "empresa": dossie,
        "cenario": {"codigo": cenario, "descricao": CENARIOS.get(cenario, cenario)},
    }


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
    return {**dados, "hipoteses": hipoteses}, rel


def fatos_item_necessarios(resultado: dict[str, Any]) -> list[dict[str, Any]]:
    return [f for f in resultado.get("fatos_necessarios", []) if f.get("escopo") == "item"]
