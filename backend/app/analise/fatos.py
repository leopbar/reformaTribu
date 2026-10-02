"""Fatos com origem: o que se sabe sobre a empresa, um grupo de itens ou um item.

Regra de ouro: hipótese não é fato. Só vira fato o que veio de uma pessoa, do ERP, do cadastro ou
do texto explícito da descrição (com o trecho guardado como evidência).

Precedência na resolução: item > grupo (categoria do ERP) > grupo (família NCM/NBS) > empresa.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.models import Company, CompanyFact
from app.models.enums import EscopoFato, OrigemFato

DESCONHECIDO = "desconhecido"

ROTULOS_ORIGEM: dict[str, str] = {
    OrigemFato.USUARIO: "informado por pessoa",
    OrigemFato.ERP: "planilha do ERP",
    OrigemFato.DESCRICAO: "explícito na descrição",
    OrigemFato.CADASTRO: "cadastro da empresa",
    OrigemFato.CODIGO: "pelo NCM do item",
}


def _sem_acento(t: str) -> str:
    return unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower().strip()


def chave(atributo: str) -> str:
    """Nome canônico de um fato: minúsculas, sem acentos, com sublinhado."""
    return re.sub(r"[^a-z0-9]+", "_", _sem_acento(atributo)).strip("_")[:80] or "fato"


def valor(v: Any) -> str:
    """Valor canônico: 'sim'/'nao' para booleanos, texto normalizado para o resto."""
    if isinstance(v, bool):
        return "sim" if v else "nao"
    if v is None:
        return DESCONHECIDO
    t = re.sub(r"\s+", " ", _sem_acento(str(v)))
    return {
        "s": "sim",
        "true": "sim",
        "verdadeiro": "sim",
        "yes": "sim",
        "n": "nao",
        "não": "nao",
        "false": "nao",
        "falso": "nao",
        "no": "nao",
        "nao sei": DESCONHECIDO,
        "": DESCONHECIDO,
        "indefinido": DESCONHECIDO,
    }.get(t, t)[:200]


def grupo_categoria(categoria: str | None) -> str | None:
    c = re.sub(r"\s+", " ", _sem_acento(categoria or "")).strip()
    return f"categoria:{c[:200]}" if c else None


def grupo_familia(tipo_codigo: str, codigo: str) -> str:
    return f"familia:{tipo_codigo}:{codigo}"


@dataclass(frozen=True)
class Fato:
    atributo: str
    valor: str
    origem: str
    escopo: str
    evidencia: str | None = None
    id: str | None = None
    autor: str | None = None
    grupo: str | None = None

    def como_dict(self) -> dict[str, Any]:
        return {
            "atributo": self.atributo,
            "valor": self.valor,
            "origem": self.origem,
            "origem_rotulo": ROTULOS_ORIGEM.get(self.origem, self.origem),
            "escopo": self.escopo,
            "grupo": self.grupo,
            "evidencia": self.evidencia,
            "id": self.id,
            "autor": self.autor,
        }


def _do_registro(f: CompanyFact) -> Fato:
    return Fato(
        atributo=f.atributo,
        valor=f.valor,
        origem=f.origem,
        escopo=f.escopo,
        evidencia=f.evidencia,
        id=str(f.id),
        autor=f.autor_email,
        grupo=f.grupo_chave or f.item_chave,
    )


def fatos_cadastro(empresa: Company) -> dict[str, Fato]:
    """Dados cadastrais viram fatos de empresa (origem 'cadastro')."""
    saida: dict[str, Fato] = {}
    for k, v in (
        ("regime_tributario", empresa.regime_tributario),
        ("uf", empresa.uf),
        ("cnae", empresa.cnae),
        ("segmento", empresa.segmento),
        ("atividade_principal", empresa.atividade_principal),
    ):
        if v:
            saida[k] = Fato(k, valor(v), OrigemFato.CADASTRO, EscopoFato.EMPRESA)
    return saida


def fatos_empresa(session: Session, empresa: Company) -> dict[str, Fato]:
    """Dossiê: cadastro + fatos de escopo empresa ativos (os informados prevalecem sobre o cadastro)."""
    saida = fatos_cadastro(empresa)
    for f in session.scalars(
        select(CompanyFact)
        .where(
            CompanyFact.company_id == empresa.id,
            CompanyFact.escopo == EscopoFato.EMPRESA,
            CompanyFact.ativo.is_(True),
        )
        .order_by(CompanyFact.created_at)
    ):
        saida[f.atributo] = _do_registro(f)
    return saida


# Dados cadastrais que não mudam o raciocínio jurídico de uma família: ficam fora da chave da tese,
# para que empresas com o mesmo perfil reaproveitem a mesma investigação. Quem recolhe o Imposto Seletivo
# (fabrica ou importa?) é decidido pelo sistema depois da tese (ADR 0029), não pelo Jurista.
FORA_DA_ASSINATURA = {"uf", "cnae", "atividade_principal", "fabrica_ou_importa_seletivo"}


def assinatura(fatos: dict[str, Fato]) -> dict[str, str]:
    """Parte do dossiê que entra na chave da tese (valores, sem autores nem datas)."""
    return {k: f.valor for k, f in sorted(fatos.items()) if f.valor != DESCONHECIDO and k not in FORA_DA_ASSINATURA}


def resolver(
    session: Session,
    empresa: Company,
    *,
    item_chave: str | None,
    categoria: str | None,
    familia: str | None,
    empresa_fatos: dict[str, Fato] | None = None,
) -> dict[str, Fato]:
    """Fatos aplicáveis a um item, com a precedência item > categoria > família > empresa."""
    saida = dict(empresa_fatos if empresa_fatos is not None else fatos_empresa(session, empresa))
    grupos = [g for g in (familia, grupo_categoria(categoria)) if g]
    condicoes = []
    if grupos:
        condicoes.append((CompanyFact.escopo == EscopoFato.GRUPO) & CompanyFact.grupo_chave.in_(grupos))
    if item_chave:
        condicoes.append((CompanyFact.escopo == EscopoFato.ITEM) & (CompanyFact.item_chave == item_chave))
    if not condicoes:
        return saida
    registros = list(
        session.scalars(
            select(CompanyFact).where(
                CompanyFact.company_id == empresa.id, CompanyFact.ativo.is_(True), or_(*condicoes)
            )
        )
    )
    prioridade = {familia: 1, grupo_categoria(categoria): 2}

    def peso(f: CompanyFact) -> tuple[int, Any]:
        base = 3 if f.escopo == EscopoFato.ITEM else prioridade.get(f.grupo_chave, 0)
        return (base, f.created_at)

    for f in sorted(registros, key=peso):
        saida[f.atributo] = _do_registro(f)
    return saida


def registrar(
    session: Session,
    *,
    org_id: uuid.UUID,
    company_id: uuid.UUID,
    escopo: str,
    atributo: str,
    valor_: str,
    origem: str,
    grupo_chave: str | None = None,
    item_chave: str | None = None,
    evidencia: str | None = None,
    autor_id: uuid.UUID | None = None,
    autor_email: str | None = None,
    audit_id: uuid.UUID | None = None,
    pendencia_id: uuid.UUID | None = None,
) -> CompanyFact:
    """Grava um fato, desativando o anterior do mesmo escopo e atributo (o histórico fica)."""
    atributo = chave(atributo)
    filtros = [
        CompanyFact.company_id == company_id,
        CompanyFact.escopo == escopo,
        CompanyFact.atributo == atributo,
        CompanyFact.ativo.is_(True),
    ]
    if escopo == EscopoFato.GRUPO:
        filtros.append(CompanyFact.grupo_chave == grupo_chave)
    if escopo == EscopoFato.ITEM:
        filtros.append(CompanyFact.item_chave == item_chave)
    anterior = session.scalar(select(CompanyFact).where(*filtros).order_by(CompanyFact.created_at.desc()).limit(1))
    # Um fato informado por pessoa não é sobrescrito por um extraído automaticamente.
    if anterior is not None and anterior.origem == OrigemFato.USUARIO and origem != OrigemFato.USUARIO:
        return anterior
    if anterior is not None:
        session.execute(update(CompanyFact).where(*filtros).values(ativo=False))
    f = CompanyFact(
        org_id=org_id,
        company_id=company_id,
        escopo=escopo,
        grupo_chave=grupo_chave,
        item_chave=item_chave,
        atributo=atributo,
        valor=valor(valor_),
        origem=origem,
        evidencia=evidencia,
        autor_id=autor_id,
        autor_email=autor_email,
        audit_id=audit_id,
        pendencia_id=pendencia_id,
        substitui_id=anterior.id if anterior else None,
    )
    session.add(f)
    session.flush()
    return f
