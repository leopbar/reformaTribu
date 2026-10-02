"""Medição sem IA (ADR 0029): quantos itens iriam para uma pessoa com as regras de hoje?

    python -m app.evals.replay                          # todas as auditorias concluídas
    python -m app.evals.replay --auditoria <id> [...]   # só algumas
    python -m app.evals.replay --gabarito /evals/conjunto_ouro/decisoes_humanas.csv

Refaz a identidade e a avaliação de cada item já analisado a partir do que a análise gravou (respostas da
IA, busca, árvore, tese da família), com o código atual, e compara com o resultado gravado e com o que as
pessoas decidiram. Não chama a IA, não grava nada no banco e não gera custo. Mede só o que é decidido
pelas regras do sistema: mudanças de instrução (prompt) dos agentes só aparecem depois de reanalisar.

Métricas:
- itens que iriam para uma pessoa (revisão do contador ou do especialista), antes e depois;
- perguntas ao operador (aguardando informação) e itens aguardando a IA (falha técnica, ADR 0029);
- falsos automáticos: itens que sairiam classificados sozinhos com cClassTrib diferente do que uma
  pessoa decidiu. Tem de ficar em zero; qualquer caso aparece listado no relatório.

O gabarito (`--gabarito`) é o conjunto das decisões de pessoas, no formato do harness (`app.evals.runner`).
"""

from __future__ import annotations

import argparse
import csv
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.db.session import TenantContext, sync_tenant_session
from app.models import Audit, AuditItem, LlmCall, Organization
from app.models.enums import StatusAuditoria, StatusRevisao

AGUARDANDO_IA = "aguardando_ia"
REANALISAR = "reanalisar"
PESSOA = ("revisao_contador", "revisao_especialista")
ROTULOS = {
    "classificado": "Classificado sozinho",
    "aguardando_informacao": "Pergunta ao operador",
    "revisao_contador": "Revisão do contador",
    "revisao_especialista": "Revisão do especialista",
    AGUARDANDO_IA: "Aguardando a IA (falha técnica)",
    REANALISAR: "Precisa de reanálise (parecer refeito)",
    "erro": "Erro",
}


@dataclass
class ItemMedido:
    auditoria: str
    linha: int
    descricao: str
    antes: str
    depois: str
    cct_antes: str | None
    cct_depois: str | None
    codigo_antes: str | None
    codigo_depois: str | None
    humano_cct: str | None = None
    humano_codigo: str | None = None
    motivos: list[str] = field(default_factory=list)
    porque: str = ""
    ajuste_cadastro: dict[str, Any] = field(default_factory=dict)

    @property
    def falso_automatico(self) -> bool:
        return self.depois == "classificado" and self.humano_cct is not None and self.cct_depois != self.humano_cct


# ------------------------------------------------------------------------------------- medição --
def _copia(item: AuditItem) -> AuditItem:
    """Cópia solta do item (fora da sessão): a avaliação lê o item, e nada pode ser gravado."""
    c = AuditItem()
    for col in AuditItem.__table__.columns:
        setattr(c, col.key, getattr(item, col.key))
    return c


def falha_de_infraestrutura(session: Any, item: AuditItem) -> bool:
    """A última análise do item esbarrou na plataforma de IA (sem créditos, fora do ar, limite de uso)."""
    texto = (item.erro or "").lower()
    if "falta de créditos" in texto or "várias tentativas" in texto or "indisponível" in texto:
        return True
    if not item.processado_em:
        return False
    inicio = item.processado_em - timedelta(minutes=30)
    return bool(
        session.scalar(
            select(LlmCall.id)
            .where(
                LlmCall.item_id == item.id,
                LlmCall.status == "falhou",
                LlmCall.erro.like("ErroTransitorio%"),
                LlmCall.created_at >= inicio,
                LlmCall.created_at <= item.processado_em,
            )
            .limit(1)
        )
    )


def _texto_porque(dimensoes: list[Any]) -> str:
    ruins = [d for d in dimensoes if d.situacao in ("falha", "atencao", "pendente")]
    return " | ".join(f"{d.chave}: {d.texto[:140]}" for d in ruins[:2])


