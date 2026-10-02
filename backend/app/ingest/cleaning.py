"""Limpeza e validação dos itens antes de qualquer chamada de IA."""

from __future__ import annotations

import hashlib
import re
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.codes import (
    gtin_valido,
    normalizar_cclasstrib,
    normalizar_cst,
    normalizar_nbs,
    normalizar_ncm,
    somente_digitos,
)

# Problemas de dados (prévia). Severidade: "erro" impede o processamento da linha; "aviso" não.
PROBLEMAS = {
    "LINHA_VAZIA": ("aviso", "Linha sem descrição; será ignorada."),
    "DESCRICAO_CURTA": ("aviso", "Descrição muito curta; a análise pode ficar inconclusiva."),
    "CODIGO_INTERNO_GERADO": ("aviso", "Sem código interno; o sistema gerou um a partir da linha."),
    "DUPLICADO": ("aviso", "Outra linha tem o mesmo código interno."),
    "DESCRICAO_DUPLICADA": ("aviso", "Outra linha tem a mesma descrição e o mesmo NCM."),
    "GTIN_INVALIDO": ("aviso", "O GTIN/EAN tem dígito verificador inválido."),
    "NCM_INVALIDO": ("aviso", "O NCM informado não é um código válido."),
    "NCM_ZERO_A_ESQUERDA_SUSPEITO": ("aviso", "NCM com 7 dígitos: provável zero à esquerda perdido."),
    "NCM_NIVEL_INCOMPLETO": ("aviso", "NCM sem os 8 dígitos."),
    "NCM_INEXISTENTE": ("aviso", "O NCM não existe na tabela oficial vigente."),
    "NCM_NAO_VIGENTE": ("aviso", "O NCM não está vigente na data de referência."),
    "NCM_NAO_FOLHA": ("aviso", "O NCM existe, mas não é um código completo (folha)."),
    "NBS_NIVEL_INCOMPLETO": ("aviso", "NBS sem os 9 dígitos."),
    "NBS_INEXISTENTE": ("aviso", "A NBS não existe na tabela oficial vigente."),
    "SEM_CODIGO": ("aviso", "Item sem NCM nem NBS; o sistema vai sugerir um."),
    "CST_INVALIDO": ("aviso", "CST do IBS/CBS informado não existe na tabela oficial."),
    "CCLASSTRIB_INVALIDO": ("aviso", "cClassTrib informado não existe na tabela oficial."),
}

_TIPOS = {
    "p": "produto",
    "produto": "produto",
    "prod": "produto",
    "mercadoria": "produto",
    "bem": "produto",
    "m": "produto",
    "s": "servico",
    "servico": "servico",
    "serv": "servico",
    "sv": "servico",
}


def _norm(t: str) -> str:
    return unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower().strip()


# Palavras do campo "tipo" do ERP em texto livre (ADR 0029): "Produção interna", "Revenda de bebida…",
# "Medicamento sob prescrição" dizem que o item é mercadoria; "Prestação de serviço", que é serviço.
_TIPO_SERVICO = ("servic", "prestacao", "mao de obra")
_TIPO_PRODUTO = (
    "produ",  # produto, produção, produtor
    "revenda",
    "mercadoria",
    "medicamento",
    "cosmetic",
    "higiene",
    "industri",
    "fabrica",
    "frigorific",
    "distribuidor",
    "importador",
)


def tipo_do_erp(tipo_bruto: str | None) -> str | None:
    """'produto', 'servico' ou None (não dá para saber) a partir do campo "tipo" do ERP."""
    if not tipo_bruto:
        return None
    t = _norm(tipo_bruto)
    curto = _TIPOS.get(t[:12].split(" ")[0])
    if curto:
        return curto
    if any(p in t for p in _TIPO_SERVICO):
        return "servico"
    if any(p in t for p in _TIPO_PRODUTO):
        return "produto"
    return None


def hash_descricao(descricao_normalizada: str) -> str:
    base = re.sub(r"\s+", " ", _norm(descricao_normalizada))
    return hashlib.sha256(base.encode()).hexdigest()


def problema(codigo: str, detalhe: str | None = None) -> dict[str, str]:
    sev, msg = PROBLEMAS[codigo]
    return {"codigo": codigo, "severidade": sev, "mensagem": detalhe or msg}


