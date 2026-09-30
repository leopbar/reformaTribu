"""Respostas às perguntas decisivas: a resposta vira fato (com autor) e os itens afetados são reavaliados."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analise import fatos as fatos_mod
from app.core.errors import Conflito, NaoEncontrado
from app.models import AuditItem, Pendencia
from app.models.enums import EscopoFato, OrigemFato, StatusPendencia


@dataclass(frozen=True)
class Autor:
    user_id: uuid.UUID
    email: str


def responder(
    session: Session,
    pendencia_id: uuid.UUID,
    autor: Autor,
    *,
    valor: str | None = None,
    respostas_itens: dict[uuid.UUID, str] | None = None,
    observacao: str | None = None,
) -> list[uuid.UUID]:
    """Registra a resposta. `valor` vale para os itens listados na pergunta (ou para a empresa, se a
    pergunta for do dossiê); `respostas_itens` são exceções por item.

    Devolve os itens a reavaliar.
    """
    p = session.get(Pendencia, pendencia_id)
    if p is None:
        raise NaoEncontrado("Pergunta não encontrada.")
    if p.status == StatusPendencia.DESCARTADA:
        raise Conflito("Esta pergunta não é mais necessária.")
    if valor is None and not respostas_itens:
        raise Conflito("Informe uma resposta para o grupo ou para os itens.")
    validos = {o.get("valor") for o in p.opcoes or []}
    for v in [valor, *(respostas_itens or {}).values()]:
        if v is not None and validos and fatos_mod.valor(v) not in validos and fatos_mod.valor(v) != "desconhecido":
            raise Conflito(f"Resposta inválida: {v}. Opções: {', '.join(sorted(validos))}.")
    evidencia = f"Resposta à pergunta: {p.pergunta}" + (f" — {observacao}" if observacao else "")
    comum: dict[str, Any] = {
        "org_id": p.org_id,
        "company_id": p.company_id,
        "atributo": p.atributo,
        "origem": OrigemFato.USUARIO,
        "evidencia": evidencia[:2000],
        "autor_id": autor.user_id,
        "autor_email": autor.email,
        "audit_id": p.audit_id,
        "pendencia_id": p.id,
    }
    if valor is not None and fatos_mod.valor(valor) != "desconhecido":
        if p.escopo == EscopoFato.EMPRESA:
            fatos_mod.registrar(session, escopo=EscopoFato.EMPRESA, valor_=valor, **comum)
        else:
            # A resposta vale para os itens listados na pergunta, nem mais nem menos (ADR 0026): um item
            # da mesma categoria que chegar depois recebe a pergunta de novo, em vez de herdar em silêncio
            # uma resposta dada pensando em outros produtos.
            excecoes = {str(i) for i in (respostas_itens or {})}
            chaves = [
                i.codigo_interno
                for i in session.scalars(select(AuditItem).where(AuditItem.id.in_(list(p.item_ids))))
                if i.audit_id == p.audit_id and str(i.id) not in excecoes
            ]
            if p.escopo == EscopoFato.ITEM and p.grupo_chave.startswith("item:"):
                chaves.append(p.grupo_chave.removeprefix("item:"))
            for chave_item in dict.fromkeys(chaves):
                fatos_mod.registrar(session, escopo=EscopoFato.ITEM, item_chave=chave_item, valor_=valor, **comum)
    itens_resp: dict[str, str] = {}
    if respostas_itens:
        itens = {
            i.id: i
            for i in session.scalars(select(AuditItem).where(AuditItem.id.in_(list(respostas_itens))))
            if i.audit_id == p.audit_id
        }
        for iid, v in respostas_itens.items():
            item = itens.get(iid)
            if item is None or fatos_mod.valor(v) == "desconhecido":
                continue
            fatos_mod.registrar(session, escopo=EscopoFato.ITEM, item_chave=item.codigo_interno, valor_=v, **comum)
            itens_resp[str(iid)] = fatos_mod.valor(v)
    p.respostas_itens = {**(p.respostas_itens or {}), **itens_resp}
    completa = valor is not None or all(str(i) in p.respostas_itens for i in p.item_ids)
    if completa:
        p.status = StatusPendencia.RESPONDIDA
        p.resposta = fatos_mod.valor(valor) if valor is not None else "por item"
        p.respondido_por, p.respondido_por_email = autor.user_id, autor.email
        p.respondido_em = datetime.now(UTC)
    return list(p.item_ids)


def pendencias_empresa_abertas(session: Session, company_id: uuid.UUID, atributos: set[str]) -> list[Pendencia]:
    return list(
        session.scalars(
            select(Pendencia).where(
                Pendencia.company_id == company_id,
                Pendencia.escopo == EscopoFato.EMPRESA,
                Pendencia.status == StatusPendencia.ABERTA,
                Pendencia.atributo.in_(sorted(atributos)),
            )
        )
    )
