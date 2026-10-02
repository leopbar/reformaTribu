"""Resumo das regras legais pelo uso (ADR 0028): o que as decisões de pessoas já confirmaram e quais
divergências entre lei e tabela oficial ainda tocam itens da organização.

Nada aqui muda o status de uma regra. "Confirmada pelo uso" é calculado a partir da memória de decisões
(`decision_memory`, isolada por organização) a cada consulta.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.analise.decisoes import CONFIRMA
from app.analise.evidencias import prefixos
from app.core.codes import formatar_codigo
from app.models import DecisionMemory, LegalRule
from app.models.enums import StatusRegra
from app.rules.divergencias import exige_justificativa


@dataclass
class _Grupo:
    """Decisões de um código num ramo e com os mesmos fatos: peso por cClassTrib (uma vez por auditoria)."""

    por_auditoria: dict[tuple[str, str], int] = field(default_factory=dict)
    ramo: str | None = None
    dispositivos: set[str] = field(default_factory=set)

    def totais(self) -> dict[str, int]:
        t: dict[str, int] = defaultdict(int)
        for (_, cct), peso in self.por_auditoria.items():
            t[cct] += peso
        return dict(t)


def _grupos(session: Session) -> dict[tuple[str, str], list[_Grupo]]:
    grupos: dict[tuple[str, str, str | None, str], _Grupo] = {}
    for d in session.scalars(select(DecisionMemory).where(DecisionMemory.ativo.is_(True))):
        g = grupos.setdefault((d.tipo_codigo, d.codigo, d.segmento, d.fatos_chave), _Grupo(ramo=d.segmento))
        k = (str(d.audit_id), d.cclasstrib)
        g.por_auditoria[k] = max(g.por_auditoria.get(k, 0), d.peso)
        if d.dispositivo:
            g.dispositivos.add(d.dispositivo)
    por_codigo: dict[tuple[str, str], list[_Grupo]] = defaultdict(list)
    for (tipo, codigo, _, _), g in grupos.items():
        por_codigo[(tipo, codigo)].append(g)
    return por_codigo


def _situacao(grupos: list[_Grupo], cclasstrib: str | None = None) -> dict[str, Any]:
    """Como as pessoas decidiram um código. Com `cclasstrib`, compara com o enquadramento da regra."""
    melhor: dict[str, Any] = {
        "situacao": "sem_decisao",
        "decisoes": 0,
        "faltam": CONFIRMA,
        "cclasstrib": None,
        "ramo": None,
    }
    ordem = {"confirmado": 4, "em_confirmacao": 3, "divergem": 2, "outro": 1, "sem_decisao": 0}
    for g in grupos:
        t = g.totais()
        lider = max(t, key=lambda c: t[c])
        alvo = cclasstrib or lider
        a_favor, contra = t.get(alvo, 0), sum(n for c, n in t.items() if c != alvo)
        if a_favor and contra:
            s = "divergem"
        elif contra:
            s = "outro"
        elif a_favor >= CONFIRMA:
            s = "confirmado"
        else:
            s = "em_confirmacao"
        if ordem[s] > ordem[melhor["situacao"]] or (s == melhor["situacao"] and a_favor > melhor["decisoes"]):
            melhor = {
                "situacao": s,
                "decisoes": a_favor if s != "outro" else contra,
                "faltam": max(0, CONFIRMA - a_favor) if s == "em_confirmacao" else 0,
                "cclasstrib": alvo if s != "outro" else lider,
                "ramo": g.ramo,
            }
    return melhor


_ANEXO = re.compile(r"Anexo [IVXL]+, item \d")


def _cita(r: LegalRule, dispositivos: set[str]) -> bool:
    """A decisão citou este item de anexo? ("Anexo I, item 2" não casa com "Anexo I, item 20")."""
    if not r.anexo or not r.item:
        return False
    padrao = re.compile(rf"Anexo {re.escape(r.anexo)}, item {re.escape(r.item)}(?![\d.])")
    return any(padrao.search(d) for d in dispositivos)


def _cobre(prefixos_regra: list[tuple[str, bool]], codigo: str) -> bool:
    if any(exc and codigo.startswith(p) for p, exc in prefixos_regra):
        return False
    return any(not exc and codigo.startswith(p) for p, exc in prefixos_regra)


def _titulo(r: LegalRule) -> str:
    if r.anexo and r.item:
        return f"Anexo {r.anexo}, item {r.item}"
    return r.dispositivo_legal


def _desc(t: str, n: int = 180) -> str:
    t = (t or "").strip()
    return t if len(t) <= n else t[:n].rsplit(" ", 1)[0] + "…"


def resumo(session: Session, com_organizacao: bool) -> dict[str, Any]:
    regras = list(
        session.scalars(
            select(LegalRule).where(LegalRule.status != StatusRegra.SUBSTITUIDA, LegalRule.tipo_codigo.is_not(None))
        )
    )
    divergentes = [r for r in regras if exige_justificativa(r.avisos or [])]
    base = {
        "organizacao_selecionada": com_organizacao,
        "total_regras": len(regras),
        "aprovadas": sum(1 for r in regras if r.status == StatusRegra.APROVADA),
        "total_divergencias": len(divergentes),
    }
    if not com_organizacao:
        return {**base, "decisoes": 0, "regras_em_uso": [], "divergencias": [], "divergencias_sem_itens": 0}

    por_codigo = _grupos(session)
    # Códigos dos itens da organização (para saber quais divergências tocam produtos reais).
    itens: dict[tuple[str, str], int] = {
        (t, c): n
        for t, c, n in session.execute(
            text(
                "SELECT identidade->>'tipo_codigo', identidade->>'codigo', count(*) FROM audit_items "
                "WHERE identidade->>'codigo' IS NOT NULL AND NOT ignorado GROUP BY 1, 2"
            )
        )
    }
    codigos = set(por_codigo) | set(itens)
    pref = sorted({p for _, c in codigos for p in prefixos(c)})
    cobertura: dict[Any, list[tuple[str, bool]]] = defaultdict(list)
    if pref:
        for rid, p, exc in session.execute(
            text("SELECT rule_id, prefixo, excecao FROM legal_rule_codes WHERE prefixo = ANY(:p)"), {"p": pref}
        ):
            cobertura[rid].append((p, exc))

    # --- regras confirmadas (ou em confirmação) pelo uso ------------------------------------------------
    # Um NCM costuma estar em várias regras (ex.: 3004.90.99 em vários itens do Anexo IV). A decisão conta
    # para a regra que ela citou; sem citação de anexo, só quando uma única regra dá aquele cClassTrib.
    candidatas: dict[tuple[str, str, str], list[Any]] = defaultdict(list)
    for r in regras:
        if r.cclasstrib and r.id in cobertura:
            for tipo, cod in por_codigo:
                if tipo == r.tipo_codigo and _cobre(cobertura[r.id], cod):
                    candidatas[(tipo, cod, r.cclasstrib)].append(r.id)
    em_uso: list[dict[str, Any]] = []
    for r in regras:
        if not r.cclasstrib or r.id not in cobertura:
            continue
        cods = []
        for (tipo, cod), grupos in por_codigo.items():
            if r.id not in candidatas.get((tipo, cod, r.cclasstrib), []):
                continue
            unica = candidatas[(tipo, cod, r.cclasstrib)] == [r.id]
            proprios = [
                g
                for g in grupos
                if _cita(r, g.dispositivos) or (unica and not any(_ANEXO.search(d) for d in g.dispositivos))
            ]
            if proprios:
                s = _situacao(proprios, r.cclasstrib)
                if s["situacao"] in ("confirmado", "em_confirmacao", "divergem"):
                    cods.append({"codigo": formatar_codigo(tipo, cod), **s})
        if not cods:
            continue
        confirmados = sum(1 for c in cods if c["situacao"] == "confirmado")
        em_uso.append(
            {
                "regra_id": str(r.id),
                "titulo": _titulo(r),
                "descricao": _desc(r.descricao_legal),
                "cclasstrib": r.cclasstrib,
                "situacao": "confirmada" if confirmados else "em_confirmacao",
                "codigos_confirmados": confirmados,
                "codigos": sorted(cods, key=lambda c: (-c["decisoes"], c["codigo"]))[:20],
            }
        )
    em_uso.sort(key=lambda x: (x["situacao"] != "confirmada", -x["codigos_confirmados"], x["titulo"]))

    # --- divergências que tocam itens da organização ------------------------------------------------------
    divergencias: list[dict[str, Any]] = []
    sem_itens = 0
    for r in divergentes:
        avisos = exige_justificativa(r.avisos or [])
        afetados = {str(c).replace(".", "") for a in avisos for c in a.get("codigos") or []}
        regra_inteira = any(not a.get("codigos") for a in avisos)
        tocados = []
        for (tipo, cod), n in itens.items():
            if tipo != r.tipo_codigo:
                continue
            if any(cod.startswith(a) for a in afetados) or (regra_inteira and _cobre(cobertura.get(r.id, []), cod)):
                s = _situacao(por_codigo.get((tipo, cod), []))
                tocados.append({"codigo": formatar_codigo(tipo, cod), "itens": n, **s})
        if not tocados:
            sem_itens += 1
            continue
        resolvidos = sum(1 for t in tocados if t["situacao"] == "confirmado")
        divergencias.append(
            {
                "regra_id": str(r.id),
                "titulo": _titulo(r),
                "descricao": _desc(r.descricao_legal),
                "cclasstrib": r.cclasstrib,
                "mensagens": [a.get("mensagem") for a in avisos][:3],
                "gravidade": "alta" if any(a.get("gravidade") == "alta" for a in avisos) else "media",
                "itens": sum(t["itens"] for t in tocados),
                "resolvida": resolvidos == len(tocados),
                "codigos_resolvidos": resolvidos,
                "codigos": sorted(tocados, key=lambda t: (-t["itens"], t["codigo"]))[:20],
            }
        )
    divergencias.sort(key=lambda d: (d["resolvida"], -d["itens"], d["titulo"]))
    decisoes = session.scalar(text("SELECT count(*) FROM decision_memory WHERE ativo")) or 0
    return {
        **base,
        "decisoes": decisoes,
        "regras_em_uso": em_uso,
        "divergencias": divergencias,
        "divergencias_sem_itens": sem_itens,
    }
