"""Extração assistida por IA das condições textuais de uma regra. O resultado é só uma proposta:
a regra continua pendente até um superadministrador aprová-la comparando com o texto legal."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.llm import gateway
from app.llm.prompts import carregar
from app.llm.schemas import SCHEMA_CONDICOES, ExtracaoCondicoes
from app.models import CClassTribCode, ConditionAttribute, LegalProvision, LegalRule
from app.models.enums import StatusRegra
from app.reference.importers.common import versao_ativa
from app.rules.validation import validar_regra


def montar_conteudo(session: Session, regra: LegalRule) -> dict[str, Any]:
    texto = regra.descricao_legal
    if regra.provision_id:
        prov = session.get(LegalProvision, regra.provision_id)
        if prov is not None:
            texto = prov.texto
    cct_nome = None
    v = versao_ativa(session, "cclasstrib")
    if regra.cclasstrib and v is not None:
        c = session.scalar(
            select(CClassTribCode).where(CClassTribCode.version_id == v.id, CClassTribCode.codigo == regra.cclasstrib)
        )
        cct_nome = c.nome if c else None
    catalogo = [
        {"chave": a.chave, "fonte": a.fonte, "pergunta": a.pergunta}
        for a in session.scalars(select(ConditionAttribute).order_by(ConditionAttribute.chave))
    ]
    codigos = [c["codigo"] for c in (regra.abrangencia or {}).get("codigos", [])]
    return {
        "anexo": regra.anexo,
        "item": regra.item,
        "titulo_anexo": regra.titulo_anexo,
        "texto_legal": texto,
        "descricao_cclasstrib": cct_nome,
        "codigos_abrangidos": codigos[:60],
        "total_codigos_abrangidos": len(codigos),
        "excecoes_por_codigo": [e["codigo"] for e in regra.excecoes or [] if e.get("codigo")][:60],
        "catalogo_atributos": catalogo,
    }


def sugerir_condicoes(session: Session, regra_id: uuid.UUID, solicitante: str | None = None) -> LegalRule:
    regra = session.get(LegalRule, regra_id)
    if regra is None:
        raise ValueError("Regra não encontrada.")
    if regra.status not in (StatusRegra.PENDENTE_REVISAO, StatusRegra.INVALIDA):
        raise ValueError("Somente regras pendentes podem receber sugestões de condições.")
    s = get_settings()
    prompt = carregar("extrair_condicoes")
    req = gateway.RequisicaoLLM(
        no="extrair_condicoes",
        modelo=s.llm_model_primary,
        prompt=prompt,
        conteudo_usuario=montar_conteudo(session, regra),
        schema=SCHEMA_CONDICOES,
        validador=ExtracaoCondicoes,
        esforco="medium",
        chave_idempotencia=f"regra:{regra.id}:extrair_condicoes:{prompt.rotulo}",
        org_id=None,
        plataforma=True,
        max_tokens=6000,
    )
    resultado = gateway.chamar_tempo_real(req)
    dados = ExtracaoCondicoes.model_validate(resultado.dados)
    regra.condicoes = [
        {
            "atributo": c.atributo.strip().lower(),
            "fonte": c.fonte,
            "deve_ser": c.deve_ser.strip().lower(),
            "pergunta": c.pergunta.strip(),
            "trecho_legal": c.trecho_legal.strip(),
        }
        for c in dados.condicoes
    ]
    textuais = [{"descricao": e.descricao, "trecho_legal": e.trecho_legal} for e in dados.excecoes_textuais]
    regra.excecoes = [e for e in regra.excecoes or [] if e.get("codigo")] + textuais
    regra.avisos = (
        [a for a in regra.avisos or [] if a.get("codigo") != "SUGESTAO_IA"]
        + [
            {
                "codigo": "SUGESTAO_IA",
                "mensagem": "Condições e exceções textuais sugeridas por IA; confira com o "
                "texto legal antes de aprovar.",
            }
        ]
        + [{"codigo": "OBSERVACAO_IA", "mensagem": o} for o in dados.observacoes]
    )
    regra.extracao = {
        **(regra.extracao or {}),
        "modelo": resultado.modelo,
        "prompt": resultado.prompt_versao,
        "llm_call_id": str(resultado.call_id),
        "solicitante": solicitante,
    }
    validar_regra(session, regra)
    return regra
