"""Validação das regras contra as tabelas oficiais importadas."""

from __future__ import annotations

from typing import Any

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.models import CClassTribCode, ConditionAttribute, LegalRule, NbsNode, NcmNode
from app.models.enums import FonteReferencia, StatusRegra, TipoTratamento
from app.reference.importers.common import versao_ativa
from app.rules.divergencias import ContextoDivergencias, detectar_divergencias


def codigo_existe(session: Session, tipo: str, codigo: str, version_id: Any) -> bool:
    modelo = NbsNode if tipo == "nbs" else NcmNode
    if session.scalar(select(exists().where(modelo.version_id == version_id, modelo.codigo == codigo))):
        return True
    # Níveis intermediários que a tabela não lista explicitamente (ex.: subposição de 5 dígitos):
    # vale se houver ao menos um código folha começando por ele.
    return bool(
        session.scalar(
            select(
                exists().where(
                    modelo.version_id == version_id, modelo.folha.is_(True), modelo.codigo.startswith(codigo)
                )
            )
        )
    )


def validar_regra(
    session: Session, regra: LegalRule, ctx: ContextoDivergencias | None = None, *, divergencias: bool = True
) -> list[dict[str, str]]:
    """Valida a regra e recalcula os avisos. `divergencias=False` adia a comparação com a lei (usada
    na geração em massa, que chama `revalidar_todas` ao final)."""
    erros: list[dict[str, str]] = []
    avisos: list[dict[str, Any]] = [
        a
        for a in (regra.avisos or [])
        if a.get("codigo") not in ("ATRIBUTO_NOVO", "CODIGO_EXTINTO_EXCECAO") and not a.get("divergencia")
    ]
    is_seletivo = regra.tipo_tratamento == TipoTratamento.IMPOSTO_SELETIVO

    # CST e cClassTrib na tabela oficial vigente
    v_cct = versao_ativa(session, FonteReferencia.CCLASSTRIB)
    if not is_seletivo:
        if not regra.cst_ibs_cbs or not regra.cclasstrib:
            erros.append({"codigo": "CST_CCLASSTRIB_AUSENTE", "mensagem": "Defina o CST e o cClassTrib da regra."})
        elif v_cct is None:
            erros.append(
                {
                    "codigo": "BASE_REFERENCIA_INCOMPLETA",
                    "mensagem": "A tabela cClassTrib não foi importada; não é possível validar.",
                }
            )
        else:
            c = session.scalar(
                select(CClassTribCode).where(
                    CClassTribCode.version_id == v_cct.id, CClassTribCode.codigo == regra.cclasstrib
                )
            )
            if c is None:
                erros.append(
                    {
                        "codigo": "CCLASSTRIB_INEXISTENTE",
                        "mensagem": f"O cClassTrib {regra.cclasstrib} não existe na tabela oficial vigente.",
                    }
                )
            elif c.cst != regra.cst_ibs_cbs:
                erros.append(
                    {
                        "codigo": "CST_INCOMPATIVEL",
                        "mensagem": f"O cClassTrib {regra.cclasstrib} pertence ao CST {c.cst}, não ao "
                        f"CST {regra.cst_ibs_cbs}.",
                    }
                )
            elif c.data_fim is not None and regra.vigencia_inicio and c.data_fim < regra.vigencia_inicio:
                erros.append(
                    {
                        "codigo": "CCLASSTRIB_NAO_VIGENTE",
                        "mensagem": f"O cClassTrib {regra.cclasstrib} não está vigente.",
                    }
                )
    elif regra.cst_ibs_cbs or regra.cclasstrib:
        erros.append(
            {
                "codigo": "IS_COM_CCLASSTRIB",
                "mensagem": "Regras do Imposto Seletivo apenas sinalizam o item; não definem CST/cClassTrib.",
            }
        )

    # Códigos abrangidos e exceções na nomenclatura vigente
    abr = regra.abrangencia or {}
    codigos = [c["codigo"] for c in abr.get("codigos", [])]
    if not abr.get("universal") and not codigos:
        erros.append({"codigo": "SEM_ABRANGENCIA", "mensagem": "A regra não abrange nenhum código."})
    if codigos and regra.tipo_codigo:
        fonte = FonteReferencia.NBS if regra.tipo_codigo == "nbs" else FonteReferencia.NCM
        v_nom = versao_ativa(session, fonte)
        if v_nom is None:
            erros.append(
                {
                    "codigo": "BASE_REFERENCIA_INCOMPLETA",
                    "mensagem": f"A tabela {fonte.value.upper()} não foi importada; os códigos não "
                    "puderam ser conferidos.",
                }
            )
        else:
            inexistentes = [c for c in codigos if not codigo_existe(session, regra.tipo_codigo, c, v_nom.id)]
            if inexistentes:
                erros.append(
                    {
                        "codigo": "CODIGO_INEXISTENTE",
                        "mensagem": f"Códigos inexistentes ou extintos na tabela {fonte.value.upper()} "
                        f"vigente: {', '.join(inexistentes[:20])}"
                        + (f" e mais {len(inexistentes) - 20}" if len(inexistentes) > 20 else ""),
                    }
                )
            exc_inex = [
                e["codigo"]
                for e in regra.excecoes or []
                if e.get("codigo") and not codigo_existe(session, regra.tipo_codigo, e["codigo"], v_nom.id)
            ]
            if exc_inex:
                avisos.append(
                    {
                        "codigo": "CODIGO_EXTINTO_EXCECAO",
                        "mensagem": "Exceções com códigos inexistentes na tabela vigente: " + ", ".join(exc_inex[:20]),
                    }
                )

    # Condições: atributos precisam existir no catálogo (ou serão criados na aprovação)
    catalogo = set(session.scalars(select(ConditionAttribute.chave)))
    for cond in regra.condicoes or []:
        if not cond.get("atributo") or not cond.get("pergunta") or cond.get("deve_ser") in (None, ""):
            erros.append(
                {
                    "codigo": "CONDICAO_INCOMPLETA",
                    "mensagem": "Toda condição precisa de atributo, valor exigido e pergunta.",
                }
            )
        elif cond["atributo"] not in catalogo:
            avisos.append(
                {
                    "codigo": "ATRIBUTO_NOVO",
                    "mensagem": f"O atributo '{cond['atributo']}' não existe no catálogo e será criado na aprovação.",
                }
            )

    if divergencias and regra.status in (StatusRegra.PENDENTE_REVISAO, StatusRegra.INVALIDA, StatusRegra.APROVADA):
        session.flush()
        avisos += detectar_divergencias(ctx or ContextoDivergencias(session), regra)

    regra.erros_validacao = erros
    regra.avisos = avisos
    if erros and regra.status == StatusRegra.PENDENTE_REVISAO:
        regra.status = StatusRegra.INVALIDA
    elif not erros and regra.status == StatusRegra.INVALIDA:
        regra.status = StatusRegra.PENDENTE_REVISAO
    return erros


def revalidar_todas(session: Session) -> dict[str, int]:
    """Revalida regras pendentes, inválidas e aprovadas (ex.: após importar uma nova tabela)."""
    contagem = {"validas": 0, "com_erros": 0, "com_divergencias": 0}
    ctx = ContextoDivergencias(session)
    for r in session.scalars(
        select(LegalRule).where(
            LegalRule.status.in_([StatusRegra.PENDENTE_REVISAO, StatusRegra.INVALIDA, StatusRegra.APROVADA])
        )
    ):
        erros = validar_regra(session, r, ctx)
        contagem["com_erros" if erros else "validas"] += 1
        contagem["com_divergencias"] += any(a.get("divergencia") for a in r.avisos or [])
    return contagem