@dataclass
class ItemLimpo:
    linha: int
    codigo_interno: str
    codigo_interno_gerado: bool
    descricao: str
    ncm_informado: str | None
    nbs_informado: str | None
    tipo_informado: str | None
    gtin: str | None
    cest: str | None
    unidade: str | None
    marca: str | None
    categoria: str | None
    cst_atual: str | None
    cclasstrib_atual: str | None
    ncm: str | None
    nbs: str | None
    tipo: str | None
    problemas: list[dict[str, str]] = field(default_factory=list)
    duplicado_de: int | None = None
    ignorado: bool = False
    ncm_candidato_zero: str | None = None

    def como_linha_bd(self) -> dict[str, Any]:
        d = {k: v for k, v in self.__dict__.items() if k != "ncm_candidato_zero"}
        d["estrutura"] = {"ncm_candidato_zero": self.ncm_candidato_zero} if self.ncm_candidato_zero else {}
        return d


def _val(registro: dict[str, str], mapeamento: dict[str, str | None], campo: str, limite: int) -> str | None:
    col = mapeamento.get(campo)
    if not col:
        return None
    v = (registro.get(col) or "").strip()
    return v[:limite] or None


def limpar(
    registros: list[dict[str, str]], mapeamento: dict[str, str | None], linha_inicial: int = 2
) -> list[ItemLimpo]:
    itens: list[ItemLimpo] = []
    por_codigo: dict[str, int] = {}
    por_desc: dict[tuple[str, str | None], int] = {}
    for i, reg in enumerate(registros):
        linha = linha_inicial + i
        descricao = _val(reg, mapeamento, "descricao", 2000) or ""
        cod = _val(reg, mapeamento, "codigo_interno", 80)
        gerado = cod is None
        codigo_interno = cod or f"L{linha}"
        ncm_bruto = _val(reg, mapeamento, "ncm", 40)
        nbs_bruto = _val(reg, mapeamento, "nbs", 40)
        tipo_bruto = _val(reg, mapeamento, "tipo", 40)
        gtin_bruto = _val(reg, mapeamento, "gtin", 20)
        item = ItemLimpo(
            linha=linha,
            codigo_interno=codigo_interno,
            codigo_interno_gerado=gerado,
            descricao=descricao,
            ncm_informado=ncm_bruto,
            nbs_informado=nbs_bruto,
            tipo_informado=tipo_bruto,
            gtin=somente_digitos(gtin_bruto) or None if gtin_bruto else None,
            cest=somente_digitos(_val(reg, mapeamento, "cest", 20)) or None,
            unidade=_val(reg, mapeamento, "unidade", 20),
            marca=_val(reg, mapeamento, "marca", 120),
            categoria=_val(reg, mapeamento, "categoria", 200),
            cst_atual=normalizar_cst(_val(reg, mapeamento, "cst_atual", 10)),
            cclasstrib_atual=normalizar_cclasstrib(_val(reg, mapeamento, "cclasstrib_atual", 10)),
            ncm=None,
            nbs=None,
            tipo=tipo_do_erp(tipo_bruto),
        )
        if not descricao:
            if not any((v or "").strip() for v in reg.values()):
                continue  # linha totalmente vazia: descartada sem registro
            item.ignorado = True
            item.problemas.append(problema("LINHA_VAZIA"))
            itens.append(item)
            continue
        if len(re.sub(r"[^A-Za-zÀ-ú]", "", descricao)) < 4:
            item.problemas.append(problema("DESCRICAO_CURTA"))
        if gerado:
            item.problemas.append(problema("CODIGO_INTERNO_GERADO"))
        if ncm_bruto:
            n = normalizar_ncm(ncm_bruto)
            item.ncm = n.codigo if n.codigo and len(n.codigo) <= 8 else None
            item.ncm_candidato_zero = n.candidato_zero_esquerda
            for p in n.problemas:
                item.problemas.append(problema(p["codigo"], p["mensagem"]))
        if nbs_bruto:
            nbs, probs = normalizar_nbs(nbs_bruto)
            item.nbs = nbs if nbs and len(nbs) <= 9 else None
            for p in probs:
                item.problemas.append(problema(p["codigo"], p["mensagem"]))
        if not item.ncm and not item.nbs:
            item.problemas.append(problema("SEM_CODIGO"))
        if item.tipo is None:
            item.tipo = "servico" if item.nbs and not item.ncm else ("produto" if item.ncm else None)
        if item.gtin and not gtin_valido(item.gtin):
            item.problemas.append(problema("GTIN_INVALIDO", f"GTIN {item.gtin} com dígito verificador inválido."))
        if not gerado:
            if codigo_interno in por_codigo:
                item.duplicado_de = por_codigo[codigo_interno]
                item.problemas.append(
                    problema("DUPLICADO", f"Mesmo código interno da linha {por_codigo[codigo_interno]}.")
                )
            else:
                por_codigo[codigo_interno] = linha
        chave = (hash_descricao(descricao), item.ncm)
        if chave in por_desc and item.duplicado_de is None:
            item.problemas.append(problema("DESCRICAO_DUPLICADA", f"Mesma descrição e NCM da linha {por_desc[chave]}."))
        else:
            por_desc.setdefault(chave, linha)
        itens.append(item)
    return itens


