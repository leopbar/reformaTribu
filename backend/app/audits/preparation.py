"""Preparação de uma auditoria: leitura do arquivo, limpeza, checagem estrutural, prévia e estimativa.

Nada aqui chama a IA.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy import delete, func, insert, or_, select

from app.config import get_settings
from app.db.session import TenantContext, sync_tenant_session
from app.events import bus
from app.ingest import cleaning, estimate
from app.ingest.reader import ArquivoInvalido, ler_planilha
from app.models import ApprovedMemory, Audit, AuditItem, OrgSettings, RefVersion, UploadedFile
from app.models.enums import StatusAuditoria, StatusVersao
from app.storage import files

log = structlog.get_logger()


def _versao_ativa(sess: Any, fonte: str) -> RefVersion | None:
    v: RefVersion | None = sess.scalar(
        select(RefVersion)
        .where(RefVersion.fonte == fonte, RefVersion.status == StatusVersao.ATIVA)
        .order_by(RefVersion.coletado_em.desc())
        .limit(1)
    )
    return v


def preparar_auditoria(audit_id: uuid.UUID, org_id: uuid.UUID) -> None:
    ctx = TenantContext.sistema(org_id)
    with sync_tenant_session(ctx) as sess:
        audit = sess.get(Audit, audit_id)
        if audit is None:
            return
        arquivo = sess.get(UploadedFile, audit.file_id) if audit.file_id else None
        if arquivo is None or arquivo.storage_path is None:
            audit.status, audit.erro = StatusAuditoria.FALHOU, "O arquivo da planilha não está mais disponível."
            return
        caminho, nome, aba, cab = arquivo.storage_path, arquivo.nome_original, arquivo.planilha, arquivo.linha_cabecalho
        mapeamento, data_ref, company_id = audit.mapeamento, audit.data_referencia, audit.company_id
    try:
        planilha = ler_planilha(files.ler(caminho), nome, aba, cab, get_settings().upload_max_linhas)
    except ArquivoInvalido as e:
        with sync_tenant_session(ctx) as sess:
            a = sess.get(Audit, audit_id)
            assert a is not None
            a.status, a.erro = StatusAuditoria.FALHOU, e.mensagem
        bus.publicar(audit_id, "status", {"status": "falhou"})
        return

    itens = cleaning.limpar(planilha.registros(), mapeamento, linha_inicial=planilha.linha_cabecalho + 2)
    with sync_tenant_session(ctx) as sess:
        v_ncm, v_nbs = _versao_ativa(sess, "ncm"), _versao_ativa(sess, "nbs")
        ncm_info: dict[str, dict[str, Any]] = {}
        nbs_info: dict[str, dict[str, Any]] = {}
        if v_ncm is not None:
            codigos = {i.ncm for i in itens if i.ncm and len(i.ncm) == 8}
            codigos |= {i.ncm_candidato_zero for i in itens if i.ncm_candidato_zero}
            ncm_info = cleaning.checar_codigos(sess, "ncm", codigos, v_ncm.id, data_ref)
        if v_nbs is not None:
            nbs_info = cleaning.checar_codigos(
                sess, "nbs", {i.nbs for i in itens if i.nbs and len(i.nbs) == 9}, v_nbs.id, data_ref
            )
        cleaning.aplicar_checagem_estrutural(itens, ncm_info, nbs_info)

        audit = sess.get(Audit, audit_id)
        assert audit is not None
        sess.execute(delete(AuditItem).where(AuditItem.audit_id == audit_id))
        linhas = []
        for it in itens:
            d = it.como_linha_bd()
            d.update(
                id=uuid.uuid4(),
                org_id=org_id,
                audit_id=audit_id,
                company_id=company_id,
                status="pendente",
                revisao_status="pendente",
                motivos=[],
                tentativa=1,
            )
            linhas.append(d)
        for i in range(0, len(linhas), 2000):
            sess.execute(insert(AuditItem), linhas[i : i + 2000])

        resumo = cleaning.resumir_problemas(itens)
        resumo["base_referencia"] = {"ncm": v_ncm is not None, "nbs": v_nbs is not None}
        # Memória aprovada: quantos itens provavelmente dispensam IA.
        hashes = {cleaning.hash_descricao(i.descricao) for i in itens if not i.ignorado}
        gtins = {i.gtin for i in itens if i.gtin}
        conds = [ApprovedMemory.descricao_hash.in_(list(hashes))] if hashes else []
        if gtins:
            conds.append(ApprovedMemory.gtin.in_(list(gtins)))
        na_memoria = 0
        if conds:
            na_memoria = int(
                sess.scalar(
                    select(func.count(func.distinct(ApprovedMemory.descricao_hash))).where(
                        ApprovedMemory.company_id == company_id, ApprovedMemory.ativo.is_(True), or_(*conds)
                    )
                )
                or 0
            )
        resumo["provaveis_da_memoria"] = na_memoria

        cfg = sess.get(OrgSettings, org_id) or OrgSettings(org_id=org_id)
        s = get_settings()
        validos = resumo["itens_validos"]
        limite_lote = cfg.lote_min_itens or s.llm_batch_min_itens
        modelo_p = cfg.modelo_principal or s.llm_model_primary
        modelo_e = cfg.modelo_escalonamento or s.llm_model_escalation
        taxa = estimate.taxa_escalonamento_historica(sess, org_id)
        previsao = estimate.prever_trabalho(
            [i for i in itens if not i.ignorado],
            codigos_validos={
                c for c, info in {**ncm_info, **nbs_info}.items() if info.get("existe") and info.get("vigente")
            },
            na_memoria=na_memoria,
            familias_ja_investigadas=estimate.familias_ja_investigadas(sess, data_ref),
        )
        resumo["previsao_ia"] = previsao
        com_ia, familias = previsao["itens_com_ia"], previsao["familias_novas"]
        extra = {
            "familias": familias,
            "modelo_investigacao": modelo_e,
            "modelo_leve": cfg.modelo_leve or s.llm_model_light,
            "previsao": previsao,
        }
        audit.estimativa = {
            "tempo_real": estimate.estimar(com_ia, modelo_p, modelo_e, taxa, lote=False, **extra),
            "lote": estimate.estimar(com_ia, modelo_p, modelo_e, taxa, lote=True, **extra),
            "modo_recomendado": "lote" if com_ia >= limite_lote else "tempo_real",
        }
        audit.problemas_resumo = resumo
        audit.total_itens = validos
        audit.status = StatusAuditoria.PRONTA
        audit.erro = None
    bus.publicar(audit_id, "status", {"status": "pronta"})
    log.info("auditoria_preparada", auditoria=str(audit_id), itens=len(itens))
