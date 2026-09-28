"""Contexto de execução do grafo (não é gravado no checkpoint; é reconstruído a cada execução)."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.analise import fatos as fatos_mod
from app.config import get_settings
from app.db.session import TenantContext, sync_tenant_session
from app.models import Abbreviation, Audit, Company, ConditionAttribute, OrgSettings, RefSnapshot
from app.rules.engine import ConjuntoRegras


@dataclass
class Contexto:
    org_id: uuid.UUID
    audit_id: uuid.UUID
    company_id: uuid.UUID
    modo: str
    data_referencia: date
    versoes: dict[str, str | None]
    completude: dict[str, Any]
    regras: ConjuntoRegras
    abreviacoes: dict[str, str]
    catalogo_atributos: dict[str, dict[str, Any]]
    atributos_empresa: dict[str, Any]
    contexto_operacao: dict[str, Any]
    limiar_confirmado: float
    limiar_corrigido: float
    limiar_escalonamento: float
    modelo_principal: str
    modelo_escalonamento: str
    modelo_leve: str
    usar_modelo_leve: bool
    esforco_principal: str
    esforco_escalonamento: str
    is_exige_analise: bool
    snapshot_id: uuid.UUID | None = None
    versoes_normas: list[str] = field(default_factory=list)
    # Dossiê do estabelecimento (valores): entra na chave das teses de família.
    dossie: dict[str, str] = field(default_factory=dict)
    modelo_investigacao: str = ""
    esforco_investigacao: str = "high"
    cenario: str = "venda_consumidor"
    prompts: dict[str, str] = field(default_factory=dict)  # versões de prompt (avaliação de variantes)
    carregado_em: float = field(default_factory=time.monotonic)

    @property
    def tenant(self) -> TenantContext:
        return TenantContext.sistema(self.org_id)

    def versao(self, fonte: str) -> uuid.UUID | None:
        v = self.versoes.get(fonte)
        return uuid.UUID(v) if v else None


_CACHE: dict[uuid.UUID, Contexto] = {}
_TTL_S = 120.0


def carregar_contexto(audit_id: uuid.UUID, org_id: uuid.UUID, forcar: bool = False) -> Contexto:
    c = _CACHE.get(audit_id)
    if c is not None and not forcar and time.monotonic() - c.carregado_em < _TTL_S:
        return c
    s = get_settings()
    with sync_tenant_session(TenantContext.sistema(org_id)) as sess:
        audit = sess.get(Audit, audit_id)
        if audit is None or audit.snapshot_id is None:
            raise ValueError("Auditoria sem snapshot da base de referência.")
        snap = sess.get(RefSnapshot, audit.snapshot_id)
        assert snap is not None
        empresa = sess.get(Company, audit.company_id)
        assert empresa is not None
        cfg = sess.get(OrgSettings, org_id) or OrgSettings(org_id=org_id)
        dossie = fatos_mod.assinatura(fatos_mod.fatos_empresa(sess, empresa))
        abrevs: dict[str, str] = {}
        # Globais primeiro; as da organização sobrescrevem.
        for a in sess.scalars(
            select(Abbreviation).where(Abbreviation.ativo.is_(True)).order_by(Abbreviation.org_id.nulls_first())
        ):
            abrevs[a.abreviacao.lower()] = a.expansao
        catalogo = {
            a.chave: {"fonte": a.fonte, "pergunta": a.pergunta, "descricao": a.descricao, "valores": a.valores}
            for a in sess.scalars(select(ConditionAttribute))
        }
        regras = ConjuntoRegras.carregar(sess, snap.regras_aprovadas, snap.regras_pendentes)
        conf = audit.configuracao or {}
        ctx = Contexto(
            org_id=org_id,
            audit_id=audit_id,
            company_id=audit.company_id,
            modo=audit.modo or "tempo_real",
            data_referencia=audit.data_referencia,
            versoes=snap.versoes,
            completude=snap.completude,
            regras=regras,
            abreviacoes=abrevs,
            catalogo_atributos=catalogo,
            atributos_empresa={
                "regime_tributario": empresa.regime_tributario,
                "uf": empresa.uf,
                "cnae": empresa.cnae,
                **(empresa.atributos or {}),
            },
            contexto_operacao=audit.contexto_operacao or {},
            limiar_confirmado=float(conf.get("limiar_confirmado", cfg.limiar_confirmado or Decimal("0.9"))),
            limiar_corrigido=float(conf.get("limiar_corrigido", cfg.limiar_corrigido or Decimal("0.85"))),
            limiar_escalonamento=float(conf.get("limiar_escalonamento", cfg.limiar_escalonamento or Decimal("0.8"))),
            modelo_principal=conf.get("modelo_principal") or cfg.modelo_principal or s.llm_model_primary,
            modelo_escalonamento=conf.get("modelo_escalonamento") or cfg.modelo_escalonamento or s.llm_model_escalation,
            modelo_leve=cfg.modelo_leve or s.llm_model_light,
            usar_modelo_leve=bool(cfg.usar_modelo_leve),
            esforco_principal=conf.get("esforco_principal") or s.llm_effort_primary,
            esforco_escalonamento=conf.get("esforco_escalonamento") or s.llm_effort_escalation,
            is_exige_analise=bool(conf.get("imposto_seletivo_exige_analise", cfg.imposto_seletivo_exige_analise)),
            prompts=dict(conf.get("prompts") or {}),
            snapshot_id=snap.id,
            versoes_normas=list((snap.completude or {}).get("normas_versoes") or []),
            dossie=dossie,
            modelo_investigacao=conf.get("modelo_investigacao") or cfg.modelo_escalonamento or s.llm_model_escalation,
            esforco_investigacao=conf.get("esforco_investigacao") or s.llm_effort_investigation,
        )
    _CACHE[audit_id] = ctx
    return ctx