def checar_codigos(
    session: Session, tipo: str, codigos: set[str], version_id: uuid.UUID, data_referencia: date
) -> dict[str, dict[str, Any]]:
    """Consulta em lote a existência, o nível e a vigência de códigos na tabela oficial."""
    if not codigos:
        return {}
    tabela = "nbs_nodes" if tipo == "nbs" else "ncm_nodes"
    rows = session.execute(
        text(
            f"SELECT codigo, folha, data_inicio, data_fim, descricao_completa FROM {tabela} "
            "WHERE version_id = :v AND codigo = ANY(:c)"
        ),
        {"v": version_id, "c": list(codigos)},
    ).all()
    saida: dict[str, dict[str, Any]] = {}
    for r in rows:
        vigente = (r.data_inicio is None or r.data_inicio <= data_referencia) and (
            r.data_fim is None or r.data_fim >= data_referencia
        )
        saida[r.codigo] = {
            "existe": True,
            "folha": r.folha,
            "vigente": vigente,
            "descricao_completa": r.descricao_completa,
        }
    for c in codigos - set(saida):
        saida[c] = {"existe": False, "folha": False, "vigente": False, "descricao_completa": None}
    return saida


def aplicar_checagem_estrutural(
    itens: list[ItemLimpo], ncm_info: dict[str, dict[str, Any]], nbs_info: dict[str, dict[str, Any]]
) -> None:
    for it in itens:
        if it.ignorado:
            continue
        codigos_problema = {p["codigo"] for p in it.problemas}
        if it.ncm and len(it.ncm) == 8:
            info = ncm_info.get(it.ncm)
            if info and not info["existe"]:
                it.problemas.append(problema("NCM_INEXISTENTE", f"NCM {it.ncm} não existe na tabela vigente."))
            elif info and not info["vigente"]:
                it.problemas.append(problema("NCM_NAO_VIGENTE"))
            elif info and not info["folha"]:
                it.problemas.append(problema("NCM_NAO_FOLHA"))
        elif it.ncm_candidato_zero and "NCM_ZERO_A_ESQUERDA_SUSPEITO" in codigos_problema:
            info = ncm_info.get(it.ncm_candidato_zero)
            if info and not info["existe"]:
                it.problemas.append(
                    problema("NCM_INEXISTENTE", f"Nem {it.ncm} nem {it.ncm_candidato_zero} existem na tabela vigente.")
                )
        if it.nbs and len(it.nbs) == 9:
            info = nbs_info.get(it.nbs)
            if info and not info["existe"]:
                it.problemas.append(problema("NBS_INEXISTENTE"))


def resumir_problemas(itens: list[ItemLimpo]) -> dict[str, Any]:
    contagem: dict[str, int] = {}
    for it in itens:
        for p in it.problemas:
            contagem[p["codigo"]] = contagem.get(p["codigo"], 0) + 1
    return {
        "total_linhas": len(itens),
        "itens_validos": sum(1 for i in itens if not i.ignorado),
        "ignorados": sum(1 for i in itens if i.ignorado),
        "com_problemas": sum(1 for i in itens if i.problemas),
        "por_problema": dict(sorted(contagem.items(), key=lambda kv: -kv[1])),
        "descricoes": {k: v[1] for k, v in PROBLEMAS.items()},
    }
