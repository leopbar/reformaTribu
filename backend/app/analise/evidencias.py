"""Pacote de evidências de uma família (NCM/NBS): o material que o analista pode citar.

As "ferramentas" do agente são consultas determinísticas feitas aqui, antes da chamada ao modelo:
- identidade oficial do código (descrição hierárquica);
- correlação oficial cClassTrib × NCM/NBS (tabela do Portal da Conformidade Fácil), completada pelas
  ligações que a lei faz pela natureza do produto (`natureza.py`: medicamentos, in natura, livros…);
- trechos da LC 214/2025 que citam o código (itens de anexos) e artigos relevantes;
- artigos dos demais atos da base normativa (EC 132/2023, LC 227/2026, Decreto 12.955/2026);
- entradas da tabela cClassTrib candidatas (lista fechada: o modelo só escolhe entre elas);
- precedentes: regras legais já aprovadas por um revisor e alertas de divergência.

Cada peça recebe uma referência curta (P1, C1, T200003, R1) que o modelo usa para citar.
Citação a referência inexistente invalida o fundamento.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import bindparam, select, text
from sqlalchemy.orm import Session

from app.analise import natureza, transicao
from app.analise.operacao import cclasstrib_da_operacao
from app.core.codes import formatar_codigo
from app.models import CClassTribCode, CClassTribCorrelacao, LegalRule
from app.models.enums import StatusRegra
from app.reference.importers.lc214 import ROMANOS, romano_para_int
from app.reference.search import obter_no, termos_busca
from app.rules.divergencias import exige_justificativa

MAX_TRECHO = 1500
MAX_CCLASSTRIB = 25
CCLASSTRIB_REGRA_GERAL = "000001"
_ART = re.compile(r"\bart(?:igo)?s?\.?\s*(\d{1,3}(?:-[A-Z])?)", re.I)


@dataclass
class Evidencias:
    pacote: dict[str, Any]
    refs: dict[str, dict[str, Any]] = field(default_factory=dict)
    cclasstrib: dict[str, dict[str, Any]] = field(default_factory=dict)
    correlacionados: set[str] = field(default_factory=set)
    precedentes: list[dict[str, Any]] = field(default_factory=list)
    alertas: list[dict[str, Any]] = field(default_factory=list)


def prefixos(codigo: str) -> list[str]:
    return [codigo[:n] for n in range(2, len(codigo) + 1)]


def _cortar(t: str, n: int = MAX_TRECHO) -> str:
    t = (t or "").strip()
    return t if len(t) <= n else t[:n].rsplit(" ", 1)[0] + " […]"


def _vigente(inicio: date | None, fim: date | None, d: date) -> bool:
    return (inicio is None or inicio <= d) and (fim is None or fim >= d)


def _local(p: Any) -> str:
    if p.tipo == "anexo_item":
        return f"Anexo {p.anexo}, item {p.item}"
    return f"Art. {p.artigo}"


def montar(
    session: Session,
    *,
    tipo_codigo: str,
    codigo: str,
    data_referencia: date,
    versoes: dict[str, Any],
    versoes_normas: list[str],
    regras_ids: list[str],
    fatos_empresa: dict[str, str],
    embedding: list[float] | None,
) -> Evidencias:
    """Consulta a base versionada do snapshot e monta o pacote enviado ao modelo."""
    ev = Evidencias(pacote={})
    pref = prefixos(codigo)
    v_cod = versoes.get(tipo_codigo)
    no = obter_no(session, tipo_codigo, uuid.UUID(v_cod), codigo) if v_cod else None
    descricao = (no or {}).get("descricao_completa") or ""
    ev.pacote["codigo"] = {
        "tipo": tipo_codigo,
        "codigo": codigo,
        "formatado": formatar_codigo(tipo_codigo, codigo),
        "descricao_oficial": descricao,
    }

    # --- correlação oficial cClassTrib × NCM/NBS ------------------------------------------------
    v_cct = versoes.get("cclasstrib")
    correlacoes = []
    if v_cct:
        correlacoes = list(
            session.scalars(
                select(CClassTribCorrelacao)
                .where(
                    CClassTribCorrelacao.version_id == uuid.UUID(v_cct),
                    CClassTribCorrelacao.codigo_ncm_nbs.in_(pref),
                )
                .order_by(CClassTribCorrelacao.cclasstrib, CClassTribCorrelacao.codigo_ncm_nbs)
            )
        )
    pac_corr = []
    for n, corr in enumerate(correlacoes[:30], start=1):
        if not _vigente(corr.data_inicio, corr.data_fim, data_referencia):
            continue
        ref = f"C{n}"
        item = {
            "ref": ref,
            "cclasstrib": corr.cclasstrib,
            "anexo": ROMANOS[corr.nro_anexo - 1] if corr.nro_anexo and 0 < corr.nro_anexo <= len(ROMANOS) else None,
            "item_anexo": corr.nro_item_anexo,
            "descricao_item_anexo": _cortar(corr.descricao_item_anexo or corr.descricao_anexo or "", 500),
            "codigo_citado": formatar_codigo(tipo_codigo, corr.codigo_ncm_nbs),
            "permissao": corr.tipo_permissao,
            "condicao": corr.descricao_condicao,
            "excecao": corr.descricao_excecao,
            "observacao": corr.observacao,
        }
        pac_corr.append(item)
        ev.refs[ref] = {"tipo": "correlacao", "id": corr.id, **item}
        ev.correlacionados.add(corr.cclasstrib)
    # Benefícios que a lei dá pela natureza do produto, sem lista de NCM (medicamentos, in natura, livros…):
    # a tabela oficial não os correlaciona a nenhum código, e sem esta linha o Jurista não os veria (ADR 0027).
    for lg in natureza.ligacoes(tipo_codigo, codigo):
        ref = f"C{len(pac_corr) + 1}"
        item = {
            "ref": ref,
            "cclasstrib": lg.cclasstrib,
            "fonte": f"lei ({lg.norma}, art. {lg.artigo}): a tabela oficial não correlaciona este cClassTrib a "
            "códigos, porque a lei o concede pela natureza do produto",
            "anexo": None,
            "item_anexo": None,
            "descricao_item_anexo": lg.natureza,
            "codigo_citado": formatar_codigo(tipo_codigo, codigo),
            "permissao": "PERMITIDO",
            "condicao": lg.condicao,
            "excecao": lg.excecao or None,
            "observacao": lg.observacao or None,
        }
        pac_corr.append(item)
        ev.refs[ref] = {"tipo": "correlacao", "id": None, **item}
        ev.correlacionados.add(lg.cclasstrib)
    ev.pacote["correlacoes_oficiais"] = pac_corr

    # --- trechos normativos ---------------------------------------------------------------------
    v_lc = versoes.get("lc214")
    versoes_texto = [uuid.UUID(v) for v in ([v_lc] if v_lc else []) + list(versoes_normas)]
    colunas = (
        "id, tipo, anexo, item, artigo, titulo_anexo, texto, norma, vigencia_inicio, vigencia_fim, codigos_citados"
    )
    escolhidos: dict[uuid.UUID, Any] = {}
    if v_lc:
        for p in session.execute(
            text(
                f"SELECT {colunas} FROM legal_provisions WHERE version_id = :v AND tipo = 'anexo_item' "
                "AND codigos_citados && CAST(:p AS varchar[]) ORDER BY ordem LIMIT 12"
            ),
            {"v": uuid.UUID(v_lc), "p": pref},
        ):
            escolhidos[p.id] = p
    anexos_citados: set[str] = {str(p.anexo) for p in escolhidos.values() if p.anexo}
    anexos_citados |= {str(r["anexo"]) for r in pac_corr if r.get("anexo")}

    # Busca por significado e por texto nos artigos da base normativa (vigentes na data).
    consulta = (
        " ".join(descricao.split(" › ")[-3:])
        + " "
        + " ".join(str(r["descricao_item_anexo"] or "") for r in pac_corr[:3])
    )
    if versoes_texto:
        if embedding is not None:
            stmt = text(
                f"SELECT {colunas} FROM legal_provisions WHERE version_id = ANY(:vs) AND tipo = 'artigo' "
                "AND embedding IS NOT NULL ORDER BY embedding <=> :q LIMIT 6"
            ).bindparams(bindparam("q", type_=Vector(len(embedding))))
            for p in session.execute(stmt, {"vs": versoes_texto, "q": embedding}):
                escolhidos.setdefault(p.id, p)
        termos = termos_busca(consulta)[:10]
        if termos:
            for p in session.execute(
                text(
                    f"SELECT {colunas} FROM legal_provisions, to_tsquery('portuguese', :q) q "
                    "WHERE version_id = ANY(:vs) AND tipo = 'artigo' AND tsv @@ q "
                    "ORDER BY ts_rank_cd(tsv, q) DESC LIMIT 5"
                ),
                {"vs": versoes_texto, "q": " | ".join(termos)},
            ):
                escolhidos.setdefault(p.id, p)

    # --- cClassTrib candidatos (lista fechada) --------------------------------------------------
    cct_rows: list[CClassTribCode] = []
    if v_cct:
        cct_rows = list(session.scalars(select(CClassTribCode).where(CClassTribCode.version_id == uuid.UUID(v_cct))))
    num_anexos = {romano_para_int(a) for a in anexos_citados}
    candidatos: dict[str, CClassTribCode] = {}
    for c in cct_rows:
        if c.codigo == CCLASSTRIB_REGRA_GERAL or c.codigo in ev.correlacionados or (c.nro_anexo in num_anexos):
            candidatos[c.codigo] = c
    # Regimes que dependem da operação (bares e restaurantes, manipulação) não entram na tese do produto:
    # são decididos pelo catálogo de `operacao.py`, igual para todos os itens (ADR 0026).
    for cod in cclasstrib_da_operacao():
        candidatos.pop(cod, None)
    # Artigos citados pelos cClassTrib candidatos entram nos trechos (fundamento do próprio código).
    arts_cct = {m.group(1) for c in candidatos.values() for m in _ART.finditer(c.nome or "")}
    if v_lc and arts_cct:
        for p in session.execute(
            text(
                f"SELECT {colunas} FROM legal_provisions WHERE version_id = :v AND tipo = 'artigo' "
                "AND artigo = ANY(:a) ORDER BY ordem"
            ),
            {"v": uuid.UUID(v_lc), "a": sorted(arts_cct)},
        ):
            escolhidos.setdefault(p.id, p)

    pac_trechos = []
    for n, p in enumerate(escolhidos.values(), start=1):
        if not _vigente(p.vigencia_inicio, p.vigencia_fim, data_referencia):
            continue
        ref = f"P{n}"
        item = {
            "ref": ref,
            "norma": p.norma,
            "local": _local(p),
            "titulo": p.titulo_anexo,
            "texto": _cortar(p.texto),
        }
        pac_trechos.append(item)
        ev.refs[ref] = {"tipo": "trecho", "id": str(p.id), **item}
    ev.pacote["trechos_normativos"] = pac_trechos

    doc_ok = "ind_nfse" if tipo_codigo == "nbs" else "ind_nfce"
    pac_cct = []
    for c in sorted(candidatos.values(), key=lambda x: (x.codigo != CCLASSTRIB_REGRA_GERAL, x.codigo))[:MAX_CCLASSTRIB]:
        info: dict[str, Any] = {
            "ref": f"T{c.codigo}",
            "codigo": c.codigo,
            "cst": c.cst,
            "nome": c.nome,
            "reducao_ibs_pct": float(c.perc_red_ibs or 0),
            "reducao_cbs_pct": float(c.perc_red_cbs or 0),
            "tipo_aliquota": c.tipo_aliquota,
            "anexo": ROMANOS[c.nro_anexo - 1] if c.nro_anexo and 0 < c.nro_anexo <= len(ROMANOS) else None,
            "vigente_na_data": _vigente(c.data_inicio, c.data_fim, data_referencia),
            "permitido_no_documento": bool(getattr(c, doc_ok) or c.ind_nfe),
            "regulamento": _cortar(c.texto_regulamento_cbs or "", 600) or None,
        }
        pac_cct.append(info)
        ev.refs[f"T{c.codigo}"] = {"tipo": "cclasstrib", **info}
        ev.cclasstrib[c.codigo] = info
    ev.pacote["cclasstrib_candidatos"] = pac_cct

    # --- precedentes (regras aprovadas) e alertas de divergência --------------------------------
    if regras_ids:
        ids = [uuid.UUID(str(i)) for i in regras_ids]
        rows = session.execute(
            text(
                "SELECT DISTINCT rule_id FROM legal_rule_codes WHERE tipo_codigo = :t AND prefixo = ANY(:p) "
                "AND NOT excecao AND rule_id = ANY(:ids)"
            ),
            {"t": tipo_codigo, "p": pref, "ids": ids},
        )
        regra_ids = [r[0] for r in rows]
        for n, r in enumerate(session.scalars(select(LegalRule).where(LegalRule.id.in_(regra_ids))), start=1):
            for a in exige_justificativa(r.avisos or []):
                ev.alertas.append(
                    {
                        "descricao": a.get("mensagem"),
                        "gravidade": a.get("gravidade"),
                        "regra": r.dispositivo_legal,
                        "cclasstrib": r.cclasstrib,
                        # Códigos afetados pela divergência (vazio = a regra inteira).
                        "codigos": a.get("codigos") or [],
                    }
                )
            if r.status == StatusRegra.APROVADA:
                prec = {
                    "ref": f"R{n}",
                    "dispositivo": r.dispositivo_legal,
                    "descricao": _cortar(r.descricao_legal, 400),
                    "cclasstrib": r.cclasstrib,
                    "condicoes": r.condicoes,
                }
                ev.precedentes.append(prec)
                ev.refs[f"R{n}"] = {"tipo": "precedente", "id": str(r.id), **prec}
    ev.pacote["precedentes_aprovados"] = ev.precedentes
    ev.pacote["alertas_de_divergencia"] = ev.alertas[:8]
    ev.pacote["transicao"] = transicao.como_dict(data_referencia)
    return ev
