"""Aplicação do resultado do analista a um item: perfil tributário versionado, perguntas agrupadas e
aprovação automática. Também reavalia itens quando um fato novo chega (sem chamar a IA)."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.analise import decisoes as decisoes_mod
from app.analise import fatos as fatos_mod
from app.analise import fatos_padrao, operacao
from app.analise import natureza as natureza_mod
from app.analise.avaliacao import Avaliacao, EntradaAvaliacao, avaliar
from app.core.codes import formatar_codigo
from app.models import Audit, AuditItem, Company, OrgSettings, Pendencia, RefSnapshot, TaxProfile, TaxThesis
from app.models.enums import EscopoFato, OrigemFato, StatusAjusteCadastro, StatusItem, StatusPendencia, StatusRevisao

CAMPOS_PERFIL = ("status", "cclasstrib", "cst", "hipotese", "imposto_seletivo", "codigo")


def grupo_da_pergunta(item: AuditItem, escopo: str, grupo: str = "") -> tuple[str, str, str]:
    """(escopo, grupo_chave, rótulo) da pergunta: o mais amplo possível.

    `grupo` separa perguntas do mesmo atributo com opções diferentes (ex.: "o que é o item?", ADR 0029):
    juntam-se só os itens da mesma categoria com as mesmas opções."""
    if escopo == EscopoFato.EMPRESA:
        return EscopoFato.EMPRESA, "", "Toda a empresa"
    cat = fatos_mod.grupo_categoria(item.categoria)
    if grupo:
        rotulo = f"Categoria “{item.categoria}”" if cat else f"Item {item.codigo_interno}"
        return EscopoFato.GRUPO, f"{cat or 'item:' + item.codigo_interno}|{grupo}"[:250], rotulo
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
    # Regimes decididos pela operação (ADR 0026): ativados pelo dossiê, com a lei e o cClassTrib da base.
    aplic = operacao.regimes_da_empresa(fatos)
    snap = session.get(RefSnapshot, audit.snapshot_id) if audit.snapshot_id else None
    mat = operacao.material(
        session, aplic.regimes, (snap.versoes if snap else None) or {}, audit.data_referencia, idt.get("tipo_codigo")
    )
    # Fatos que a lei presume pelo perfil ou que o código determina; os gravados prevalecem. O catálogo de
    # fatos padronizados também presume e lê o cadastro (ADR 0030): medicamento vendido no varejo é registrado
    # na Anvisa; o que o ERP diz ser medicamento não é dispositivo médico.
    presumidos = {
        f: operacao.registro_implicito(f, v, OrigemFato.ERP if origem == "erp" else OrigemFato.CADASTRO, explicacao)
        for f, (v, origem, explicacao) in fatos_padrao.implicitos(
            item.tipo_informado, {k: str(x.get("valor")) for k, x in fatos.items()}
        ).items()
    }
    fatos = {
        **presumidos,
        **operacao.fatos_implicitos(aplic.regimes, fatos, idt.get("tipo_codigo"), idt.get("codigo")),
        **fatos,
    }
    return EntradaAvaliacao(
        identidade=idt,
        tese=tese.resultado if tese is not None and tese.status == "concluida" else None,
        cclasstrib={**ev.get("cclasstrib", {}), **mat.cclasstrib},
        refs={**ev.get("refs", {}), **mat.refs},
        fatos=fatos,
        correlacionados=ev.get("correlacionados", []),
        precedentes=ev.get("precedentes", []),
        alertas=ev.get("alertas", []),
        sugestoes=(item.estrutura or {}).get("sugestoes_fatos", {}),
        tese_falha=tese_falha or (tese.erro if tese is not None and tese.status != "concluida" else None),
        base_incompleta=base_incompleta,
        is_exige_analise=bool(cfg.imposto_seletivo_exige_analise) if cfg else True,
        tese_aprovada=bool(tese and tese.aprovada_em),
        tratamento_alternativas=(trat := tratamento_alternativas(session, item, audit, fatos)),
        beneficios_em_disputa=beneficios_citados(
            session,
            idt.get("tipo_codigo"),
            [c for c, t in trat.items() if t is None],
            (snap.versoes if snap else None) or {},
        ),
        produtos_na_lei=_produtos_na_lei(session, item, audit),
        operacao=operacao.fundamentar(operacao.hipoteses(aplic.regimes), mat),
        operacao_fatos=operacao.fatos_necessarios(aplic.regimes),
        operacao_afastada=[f"{r.titulo}: {motivo}" for r, motivo in aplic.afastados],
        decisoes=decisoes_mod.carregar(session, item, empresa),
        is_no_anexo_xvii=_no_anexo_xvii(session, idt, (snap.versoes if snap else None) or {}),
    )


def _no_anexo_xvii(session: Session, idt: dict[str, Any], versoes: dict[str, Any]) -> bool | None:
    """O NCM do item é citado por algum item do Anexo XVII (bens do Imposto Seletivo)? None para NBS
    (os serviços do anexo não têm código) ou quando a base da lei não está disponível."""
    from app.analise.evidencias import prefixos

    v_lc = versoes.get("lc214")
    if idt.get("tipo_codigo") != "ncm" or not idt.get("codigo") or not v_lc:
        return None
    total = session.scalar(
        text("SELECT count(*) FROM legal_provisions WHERE version_id = :v AND tipo = 'anexo_item' AND anexo = 'XVII'"),
        {"v": uuid.UUID(str(v_lc))},
    )
    if not total:
        return None  # a lei importada não trouxe o Anexo XVII: não dá para concluir
    citado = session.scalar(
        text(
            "SELECT count(*) FROM legal_provisions WHERE version_id = :v AND tipo = 'anexo_item' AND anexo = 'XVII' "
            "AND codigos_citados && CAST(:p AS varchar[])"
        ),
        {"v": uuid.UUID(str(v_lc)), "p": prefixos(str(idt["codigo"]))},
    )
    return bool(citado)


def _produtos_na_lei(session: Session, item: AuditItem, audit: Audit) -> list[dict[str, Any]]:
    from app.analise.anexos import produtos_citados_com_outro_codigo
    from app.reference.importers.lc214 import romano_para_int

    idt = item.identidade or {}
    snap = session.get(RefSnapshot, audit.snapshot_id) if audit.snapshot_id else None
    versoes = (snap.versoes if snap else None) or {}
    citados = produtos_citados_com_outro_codigo(
        session,
        versoes.get("lc214"),
        item.descricao_normalizada or item.descricao,
        idt.get("tipo_codigo"),
        idt.get("codigo"),
    )
    # O tratamento que cada anexo dá ao produto (ADR 0030): se o item já o tem, o NCM da lei não muda o imposto.
    for p in citados:
        n = romano_para_int(str(p.get("anexo") or ""))
        cods = set(natureza_mod.ANEXOS_SEM_CORRELACAO.get(n, ()))
        if n and versoes.get("cclasstrib"):
            cods |= set(
                session.scalars(
                    text("SELECT codigo FROM cclasstrib_codes WHERE version_id = :v AND nro_anexo = :n"),
                    {"v": uuid.UUID(str(versoes["cclasstrib"])), "n": n},
                )
            )
        p["cclasstrib_do_anexo"] = sorted(cods)
    return citados


def tratamento_alternativas(
    session: Session, item: AuditItem, audit: Audit, fatos: dict[str, dict[str, Any]]
) -> dict[str, str | None]:
    """Para cada código em disputa na identificação (o do ERP, o de cada parecer e as alternativas), o
    tratamento ("cClassTrib|IS") que ele teria; "=" quando a lei e a tabela oficial tratam o código
    exatamente como o escolhido. Sem IA: usa o parecer já existente da família ou a base oficial."""
    idt = item.identidade or {}
    tipo = idt.get("tipo_codigo")
    codigos = idt.get("codigos_em_disputa") or idt.get("codigos_alternativos") or []
    if not tipo or not codigos:
        return {}
    snap = session.get(RefSnapshot, audit.snapshot_id) if audit.snapshot_id else None
    versoes = (snap.versoes if snap else None) or {}
    return {
        cod: tratamento_do_codigo(
            session, tipo, cod, item.cenario, audit.data_referencia, versoes, fatos, codigo_atual=idt.get("codigo")
        )
        for cod in codigos[:6]
    }


MESMO_TRATAMENTO = "="


def _titulo_do_anexo(descricao: str) -> str:
    """Nome curto do anexo, com a redução: "PRODUTOS HORTÍCOLAS, FRUTAS E OVOS SUBMETIDOS À REDUÇÃO DE 100%…"
    vira "Produtos hortícolas, frutas e ovos (redução de 100%)"."""
    texto = " ".join(descricao.split())
    nome = re.split(r"\s+submetid[oa]s?\b", texto, maxsplit=1, flags=re.IGNORECASE)[0].strip(" ,.;")
    reducao = re.search(r"redu[çc][ãa]o\s+(de\s+\d+\s*%|a\s+zero)", texto, flags=re.IGNORECASE)
    return nome.capitalize() + (f" (redução {reducao.group(1).lower()})" if reducao else "")


def beneficios_citados(
    session: Session, tipo: str | None, codigos: list[str], versoes: dict[str, Any]
) -> dict[str, str]:
    """Os anexos da lei que a correlação oficial liga a cada código (ex.: "Anexo XV – produtos hortícolas,
    frutas e ovos"). Explicam ao operador por que a pergunta "o que é este item?" importa quando o imposto
    de uma opção só se sabe depois de investigar."""
    from app.analise.evidencias import prefixos
    from app.reference.importers.lc214 import ROMANOS

    v_cct = versoes.get("cclasstrib")
    if not tipo or not codigos or not v_cct:
        return {}
    saida: dict[str, str] = {}
    for cod in codigos:
        rows = session.execute(
            text(
                "SELECT DISTINCT nro_anexo, descricao_anexo FROM cclasstrib_correlacoes WHERE version_id = :vc "
                "AND codigo_ncm_nbs = ANY(:p) AND upper(coalesce(tipo_permissao, '')) <> 'VEDADO' "
                "AND nro_anexo IS NOT NULL ORDER BY nro_anexo"
            ),
            {"vc": uuid.UUID(str(v_cct)), "p": prefixos(cod)},
        ).all()
        nomes = [
            f"Anexo {ROMANOS[r.nro_anexo - 1] if 0 < r.nro_anexo <= len(ROMANOS) else r.nro_anexo}"
            + (f" – {_titulo_do_anexo(r.descricao_anexo)}" if r.descricao_anexo else "")
            for r in rows
        ]
        if nomes:
            saida[cod] = "; ".join(nomes)
    return saida


def assinatura_juridica(session: Session, tipo: str, codigo: str, versoes: dict[str, Any]) -> tuple[Any, ...] | None:
    """O que a lei e a tabela oficial dizem sobre o código: as linhas da correlação oficial (cClassTrib,
    permissão, condição, exceção), os itens dos anexos que o citam e os benefícios pela natureza do
    produto. Dois códigos com a mesma assinatura recebem o mesmo parecer com os mesmos fatos."""
    from app.analise.evidencias import prefixos
    from app.analise.natureza import ligacoes

    v_cct, v_lc = versoes.get("cclasstrib"), versoes.get("lc214")
    if not v_cct or not v_lc:
        return None
    pref = prefixos(codigo)
    correl = session.execute(
        text(
            "SELECT DISTINCT cclasstrib, upper(coalesce(tipo_permissao, '')), coalesce(descricao_condicao, ''), "
            "coalesce(descricao_excecao, '') FROM cclasstrib_correlacoes WHERE version_id = :vc "
            "AND codigo_ncm_nbs = ANY(:p)"
        ),
        {"vc": uuid.UUID(str(v_cct)), "p": pref},
    ).all()
    anexos = session.scalars(
        text(
            "SELECT id FROM legal_provisions WHERE version_id = :vl AND tipo = 'anexo_item' "
            "AND codigos_citados && CAST(:p AS varchar[])"
        ),
        {"vl": uuid.UUID(str(v_lc)), "p": pref},
    ).all()
    natureza = [str(x) for x in ligacoes(tipo, codigo)]
    return (tuple(sorted(tuple(r) for r in correl)), tuple(sorted(str(a) for a in anexos)), tuple(sorted(natureza)))


def tratamento_do_codigo(
    session: Session,
    tipo: str,
    codigo: str,
    cenario: str,
    data_referencia: Any,
    versoes: dict[str, Any],
    fatos: dict[str, dict[str, Any]],
    *,
    codigo_atual: str | None = None,
) -> str | None:
    from app.analise.avaliacao import escolher
    from app.analise.evidencias import prefixos

    if codigo_atual and codigo_atual != codigo:
        assinatura = assinatura_juridica(session, tipo, codigo, versoes)
        if assinatura is not None and assinatura == assinatura_juridica(session, tipo, codigo_atual, versoes):
            return MESMO_TRATAMENTO
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
    # Um benefício pela natureza do produto (medicamento, in natura, livro…) também impede essa conclusão.
    from app.analise.natureza import ligacoes

    if ligacoes(tipo, codigo):
        return None
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
        escopo, grupo, rotulo = grupo_da_pergunta(item, p.escopo, p.grupo)
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
                    # A resposta anterior valeu só para os itens que estavam na pergunta: um item que
                    # chega agora precisa dela, então a pergunta reabre (ADR 0026).
                    "status": "aberta",
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
    registrar_ajuste_cadastro(item, av.ajuste_cadastro)

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
        item.final_tipo_codigo, item.final_codigo = item.tipo_codigo_sugerido, codigo_para_o_cadastro(item)
        item.final_cst, item.final_cclasstrib = av.cst, av.cclasstrib
        item.final_dispositivo = item.dispositivo_legal
        item.revisado_por, item.revisado_em = None, datetime.now(UTC)


def registrar_ajuste_cadastro(item: AuditItem, ajuste: dict[str, Any]) -> None:
    """Guarda o NCM/NBS a confirmar no cadastro (ADR 0029). Uma decisão já tomada pela pessoa sobre a
    mesma sugestão continua valendo; uma sugestão nova volta a ficar pendente."""
    if not ajuste:
        item.ajuste_cadastro, item.ajuste_cadastro_status = {}, None
        return
    decidido = item.ajuste_cadastro_status in (StatusAjusteCadastro.ACEITO, StatusAjusteCadastro.MANTIDO)
    mesma = (item.ajuste_cadastro or {}).get("sugerido") == ajuste.get("sugerido")
    item.ajuste_cadastro = ajuste
    if not (decidido and mesma):
        item.ajuste_cadastro_status = StatusAjusteCadastro.PENDENTE


def codigo_para_o_cadastro(item: AuditItem) -> str | None:
    """O código que sai na exportação: enquanto a pessoa não aceitar a sugestão, o do ERP (se válido)."""
    ajuste = item.ajuste_cadastro or {}
    if item.ajuste_cadastro_status == StatusAjusteCadastro.ACEITO and ajuste.get("sugerido"):
        return str(ajuste["sugerido"])
    if item.ajuste_cadastro_status in (StatusAjusteCadastro.PENDENTE, StatusAjusteCadastro.MANTIDO) and ajuste.get(
        "erp"
    ):
        return str(ajuste["erp"])
    return item.codigo_sugerido


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
    if item is None or not item.identidade:
        return False
    if item.revisao_status == StatusRevisao.APROVADO and not item.aprovado_automaticamente:
        return False  # decisão humana prevalece; desfaça a aprovação para reavaliar
    audit = session.get(Audit, item.audit_id)
    tese = session.get(TaxThesis, item.thesis_id) if item.thesis_id else None
    if audit is None or (item.thesis_id is not None and tese is None):
        return False
    ent = entrada(session, item, audit, tese)
    if tese is None and not ent.operacao:
        return False  # sem tese e sem regime da operação não há o que reavaliar sem IA
    av = avaliar(ent)
    motivos_id = [m for m in item.motivos or [] if m not in av.motivos and m not in MOTIVOS_DA_AVALIACAO]
    aplicar(session, item, audit, av, tese, motivos_identidade=motivos_id, motivo_versao=motivo)
    return True


def tese_para_reaplicar(
    session: Session, item: AuditItem, audit: Audit, idt: dict[str, Any], *, aceitar_atual: bool = False
) -> tuple[TaxThesis | None, bool]:
    """(tese, precisa de reanálise) para refazer a avaliação sem IA.

    Vale a tese com que o item foi analisado: os fatos do item foram levantados para ela. Se ela foi refeita
    ("Refazer pareceres"), a nova pode pedir outros fatos: o item precisa de reanálise. Item analisado sem
    tese (a investigação falhou): a concluída mais recente da família com o MESMO dossiê da empresa, nunca
    a de outro dossiê (a tese depende de quem vende); sem ela, reanálise."""
    propria = session.get(TaxThesis, item.thesis_id) if item.thesis_id else None
    if propria is not None and (propria.status == "concluida" or not aceitar_atual):
        return (propria, False) if propria.status == "concluida" else (None, True)
    if not idt.get("codigo"):
        return None, False
    empresa = session.get(Company, item.company_id)
    if empresa is None:
        return None, True
    dossie = fatos_mod.assinatura(fatos_mod.fatos_empresa(session, empresa))
    for t in session.scalars(
        select(TaxThesis)
        .where(
            TaxThesis.status == "concluida",
            TaxThesis.tipo_codigo == idt.get("tipo_codigo"),
            TaxThesis.codigo == idt["codigo"],
            TaxThesis.cenario == item.cenario,
            TaxThesis.data_referencia == audit.data_referencia,
        )
        .order_by(TaxThesis.created_at.desc())
    ):
        if (t.fatos_empresa or {}) == dossie:
            return t, False
    return None, True


REAPLICADO, MANTIDO, REANALISAR = "reaplicado", "mantido", "reanalisar"


def reaplicar_item(session: Session, item: AuditItem, motivo: str = "regras atuais reaplicadas (sem IA)") -> str:
    """Refaz a identidade e a avaliação do item com as regras atuais, a partir das respostas da IA já
    gravadas (ADR 0029). Não chama a IA. Devolve "reaplicado", "mantido" ou "reanalisar".

    Item aprovado por uma pessoa: a decisão dela nunca muda. A análise mostrada (status, dimensões, Imposto
    Seletivo) só é atualizada quando as regras atuais chegam ao mesmo resultado que a pessoa aprovou."""
    from app.pipeline import analista

    if item.ignorado or not item.identidade or item.status not in STATUS_REVISAVEIS_ITEM:
        return MANTIDO
    if item.revisao_status == StatusRevisao.REJEITADO:
        return MANTIDO
    humano = item.revisao_status == StatusRevisao.APROVADO and not item.aprovado_automaticamente
    audit = session.get(Audit, item.audit_id)
    if audit is None:
        return MANTIDO
    state = analista.estado_do_registro(session, item)
    idt = analista.identidade(state)
    # Aprovado por pessoa: vale também a tese atual da família (mesmo dossiê), porque só se atualiza a análise
    # quando ela chega ao mesmo resultado que a pessoa aprovou.
    tese, reanalisar = tese_para_reaplicar(session, item, audit, idt, aceitar_atual=humano)
    if reanalisar:
        return MANTIDO if humano else REANALISAR
    anterior = item.identidade
    item.identidade = idt
    ent = entrada(session, item, audit, tese, tese_falha=state.tese_falha, base_incompleta=state.base_incompleta)
    av = avaliar(ent)
    if humano and not (
        av.status == StatusItem.CLASSIFICADO
        and av.cclasstrib == item.final_cclasstrib
        and idt.get("codigo") == item.final_codigo
        and not av.ajuste_cadastro
        and not av.perguntas
    ):
        item.identidade = anterior  # as regras atuais não chegam ao que a pessoa aprovou: nada muda
        return MANTIDO
    motivos_id = [m for m in item.motivos or [] if m not in av.motivos and m not in MOTIVOS_DA_AVALIACAO]
    aplicar(session, item, audit, av, tese, motivos_identidade=motivos_id, motivo_versao=motivo)
    return REAPLICADO


STATUS_REVISAVEIS_ITEM = (
    StatusItem.CLASSIFICADO,
    StatusItem.AGUARDANDO_INFORMACAO,
    StatusItem.REVISAO_CONTADOR,
    StatusItem.REVISAO_ESPECIALISTA,
)


MOTIVOS_DA_AVALIACAO = {
    "FATO_PENDENTE",
    "CONFLITO_NORMATIVO",
    "SEM_HIPOTESE_SUSTENTADA",
    "SUJEITO_A_IMPOSTO_SELETIVO",
    "TESE_NAO_CONCLUIDA",
    "BASE_REFERENCIA_INCOMPLETA",
    "PRODUTO_CITADO_NA_LEI",
    "DECISAO_ANTERIOR_DIVERGENTE",
}
