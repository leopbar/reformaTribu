"""Aplicação do resultado do analista a um item: perfil tributário versionado, perguntas agrupadas e
aprovação automática. Também reavalia itens quando um fato novo chega (sem chamar a IA)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.analise import fatos as fatos_mod
from app.analise.avaliacao import Avaliacao, EntradaAvaliacao, avaliar
from app.core.codes import formatar_codigo
from app.models import Audit, AuditItem, Company, OrgSettings, Pendencia, RefSnapshot, TaxProfile, TaxThesis
from app.models.enums import EscopoFato, StatusItem, StatusPendencia, StatusRevisao

CAMPOS_PERFIL = ("status", "cclasstrib", "cst", "hipotese", "imposto_seletivo", "codigo")


def grupo_da_pergunta(item: AuditItem, escopo: str) -> tuple[str, str, str]:
    """(escopo, grupo_chave, rótulo) da pergunta: o mais amplo possível."""
    if escopo == EscopoFato.EMPRESA:
        return EscopoFato.EMPRESA, "", "Toda a empresa"
    cat = fatos_mod.grupo_categoria(item.categoria)
    if cat:
        return EscopoFato.GRUPO, cat, f"Categoria “{item.categoria}”"
    tipo = (item.identidade or {}).get("tipo_codigo") or item.tipo_codigo_sugerido or "ncm"
    codigo = (item.identidade or {}).get("codigo") or item.codigo_sugerido
    if codigo:
        desc = ((item.identidade or {}).get("descricao_oficial") or "").split(" › ")[-1][:120]
        return (
            EscopoFato.GRUPO,
            fatos_mod.grupo_familia(tipo, codigo),
            f"{tipo.upper()} {formatar_codigo(tipo, codigo)}" + (f" — {desc}" if desc else ""),
        )
    return EscopoFato.ITEM, f"item:{item.codigo_interno}", f"Item {item.codigo_interno}"


def entrada(
    session: Session,
    item: AuditItem,
    audit: Audit,
    tese: TaxThesis | None,
    *,
    tese_falha: str | None = None,
    base_incompleta: bool = False,
) -> EntradaAvaliacao:
    empresa = session.get(Company, item.company_id)
    assert empresa is not None
    cfg = session.get(OrgSettings, item.org_id)
    idt = item.identidade or {}
    familia = fatos_mod.grupo_familia(idt["tipo_codigo"], idt["codigo"]) if idt.get("codigo") else None
    resolvidos = fatos_mod.resolver(
        session, empresa, item_chave=item.codigo_interno, categoria=item.categoria, familia=familia
    )
    ev = (tese.evidencias if tese else None) or {}
    fatos = {k: f.como_dict() for k, f in resolvidos.items()}
    return EntradaAvaliacao(
        identidade=idt,
        tese=tese.resultado if tese is not None and tese.status == "concluida" else None,
        cclasstrib=ev.get("cclasstrib", {}),
        refs=ev.get("refs", {}),
        fatos=fatos,
        correlacionados=ev.get("correlacionados", []),
        precedentes=ev.get("precedentes", []),
        alertas=ev.get("alertas", []),
        sugestoes=(item.estrutura or {}).get("sugestoes_fatos", {}),
        tese_falha=tese_falha or (tese.erro if tese is not None and tese.status != "concluida" else None),
        base_incompleta=base_incompleta,
        is_exige_analise=bool(cfg.imposto_seletivo_exige_analise) if cfg else True,
        tese_aprovada=bool(tese and tese.aprovada_em),
        tratamento_alternativas=tratamento_alternativas(session, item, audit, fatos),
        produtos_na_lei=_produtos_na_lei(session, item, audit),
    )


def _produtos_na_lei(session: Session, item: AuditItem, audit: Audit) -> list[dict[str, Any]]:
    from app.analise.anexos import produtos_citados_com_outro_codigo

    idt = item.identidade or {}
    snap = session.get(RefSnapshot, audit.snapshot_id) if audit.snapshot_id else None
    versao_lei = ((snap.versoes if snap else None) or {}).get("lc214")
    return produtos_citados_com_outro_codigo(
        session, versao_lei, item.descricao_normalizada or item.descricao, idt.get("tipo_codigo"), idt.get("codigo")
    )


def tratamento_alternativas(
    session: Session, item: AuditItem, audit: Audit, fatos: dict[str, dict[str, Any]]
) -> dict[str, str | None]:
    """Para cada código alternativo da dúvida de identificação, o tratamento ("cClassTrib|IS") que ele
    teria. Sem IA: usa o parecer já existente da família ou, se não houver, a base oficial."""
    idt = item.identidade or {}
    tipo = idt.get("tipo_codigo")
    if not tipo or not idt.get("codigos_alternativos"):
        return {}
    snap = session.get(RefSnapshot, audit.snapshot_id) if audit.snapshot_id else None
    versoes = (snap.versoes if snap else None) or {}
    return {
        cod: tratamento_do_codigo(session, tipo, cod, item.cenario, audit.data_referencia, versoes, fatos)
        for cod in idt["codigos_alternativos"][:3]
    }


def tratamento_do_codigo(
    session: Session,
    tipo: str,
    codigo: str,
    cenario: str,
    data_referencia: Any,
    versoes: dict[str, Any],
    fatos: dict[str, dict[str, Any]],
) -> str | None:
    from app.analise.avaliacao import escolher
    from app.analise.evidencias import prefixos

    tese = session.scalar(
        select(TaxThesis)
        .where(
            TaxThesis.status == "concluida",
            TaxThesis.tipo_codigo == tipo,
            TaxThesis.codigo == codigo,
            TaxThesis.cenario == cenario,
            TaxThesis.data_referencia == data_referencia,
        )
        .order_by(TaxThesis.created_at.desc())
        .limit(1)
    )
    if tese is not None:
        h, _, _ = escolher((tese.resultado or {}).get("hipoteses", []), fatos)
        situacao = ((tese.resultado or {}).get("imposto_seletivo") or {}).get("situacao", "nao_sujeito")
        if h is None or situacao == "depende":
            return None
        return f"{h['cclasstrib']}|{'sujeito' if situacao == 'sujeito' else 'nao_sujeito'}"
    # Sem parecer: se nem a correlação oficial nem nenhum anexo da lei citam o código, vale a regra geral.
    pref = prefixos(codigo)
    v_cct, v_lc = versoes.get("cclasstrib"), versoes.get("lc214")
    if not v_cct or not v_lc:
        return None
    citacoes = session.scalar(
        text(
            "SELECT (SELECT count(*) FROM cclasstrib_correlacoes WHERE version_id = :vc "
            "AND codigo_ncm_nbs = ANY(:p) AND upper(coalesce(tipo_permissao, '')) <> 'VEDADO') + "
            "(SELECT count(*) FROM legal_provisions WHERE version_id = :vl AND tipo = 'anexo_item' "
            "AND codigos_citados && CAST(:p AS varchar[]))"
        ),
        {"vc": uuid.UUID(str(v_cct)), "vl": uuid.UUID(str(v_lc)), "p": pref},
    )
    return "000001|nao_sujeito" if not citacoes else None


def _dispositivo(av: Avaliacao) -> str | None:
    locais = [
        f"{f.get('norma') or ''} {f.get('local') or ''}".strip()
        for f in av.fundamentos
        if f.get("tipo") in ("trecho", "precedente") and (f.get("local") or f.get("norma"))
    ]
    return "; ".join(dict.fromkeys(locais)) or None


def _registrar_perguntas(session: Session, item: AuditItem, av: Avaliacao) -> list[dict[str, Any]]:
    saida = []
    atuais: list[uuid.UUID] = []
    for p in av.perguntas:
        escopo, grupo, rotulo = grupo_da_pergunta(item, p.escopo)
        stmt = (
            pg_insert(Pendencia)
            .values(
                id=uuid.uuid4(),
                org_id=item.org_id,
                audit_id=item.audit_id,
                company_id=item.company_id,
                atributo=p.atributo,
                escopo=escopo,
                grupo_chave=grupo,
                grupo_rotulo=rotulo,
                pergunta=p.pergunta,
                motivo=p.motivo,
                opcoes=p.opcoes,
                nivel=p.nivel,
                item_ids=[item.id],
                status=StatusPendencia.ABERTA,
                respostas_itens={},
            )
            .on_conflict_do_update(
                constraint="uq_pendencias_pergunta",
                set_={
                    "item_ids": text(
                        "(SELECT array_agg(DISTINCT x) FROM unnest(pendencias.item_ids || excluded.item_ids) x)"
                    ),
                    "status": text(
                        "CASE WHEN pendencias.status = 'respondida' THEN pendencias.status ELSE 'aberta' END"
                    ),
                    "updated_at": datetime.now(UTC),
                },
            )
            .returning(Pendencia.id)
        )
        pid = session.execute(stmt).scalar_one()
        atuais.append(pid)
        saida.append(
            {
                "pendencia_id": str(pid),
                "atributo": p.atributo,
                "pergunta": p.pergunta,
                "escopo": escopo,
                "grupo": rotulo,
                "opcoes": p.opcoes,
                "motivo": p.motivo,
                "sugestao": p.sugestao,
            }
        )
    # O item sai das perguntas que não precisa mais responder.
    session.execute(
        text(
            "UPDATE pendencias SET item_ids = array_remove(item_ids, :i), updated_at = now() "
            "WHERE audit_id = :a AND :i = ANY(item_ids) AND NOT (id = ANY(:atuais))"
        ),
        {"i": item.id, "a": item.audit_id, "atuais": atuais},
    )
    session.execute(
        text(
            "UPDATE pendencias SET status = 'descartada' WHERE audit_id = :a AND status = 'aberta' "
            "AND cardinality(item_ids) = 0"
        ),
        {"a": item.audit_id},
    )
    return saida


def aplicar(
    session: Session,
    item: AuditItem,
    audit: Audit,
    av: Avaliacao,
    tese: TaxThesis | None,
    *,
    motivos_identidade: list[str] | None = None,
    motivo_versao: str = "análise do agente",
) -> None:
    cfg = session.get(OrgSettings, item.org_id)
    idt = item.identidade or {}
    if item.revisao_status == StatusRevisao.APROVADO and item.aprovado_automaticamente:
        # Aprovação automática vale para o resultado anterior; é refeita abaixo se continuar alta.
        item.revisao_status = StatusRevisao.PENDENTE
        item.aprovado_automaticamente = False
        item.final_tipo_codigo = item.final_codigo = item.final_cclasstrib = item.final_cst = None
        item.final_dispositivo, item.revisado_em = None, None
    item.status = av.status
    item.nivel_revisao = av.nivel
    item.confianca_global = av.confianca_global
    item.hipotese = av.hipotese
    item.conclusao = av.conclusao
    item.dimensoes = av.dimensoes_dict()
    item.fatos_usados = av.fatos_usados
    item.fundamentos = av.fundamentos
    item.thesis_id = tese.id if tese else None
    item.cst_sugerido, item.cclasstrib_sugerido = av.cst, av.cclasstrib
    item.perc_red_ibs = Decimal(str(av.perc_red_ibs)) if av.perc_red_ibs is not None else None
    item.perc_red_cbs = Decimal(str(av.perc_red_cbs)) if av.perc_red_cbs is not None else None
    item.is_situacao = av.is_situacao
    item.imposto_seletivo = av.is_situacao == "sujeito"
    item.tipo_tratamento = av.tratamento
    item.dispositivo_legal = _dispositivo(av)
    # Sem código na análise atual, não sobra sugestão de uma análise anterior na tela.
    item.tipo_codigo_sugerido = idt.get("tipo_codigo") or (item.tipo_codigo_sugerido if idt.get("codigo") else None)
    item.codigo_sugerido = idt.get("codigo")
    item.motivos = list(dict.fromkeys([*(motivos_identidade or []), *av.motivos]))
    item.perguntas = _registrar_perguntas(session, item, av)
    item.etapa = "concluido"
    item.processado_em = datetime.now(UTC)

    # --- perfil tributário (versionado: só muda quando o resultado muda) ------------------------
    versionar_perfil(
        session,
        item,
        audit,
        registro={
            "identidade": idt,
            "fatos_usados": av.fatos_usados,
            "fundamentos": av.fundamentos,
            "hipoteses_avaliadas": av.hipoteses_avaliadas,
            "perguntas": item.perguntas,
            "tese": {
                "id": str(tese.id) if tese else None,
                "modelo": tese.modelo if tese else None,
                "prompt": tese.prompt_versao if tese else None,
                "aprovada_por": tese.aprovada_por_email if tese else None,
            },
        },
        motivo=motivo_versao,
    )

    # --- aprovação automática --------------------------------------------------------------------
    if (
        av.status == StatusItem.CLASSIFICADO
        and item.revisao_status == StatusRevisao.PENDENTE
        and (cfg.aprovacao_automatica if cfg else True)
    ):
        item.revisao_status = StatusRevisao.APROVADO
        item.aprovado_automaticamente = True
        item.final_tipo_codigo, item.final_codigo = item.tipo_codigo_sugerido, item.codigo_sugerido
        item.final_cst, item.final_cclasstrib = av.cst, av.cclasstrib
        item.final_dispositivo = item.dispositivo_legal
        item.revisado_por, item.revisado_em = None, datetime.now(UTC)


def versionar_perfil(session: Session, item: AuditItem, audit: Audit, *, registro: dict[str, Any], motivo: str) -> bool:
    """Grava uma nova versão do perfil tributário se o resultado do item mudou. Devolve se mudou."""
    idt = item.identidade or {}
    atual = session.scalar(select(TaxProfile).where(TaxProfile.item_id == item.id, TaxProfile.ativo.is_(True)).limit(1))
    novo = {
        "status": item.status,
        "cclasstrib": item.final_cclasstrib or item.cclasstrib_sugerido,
        "cst": item.final_cst or item.cst_sugerido,
        "hipotese": item.hipotese,
        "imposto_seletivo": item.is_situacao,
        "codigo": item.final_codigo or idt.get("codigo"),
    }
    if atual is not None and all(getattr(atual, k) == v for k, v in novo.items()):
        return False
    snap = session.get(RefSnapshot, audit.snapshot_id) if audit.snapshot_id else None
    versao = (atual.versao + 1) if atual else 1
    if atual is not None:
        session.execute(update(TaxProfile).where(TaxProfile.id == atual.id).values(ativo=False))
    session.add(
        TaxProfile(
            org_id=item.org_id,
            company_id=item.company_id,
            audit_id=item.audit_id,
            item_id=item.id,
            codigo_interno=item.codigo_interno,
            cenario=item.cenario,
            vigencia=audit.data_referencia,
            versao=versao,
            ativo=True,
            status=item.status,
            nivel_revisao=item.nivel_revisao,
            tipo_codigo=item.final_tipo_codigo or idt.get("tipo_codigo"),
            codigo=novo["codigo"],
            cst=novo["cst"],
            cclasstrib=novo["cclasstrib"],
            perc_red_ibs=item.perc_red_ibs,
            perc_red_cbs=item.perc_red_cbs,
            imposto_seletivo=item.is_situacao,
            hipotese=item.hipotese,
            conclusao=item.conclusao,
            confianca_global=item.confianca_global,
            dimensoes=item.dimensoes or {},
            registro={
                **registro,
                "base": {"snapshot": str(snap.id) if snap else None, "versoes": snap.versoes if snap else {}},
            },
            thesis_id=item.thesis_id,
            motivo_versao=motivo[:200],
        )
    )
    item.perfil_versao = versao
    return True


def reavaliar(session: Session, item_id: uuid.UUID, motivo: str) -> bool:
    """Reavalia um item com os fatos atuais, sem IA. Devolve True se reavaliou."""
    item = session.get(AuditItem, item_id)
    if item is None or item.thesis_id is None:
        return False
    if item.revisao_status == StatusRevisao.APROVADO and not item.aprovado_automaticamente:
        return False  # decisão humana prevalece; desfaça a aprovação para reavaliar
    audit = session.get(Audit, item.audit_id)
    tese = session.get(TaxThesis, item.thesis_id)
    if audit is None or tese is None:
        return False
    av = avaliar(entrada(session, item, audit, tese))
    motivos_id = [m for m in item.motivos or [] if m not in av.motivos and m not in _MOTIVOS_DA_AVALIACAO]
    aplicar(session, item, audit, av, tese, motivos_identidade=motivos_id, motivo_versao=motivo)
    return True


_MOTIVOS_DA_AVALIACAO = {
    "FATO_PENDENTE",
    "CONFLITO_NORMATIVO",
    "SEM_HIPOTESE_SUSTENTADA",
    "SUJEITO_A_IMPOSTO_SELETIVO",
    "TESE_NAO_CONCLUIDA",
    "BASE_REFERENCIA_INCOMPLETA",
}
