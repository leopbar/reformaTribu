"""Harness de avaliação reproduzível.

    python -m app.evals.runner --conjunto /evals/conjunto_ouro/exemplo_nao_validado.csv \\
        --config /evals/configs/padrao.yaml [--config /evals/configs/outra.yaml] [--baseline /evals/baseline.json]

Para cada configuração (modelos, esforço, versões de prompt, dossiê), roda o analista REAL (API do
Claude, busca híbrida, investigação jurídica por família sobre a base normativa vigente) nos itens
do conjunto-ouro e calcula as métricas. Gera relatório em Markdown e HTML com a comparação lado a
lado e a distribuição de erros por nível de confiança.

Métrica principal: falsos classificados — itens que o analista deu como "classificado" (confiança
alta em todas as dimensões, elegível para aprovação automática) com NCM ou cClassTrib errado.
Regressão: com --baseline, termina com código 1 se essa taxa piorar.

Coluna opcional `fatos` no conjunto ("atributo=valor;atributo=valor"): fatos do item informados
antes da análise, como um operador faria ao responder as perguntas.

Os resultados só têm valor se o conjunto-ouro tiver sido validado por um contador (ver
docs/avaliacao.md). O arquivo de exemplo do repositório NÃO é validado.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import html
import json
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import func, select

from app.analise import fatos as fatos_mod
from app.core.codes import normalizar_cclasstrib, normalizar_nbs, normalizar_ncm, somente_digitos
from app.db.session import TenantContext, sync_tenant_session, tenant_session
from app.models import Audit, AuditItem, Company, LlmCall, Organization, OrgSettings
from app.models.enums import EscopoFato, OrigemFato
from app.pipeline import context as ctx_mod
from app.pipeline.runner import AGUARDANDO_LOTE, processar_item
from app.reference.snapshot import criar_ou_obter

CNPJ_AVALIACAO = "00000000000191"  # CNPJ reservado para a organização de avaliação (fictícia)


@dataclass
class ItemOuro:
    id: str
    descricao: str
    ncm_informado: str | None
    nbs_informado: str | None
    tipo: str | None
    esperado_tipo_codigo: str
    esperado_codigo: str
    esperado_cst: str | None
    esperado_cclasstrib: str | None
    esperado_status: str | None
    validado_por: str | None
    observacao: str = ""
    fatos: dict[str, str] = field(default_factory=dict)


@dataclass
class Resultado:
    ouro: ItemOuro
    status: str
    codigo: str | None
    cclasstrib: str | None
    confianca: str
    escalonado: bool
    custo: float
    segundos: float
    motivos: list[str] = field(default_factory=list)

    @property
    def acerto8(self) -> bool:
        return (self.codigo or "") == self.ouro.esperado_codigo

    @property
    def acerto4(self) -> bool:
        return (self.codigo or "")[:4] == self.ouro.esperado_codigo[:4]

    @property
    def acerto_cct(self) -> bool:
        return self.ouro.esperado_cclasstrib is None or self.cclasstrib == self.ouro.esperado_cclasstrib

    @property
    def correto(self) -> bool:
        return self.acerto8 and self.acerto_cct

    @property
    def falso_classificado(self) -> bool:
        return self.status == "classificado" and not self.correto


def carregar_conjunto(caminho: Path) -> tuple[list[ItemOuro], bool]:
    linhas = [li for li in caminho.read_text(encoding="utf-8").splitlines() if not li.startswith("#")]
    itens = []
    validado = True
    for r in csv.DictReader(linhas, delimiter=";"):
        tipo_cod = (r.get("esperado_tipo_codigo") or "ncm").strip()
        codigo = somente_digitos(r["esperado_codigo"])
        itens.append(
            ItemOuro(
                id=r["id"].strip(),
                descricao=r["descricao"].strip(),
                ncm_informado=(normalizar_ncm(r.get("ncm_informado")).codigo or None)
                if r.get("ncm_informado")
                else None,
                nbs_informado=normalizar_nbs(r.get("nbs_informado"))[0] if r.get("nbs_informado") else None,
                tipo=(r.get("tipo") or None),
                esperado_tipo_codigo=tipo_cod,
                esperado_codigo=codigo,
                esperado_cst=(r.get("esperado_cst") or None),
                esperado_cclasstrib=normalizar_cclasstrib(r.get("esperado_cclasstrib")),
                esperado_status=(r.get("esperado_status") or None),
                validado_por=(r.get("validado_por") or None),
                observacao=r.get("observacao") or "",
                fatos=dict(par.split("=", 1) for par in (r.get("fatos") or "").split(";") if "=" in par),
            )
        )
        validado = validado and bool(itens[-1].validado_por)
    return itens, validado


def _preparar_org(config: dict[str, Any]) -> tuple[uuid.UUID, uuid.UUID]:
    with sync_tenant_session(TenantContext(org_id=None, platform_admin=True)) as s:
        org = s.scalar(select(Organization).where(Organization.nome == "Avaliação (harness)"))
        if org is None:
            org = Organization(nome="Avaliação (harness)", tipo="empresa")
            s.add(org)
            s.flush()
        org_id = org.id
    with sync_tenant_session(TenantContext(org_id=org_id)) as s:
        if s.get(OrgSettings, org_id) is None:
            s.add(OrgSettings(org_id=org_id, orcamento_mensal_usd=None))
        emp = s.scalar(select(Company).where(Company.cnpj == CNPJ_AVALIACAO))
        if emp is None:
            emp = Company(
                org_id=org_id,
                razao_social="Empresa de avaliação (fictícia)",
                cnpj=CNPJ_AVALIACAO,
                regime_tributario="lucro_real",
                uf="SP",
                atributos={},
            )
            s.add(emp)
            s.flush()
        emp.segmento = config.get("segmento", "supermercado")
        for atributo, valor in (config.get("dossie") or {}).items():
            fatos_mod.registrar(
                s,
                org_id=org_id,
                company_id=emp.id,
                escopo=EscopoFato.EMPRESA,
                atributo=atributo,
                valor_=str(valor),
                origem=OrigemFato.USUARIO,
                evidencia="configuração da avaliação",
            )
        return org_id, emp.id


async def _snapshot(org_id: uuid.UUID) -> uuid.UUID:
    async with tenant_session(TenantContext(org_id=org_id)) as s:
        return (await criar_ou_obter(s)).id


def rodar(conjunto: list[ItemOuro], config: dict[str, Any]) -> list[Resultado]:
    org_id, emp_id = _preparar_org(config)
    snap = asyncio.run(_snapshot(org_id))
    aid = uuid.uuid4()
    configuracao = {k: v for k, v in config.items() if k != "nome"}
    with sync_tenant_session(TenantContext(org_id=org_id)) as s:
        s.add(
            Audit(
                id=aid,
                org_id=org_id,
                company_id=emp_id,
                nome=f"Avaliação {config.get('nome')}",
                mapeamento={},
                status="processando",
                modo="tempo_real",
                data_referencia=date.today(),
                snapshot_id=snap,
                contexto_operacao=config.get("contexto_operacao", {}),
                configuracao=configuracao,
            )
        )
        s.flush()
        ids = []
        for n, it in enumerate(conjunto, start=2):
            item = AuditItem(
                org_id=org_id,
                audit_id=aid,
                company_id=emp_id,
                linha=n,
                codigo_interno=it.id,
                descricao=it.descricao,
                ncm=it.ncm_informado,
                nbs=it.nbs_informado,
                ncm_informado=it.ncm_informado,
                nbs_informado=it.nbs_informado,
                tipo=it.tipo,
                problemas=[],
                status="pendente",
                motivos=[],
                revisao_status="pendente",
            )
            s.add(item)
            s.flush()
            ids.append(item.id)
            for atributo, valor in it.fatos.items():
                fatos_mod.registrar(
                    s,
                    org_id=org_id,
                    company_id=emp_id,
                    escopo=EscopoFato.ITEM,
                    item_chave=it.id,
                    atributo=atributo,
                    valor_=valor,
                    origem=OrigemFato.USUARIO,
                    evidencia="fato do conjunto-ouro",
                )
    ctx = ctx_mod.carregar_contexto(aid, org_id, forcar=True)
    resultados = []
    for it, iid in zip(conjunto, ids, strict=True):
        t0 = time.perf_counter()
        r = processar_item(iid, 1, ctx)
        dt = time.perf_counter() - t0
        with sync_tenant_session(TenantContext(org_id=org_id)) as s:
            i = s.get(AuditItem, iid)
            assert i is not None
            custo = s.scalar(select(func.coalesce(func.sum(LlmCall.custo_usd), 0)).where(LlmCall.item_id == iid))
            esc = s.scalar(
                select(func.count()).select_from(LlmCall).where(LlmCall.item_id == iid, LlmCall.no == "escalar")
            )
            resultados.append(
                Resultado(
                    ouro=it,
                    status=i.status if r != AGUARDANDO_LOTE else "pendente",
                    codigo=i.codigo_sugerido,
                    cclasstrib=i.cclasstrib_sugerido,
                    confianca=i.confianca_global or "",
                    escalonado=bool(esc),
                    custo=float(custo or Decimal(0)),
                    segundos=dt,
                    motivos=list(i.motivos or []),
                )
            )
    with sync_tenant_session(TenantContext(org_id=org_id)) as s:
        a = s.get(Audit, aid)
        if a is not None:
            a.status = "concluida"
    return resultados


def metricas(res: list[Resultado]) -> dict[str, float]:
    n = len(res) or 1
    classificados = [r for r in res if r.status == "classificado"]
    return {
        "itens": len(res),
        "acerto_ncm_8_digitos": sum(r.acerto8 for r in res) / n,
        "acerto_ncm_4_digitos": sum(r.acerto4 for r in res) / n,
        "acerto_cclasstrib": sum(r.acerto_cct for r in res) / n,
        "taxa_falsos_classificados": sum(r.falso_classificado for r in res) / n,
        "falsos_entre_classificados": (sum(r.falso_classificado for r in classificados) / len(classificados))
        if classificados
        else 0.0,
        "taxa_classificados": len(classificados) / n,
        "taxa_aguardando_informacao": sum(r.status == "aguardando_informacao" for r in res) / n,
        "taxa_revisao": sum(r.status in ("revisao_contador", "revisao_especialista") for r in res) / n,
        "taxa_escalonamento": sum(r.escalonado for r in res) / n,
        "custo_medio_usd": sum(r.custo for r in res) / n,
        "tempo_medio_s": sum(r.segundos for r in res) / n,
    }


def por_confianca(res: list[Resultado]) -> list[dict[str, Any]]:
    """Para cada nível de confiança global: quantos itens e quantos errados."""
    saida = []
    for nivel in ("alta", "media", "incompleta", "baixa", ""):
        grupo = [r for r in res if r.confianca == nivel]
        if grupo:
            saida.append(
                {"nivel": nivel or "sem resultado", "itens": len(grupo), "errados": sum(not r.correto for r in grupo)}
            )
    return saida


ROTULOS = {
    "itens": "Itens",
    "acerto_ncm_8_digitos": "Acerto NCM/NBS (8/9 dígitos)",
    "acerto_ncm_4_digitos": "Acerto NCM (posição, 4 dígitos)",
    "acerto_cclasstrib": "Acerto cClassTrib",
    "taxa_falsos_classificados": "Falsos classificados (principal)",
    "falsos_entre_classificados": "Falsos classificados / classificados",
    "taxa_classificados": "Classificados (confiança alta)",
    "taxa_aguardando_informacao": "Aguardando informação",
    "taxa_revisao": "Enviados à revisão",
    "taxa_escalonamento": "Escalonados",
    "custo_medio_usd": "Custo médio por item (US$)",
    "tempo_medio_s": "Tempo médio por item (s)",
}


def _fmt(k: str, v: float) -> str:
    if k == "itens":
        return str(int(v))
    if k == "custo_medio_usd":
        return f"{v:.4f}"
    if k == "tempo_medio_s":
        return f"{v:.1f}"
    return f"{v * 100:.1f}%"


def relatorio(
    execucoes: list[tuple[dict[str, Any], list[Resultado], dict[str, float]]], validado: bool, conjunto: Path
) -> tuple[str, str]:
    agora = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    aviso = (
        ""
        if validado
        else (
            "> **Atenção:** o conjunto usado NÃO foi validado por um contador. Os números abaixo servem apenas para "
            "testar o harness e não medem a qualidade real do sistema.\n"
        )
    )
    md = [
        f"# Relatório de avaliação — {agora}",
        "",
        f"Conjunto: `{conjunto.name}`",
        "",
        aviso,
        "## Comparação",
        "",
        "| Métrica | " + " | ".join(c.get("nome", "?") for c, _, _ in execucoes) + " |",
        "|---|" + "---|" * len(execucoes),
    ]
    for k, rot in ROTULOS.items():
        md.append(f"| {rot} | " + " | ".join(_fmt(k, m[k]) for _, _, m in execucoes) + " |")
    for cfg, res, _ in execucoes:
        md += [
            "",
            f"## Configuração `{cfg.get('nome')}`",
            "",
            "```yaml",
            yaml.safe_dump(cfg, allow_unicode=True).strip(),
            "```",
            "",
            "### Erros por nível de confiança",
            "",
            "| Confiança | Itens | Errados |",
            "|---|---|---|",
        ]
        for p in por_confianca(res):
            md.append(f"| {p['nivel']} | {p['itens']} | {p['errados']} |")
        md += [
            "",
            "### Erros",
            "",
            "| Item | Descrição | Esperado | Obtido | Status | Motivos |",
            "|---|---|---|---|---|---|",
        ]
        for r in res:
            if not r.correto or r.status != (r.ouro.esperado_status or r.status):
                alerta = " ⚠ FALSO CLASSIFICADO" if r.falso_classificado else ""
                esperado = f"{r.ouro.esperado_codigo} / {r.ouro.esperado_cclasstrib or '—'}"
                obtido = f"{r.codigo or '—'} / {r.cclasstrib or '—'}"
                md.append(
                    f"| {r.ouro.id} | {r.ouro.descricao} | {esperado} | {obtido} | {r.status}{alerta} | "
                    f"{', '.join(r.motivos)} |"
                )
    texto_md = "\n".join(md) + "\n"
    corpo = []
    for linha in md:
        if linha.startswith("# "):
            corpo.append(f"<h1>{html.escape(linha[2:])}</h1>")
        elif linha.startswith("## "):
            corpo.append(f"<h2>{html.escape(linha[3:])}</h2>")
        elif linha.startswith("### "):
            corpo.append(f"<h3>{html.escape(linha[4:])}</h3>")
        elif linha.startswith("|---"):
            continue
        elif linha.startswith("|"):
            cels = [c.strip() for c in linha.strip("|").split("|")]
            corpo.append("<tr>" + "".join(f"<td>{html.escape(c)}</td>" for c in cels) + "</tr>")
        elif linha.startswith(">"):
            corpo.append(f"<p class='aviso'>{html.escape(linha[1:].replace('**', ''))}</p>")
        elif linha and not linha.startswith("```"):
            corpo.append(f"<p>{html.escape(linha)}</p>")
    html_doc = (
        "<!doctype html><html lang='pt-BR'><meta charset='utf-8'><title>Avaliação</title><style>"
        "body{font-family:'IBM Plex Sans',system-ui,sans-serif;max-width:1100px;margin:2rem auto;color:#17202e}"
        "td{border-bottom:1px solid #d6dad3;padding:4px 8px;font-size:14px}.aviso{background:#fbeadb;padding:8px}"
        "</style><body><table>" + "".join(corpo) + "</table></body></html>"
    )
    return texto_md, html_doc


def main() -> int:
    p = argparse.ArgumentParser(description="Harness de avaliação do auditor fiscal")
    p.add_argument("--conjunto", type=Path, required=True)
    p.add_argument("--config", type=Path, action="append", required=True)
    p.add_argument("--baseline", type=Path)
    p.add_argument("--saida", type=Path, default=Path("/evals/reports"))
    p.add_argument("--atualizar-baseline", action="store_true")
    a = p.parse_args()
    conjunto, validado = carregar_conjunto(a.conjunto)
    execucoes = []
    for caminho in a.config:
        cfg = yaml.safe_load(caminho.read_text(encoding="utf-8")) or {}
        cfg.setdefault("nome", caminho.stem)
        print(f"Avaliando configuração {cfg['nome']} em {len(conjunto)} itens…")
        res = rodar(conjunto, cfg)
        m = metricas(res)
        execucoes.append((cfg, res, m))
        print(json.dumps({k: round(v, 4) for k, v in m.items()}, ensure_ascii=False))
    md, doc = relatorio(execucoes, validado, a.conjunto)
    a.saida.mkdir(parents=True, exist_ok=True)
    base = a.saida / datetime.now(UTC).strftime("avaliacao-%Y%m%d-%H%M%S")
    base.with_suffix(".md").write_text(md, encoding="utf-8")
    base.with_suffix(".html").write_text(doc, encoding="utf-8")
    print(f"Relatório: {base.with_suffix('.md')} e .html")

    principal = execucoes[0][2]
    if a.baseline:
        if a.atualizar_baseline or not a.baseline.exists():
            a.baseline.write_text(
                json.dumps({"conjunto": a.conjunto.name, "metricas": principal}, indent=2), encoding="utf-8"
            )
            print(f"Baseline gravado em {a.baseline}")
        else:
            ref = json.loads(a.baseline.read_text(encoding="utf-8"))["metricas"]
            chave = "taxa_falsos_classificados"
            if principal[chave] > ref.get(chave, 1.0) + 1e-9:
                print(
                    f"REGRESSÃO: falsos classificados {principal[chave]:.3%} > baseline "
                    f"{ref.get(chave, 1.0):.3%}. A mudança não deve entrar."
                )
                return 1
            print("Sem regressão na taxa de falsos classificados.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