def medir_item(session: Any, item: AuditItem, audit: Audit) -> ItemMedido | None:
    from app.analise import aplicacao
    from app.analise.avaliacao import avaliar
    from app.pipeline import analista

    if item.ignorado or not item.identidade or item.status in ("pendente", "processando"):
        return None
    humano = item.revisao_status == StatusRevisao.APROVADO and not item.aprovado_automaticamente
    medido = ItemMedido(
        auditoria=audit.nome,
        linha=item.linha,
        descricao=item.descricao,
        antes=item.status,
        depois=item.status,
        cct_antes=item.cclasstrib_sugerido,
        cct_depois=None,
        codigo_antes=(item.identidade or {}).get("codigo"),
        codigo_depois=None,
        humano_cct=item.final_cclasstrib if humano else None,
        humano_codigo=item.final_codigo if humano else None,
    )
    if falha_de_infraestrutura(session, item):
        medido.depois = AGUARDANDO_IA
        medido.porque = "a plataforma de IA falhou na última análise: o item espera a IA voltar"
        return medido
    state = analista.estado_do_registro(session, item)
    copia = _copia(item)
    copia.identidade = analista.identidade(state)
    tese, reanalisar = aplicacao.tese_para_reaplicar(session, item, audit, copia.identidade, aceitar_atual=humano)
    if reanalisar:
        medido.depois = REANALISAR
        medido.porque = "o parecer da família foi refeito: os fatos do item precisam ser levantados de novo"
        return medido
    with session.no_autoflush:
        ent = aplicacao.entrada(
            session, copia, audit, tese, tese_falha=state.tese_falha, base_incompleta=state.base_incompleta
        )
        av = avaliar(ent)
    medido.depois = av.status
    medido.cct_depois = av.cclasstrib
    medido.codigo_depois = copia.identidade.get("codigo")
    medido.motivos = av.motivos
    medido.porque = _texto_porque(av.dimensoes)
    medido.ajuste_cadastro = dict(getattr(av, "ajuste_cadastro", None) or {})
    return medido


def _orgs() -> list[uuid.UUID]:
    with sync_tenant_session(TenantContext(org_id=None, platform_admin=True)) as s:
        return list(s.scalars(select(Organization.id)))


def medir(auditorias: list[uuid.UUID] | None = None) -> list[ItemMedido]:
    saida: list[ItemMedido] = []
    for org in _orgs():
        with sync_tenant_session(TenantContext.sistema(org)) as s:
            q = select(Audit).where(Audit.status == StatusAuditoria.CONCLUIDA, ~Audit.nome.like("Teste%"))
            if auditorias:
                q = q.where(Audit.id.in_(auditorias))
            for audit in s.scalars(q.order_by(Audit.created_at)):
                for item in s.scalars(
                    select(AuditItem).where(AuditItem.audit_id == audit.id).order_by(AuditItem.linha)
                ):
                    m = medir_item(s, item, audit)
                    if m is not None:
                        saida.append(m)
            s.rollback()  # nada desta medição é gravado
    return saida


# ------------------------------------------------------------------------------------ relatório --
def resumo(itens: list[ItemMedido]) -> dict[str, Any]:
    antes, depois = Counter(i.antes for i in itens), Counter(i.depois for i in itens)
    total = len(itens) or 1
    humanos = [i for i in itens if i.humano_cct is not None]
    return {
        "itens": len(itens),
        "pessoa_antes": sum(antes[s] for s in PESSOA),
        "pessoa_depois": sum(depois[s] for s in PESSOA),
        "taxa_pessoa_antes": sum(antes[s] for s in PESSOA) / total,
        "taxa_pessoa_depois": sum(depois[s] for s in PESSOA) / total,
        "antes": dict(antes),
        "depois": dict(depois),
        "decididos_por_pessoas": len(humanos),
        "falsos_automaticos": [i for i in itens if i.falso_automatico],
        "ajustes_de_cadastro": sum(1 for i in itens if i.ajuste_cadastro),
    }


