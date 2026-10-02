"""Memória de decisões (ADR 0028): o que as pessoas já decidiram para um código, cenário e ramo.

Cada aprovação ou correção feita por uma pessoa grava o enquadramento escolhido para o NCM/NBS do item,
no cenário e no ramo (segmento) da empresa, com os fatos que o decidiram. Nas análises seguintes da
organização, a avaliação compara a conclusão do analista com essas decisões:

- concordância: 1 decisão vira uma nota; 2 dispensam os avisos jurídicos leves; 3 confirmam o
  enquadramento e resolvem também o conflito normativo daquele código;
- discordância: o item vai para revisão; com 3 ou mais decisões contra, vai para o especialista.

Regras de contagem (evitam que a IA confirme a si mesma ou que um clique em lote "confirme" sozinho):
- só decisões de pessoas; a aprovação automática nunca grava aqui;
- cada auditoria conta no máximo uma vez por resultado;
- uma correção (enquadramento definido pela pessoa) pesa 2;
- a decisão só vale para itens decididos pelos mesmos fatos;
- a IA não vê esta memória: ela entra só na comparação, depois da análise.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.models import Audit, AuditItem, Company, DecisionMemory

CONFIRMA = 3  # decisões que confirmam o enquadramento
DISPENSA_AVISOS = 2  # decisões que dispensam os avisos jurídicos leves
PESO_CORRECAO = 2


def chave_fatos(fatos_usados: list[dict[str, Any]] | None) -> str:
    """Assinatura estável dos fatos que decidiram o enquadramento ("atributo=valor;...")."""
    pares = {
        str(f.get("atributo") or "").strip().lower(): str(f.get("valor") or "").strip().lower()
        for f in fatos_usados or []
        if f.get("atributo")
    }
    return ";".join(f"{k}={v}" for k, v in sorted(pares.items()))


def resultado(cclasstrib: str | None, imposto_seletivo: str | None) -> str:
    # "na_origem" (ADR 0029): o produto é sujeito ao IS; quem recolhe é decidido pelo dossiê da empresa.
    return f"{cclasstrib or ''}|{'sujeito' if imposto_seletivo in ('sujeito', 'na_origem') else 'nao_sujeito'}"


# ------------------------------------------------------------------------------------ gravação --
def registrar(
    session: Session,
    item: AuditItem,
    audit: Audit,
    review_id: uuid.UUID,
    user_id: uuid.UUID | None,
    user_email: str | None,
) -> DecisionMemory | None:
    """Grava a decisão de uma pessoa sobre o item aprovado. Devolve None quando não há o que aprender."""
    if not item.final_cclasstrib or not item.final_codigo or item.aprovado_automaticamente:
        return None
    # Regime decidido pela operação (restaurante, manipulação…): o cClassTrib não vem do código do produto.
    if (item.hipotese or "").startswith("OP-"):
        return None
    empresa = session.get(Company, item.company_id)
    corrigido = item.hipotese == "manual"
    d = DecisionMemory(
        org_id=item.org_id,
        company_id=item.company_id,
        audit_id=audit.id,
        item_id=item.id,
        review_id=review_id,
        segmento=empresa.segmento if empresa else None,
        cenario=item.cenario,
        tipo_codigo=item.final_tipo_codigo or "ncm",
        codigo=item.final_codigo,
        cclasstrib=item.final_cclasstrib,
        cst=item.final_cst,
        imposto_seletivo="sujeito" if item.is_situacao in ("sujeito", "na_origem") else "nao_sujeito",
        fatos_chave=chave_fatos(item.fatos_usados),
        fatos=[{"atributo": f.get("atributo"), "valor": f.get("valor")} for f in item.fatos_usados or []],
        dispositivo=item.final_dispositivo,
        origem="correcao" if corrigido else "aprovacao",
        peso=PESO_CORRECAO if corrigido else 1,
        user_id=user_id,
        user_email=user_email,
    )
    session.add(d)
    return d


def desativar(session: Session, review_id: uuid.UUID) -> None:
    session.execute(update(DecisionMemory).where(DecisionMemory.review_id == review_id).values(ativo=False))


# ------------------------------------------------------------------------------------- leitura --
def carregar(session: Session, item: AuditItem, empresa: Company) -> list[dict[str, Any]]:
    """Decisões ativas para o código do item, no mesmo cenário e ramo (sem ramo: só a própria empresa)."""
    idt = item.identidade or {}
    if not idt.get("codigo") or not idt.get("tipo_codigo"):
        return []
    mesmo_ramo = (
        DecisionMemory.segmento == empresa.segmento if empresa.segmento else DecisionMemory.company_id == empresa.id
    )
    rows = session.scalars(
        select(DecisionMemory).where(
            DecisionMemory.tipo_codigo == idt["tipo_codigo"],
            DecisionMemory.codigo == idt["codigo"],
            DecisionMemory.cenario == item.cenario,
            DecisionMemory.ativo.is_(True),
            DecisionMemory.item_id != item.id,
            or_(mesmo_ramo, DecisionMemory.company_id == empresa.id),
        )
    )
    return [
        {
            "audit_id": str(d.audit_id),
            "company_id": str(d.company_id),
            "resultado": resultado(d.cclasstrib, d.imposto_seletivo),
            "cclasstrib": d.cclasstrib,
            "fatos_chave": d.fatos_chave,
            "peso": d.peso,
            "origem": d.origem,
        }
        for d in rows
    ]


# ---------------------------------------------------------------------------------- comparação --
@dataclass
class Consolidado:
    a_favor: int = 0  # peso das decisões com o mesmo resultado da análise
    contra: int = 0  # peso das decisões com outro resultado
    outro: str | None = None  # o outro cClassTrib mais decidido
    empresas: int = 0  # empresas distintas que decidiram igual
    correcoes: int = 0
    resultados: dict[str, int] = field(default_factory=dict)

    @property
    def vazio(self) -> bool:
        return not self.a_favor and not self.contra


def consolidar(decisoes: list[dict[str, Any]], resultado_atual: str, fatos_chave: str) -> Consolidado:
    """Soma as decisões que valem para o item: mesmos fatos, no máximo uma por auditoria e resultado."""
    por_auditoria: dict[tuple[str, str], int] = {}
    empresas: dict[str, set[str]] = {}
    correcoes = 0
    for d in decisoes:
        if d.get("fatos_chave", "") != fatos_chave:
            continue
        k = (d["audit_id"], d["resultado"])
        por_auditoria[k] = max(por_auditoria.get(k, 0), int(d.get("peso") or 1))
        empresas.setdefault(d["resultado"], set()).add(d.get("company_id") or "")
        if d.get("origem") == "correcao" and d["resultado"] == resultado_atual:
            correcoes += 1
    totais: dict[str, int] = {}
    for (_, res), peso in por_auditoria.items():
        totais[res] = totais.get(res, 0) + peso
    outros = {r: n for r, n in totais.items() if r != resultado_atual}
    outro = max(outros, key=lambda r: outros[r]) if outros else None
    return Consolidado(
        a_favor=totais.get(resultado_atual, 0),
        contra=sum(outros.values()),
        outro=outro.split("|")[0] if outro else None,
        empresas=len(empresas.get(resultado_atual, set())),
        correcoes=correcoes,
        resultados=totais,
    )