def relatorio(itens: list[ItemMedido]) -> str:
    r = resumo(itens)
    linhas = [
        f"# Medição sem IA — {datetime.now(UTC):%d/%m/%Y %H:%M} (UTC)",
        "",
        f"- Itens medidos: **{r['itens']}** (decididos por pessoas: {r['decididos_por_pessoas']})",
        f"- Iriam para uma pessoa: **{r['pessoa_antes']} ({r['taxa_pessoa_antes']:.0%})** antes → "
        f"**{r['pessoa_depois']} ({r['taxa_pessoa_depois']:.0%})** com as regras atuais",
        f"- Falsos automáticos (classificado sozinho com cClassTrib diferente do decidido por pessoa): "
        f"**{len(r['falsos_automaticos'])}**",
        f"- Ajustes de cadastro (NCM a confirmar sem mudar o imposto): {r['ajustes_de_cadastro']}",
        "",
        "| Resultado | Antes | Depois |",
        "|---|---:|---:|",
    ]
    for k, rot in ROTULOS.items():
        a, d = r["antes"].get(k, 0), r["depois"].get(k, 0)
        if a or d:
            linhas.append(f"| {rot} | {a} | {d} |")
    if r["falsos_automaticos"]:
        linhas += ["", "## Falsos automáticos (corrigir antes de liberar)", ""]
        for i in r["falsos_automaticos"]:
            linhas.append(
                f"- {i.auditoria} · linha {i.linha} · {i.descricao}: sairia {i.cct_depois}, a pessoa decidiu "
                f"{i.humano_cct}"
            )
    mudaram = [i for i in itens if i.antes != i.depois or i.cct_antes != i.cct_depois]
    if mudaram:
        linhas += ["", "## Itens que mudam", "", "| Auditoria | Linha | Item | Antes | Depois | cClassTrib | Por quê |"]
        linhas.append("|---|---:|---|---|---|---|---|")
        for i in mudaram:
            cct = i.cct_depois if i.cct_antes == i.cct_depois else f"{i.cct_antes or '—'} → {i.cct_depois or '—'}"
            porque = i.porque.replace("|", "/") or (
                "ajuste de cadastro: " + str(i.ajuste_cadastro.get("texto", "")) if i.ajuste_cadastro else ""
            )
            linhas.append(
                f"| {i.auditoria[:40]} | {i.linha} | {i.descricao} | {ROTULOS.get(i.antes, i.antes)} | "
                f"{ROTULOS.get(i.depois, i.depois)} | {cct or '—'} | {porque[:220]} |"
            )
    pessoa = [i for i in itens if i.depois in PESSOA]
    if pessoa:
        linhas += ["", "## Ainda vão para uma pessoa", ""]
        for i in pessoa:
            linhas.append(f"- {i.auditoria[:40]} · {i.linha} · {i.descricao} — {i.porque[:260]}")
    return "\n".join(linhas) + "\n"


def gravar_gabarito(caminho: Path) -> int:
    """Exporta as decisões de pessoas no formato do conjunto-ouro do harness (`app.evals.runner`)."""
    colunas = [
        "id",
        "descricao",
        "ncm_informado",
        "nbs_informado",
        "tipo",
        "esperado_tipo_codigo",
        "esperado_codigo",
        "esperado_cst",
        "esperado_cclasstrib",
        "esperado_status",
        "fatos",
        "validado_por",
        "observacao",
    ]
    linhas: list[dict[str, Any]] = []
    for org in _orgs():
        with sync_tenant_session(TenantContext.sistema(org)) as s:
            for item, audit in s.execute(
                select(AuditItem, Audit)
                .join(Audit, Audit.id == AuditItem.audit_id)
                .where(
                    AuditItem.revisao_status == StatusRevisao.APROVADO,
                    AuditItem.aprovado_automaticamente.is_(False),
                    AuditItem.final_cclasstrib.is_not(None),
                )
                .order_by(Audit.created_at, AuditItem.linha)
            ):
                fatos = ";".join(f"{f.get('atributo')}={f.get('valor')}" for f in item.fatos_usados or [])
                linhas.append(
                    {
                        "id": f"{audit.nome[:30]}#{item.linha}",
                        "descricao": item.descricao,
                        "ncm_informado": item.ncm_informado or "",
                        "nbs_informado": item.nbs_informado or "",
                        "tipo": item.tipo or "",
                        "esperado_tipo_codigo": item.final_tipo_codigo or "ncm",
                        "esperado_codigo": item.final_codigo or "",
                        "esperado_cst": item.final_cst or "",
                        "esperado_cclasstrib": item.final_cclasstrib or "",
                        "esperado_status": "",
                        "fatos": fatos,
                        "validado_por": "",  # preencher com nome e CRC do contador que validou
                        "observacao": f"decisão de pessoa na auditoria “{audit.nome}”",
                    }
                )
            s.rollback()
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("w", encoding="utf-8", newline="") as f:
        f.write("# Decisões de pessoas exportadas pela medição sem IA. Preencha validado_por com nome e CRC.\n")
        w = csv.DictWriter(f, fieldnames=colunas, delimiter=";")
        w.writeheader()
        w.writerows(linhas)
    return len(linhas)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--auditoria", action="append", type=uuid.UUID)
    p.add_argument("--saida", type=Path, default=Path("/evals/reports"))
    p.add_argument("--gabarito", type=Path)
    a = p.parse_args()
    if a.gabarito:
        n = gravar_gabarito(a.gabarito)
        print(f"Gabarito: {n} decisões de pessoas em {a.gabarito}")
    itens = medir(a.auditoria)
    texto = relatorio(itens)
    a.saida.mkdir(parents=True, exist_ok=True)
    arquivo = a.saida / f"medicao-sem-ia-{datetime.now(UTC):%Y%m%d-%H%M}.md"
    arquivo.write_text(texto, encoding="utf-8")
    print(texto)
    print(f"Relatório: {arquivo}")
    return 1 if resumo(itens)["falsos_automaticos"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
