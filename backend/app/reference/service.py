"""Serviço da base de referência: importação versionada, geração/validação de regras e catálogo."""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy import select

from app.config import get_settings
from app.core.audit_trail import Acao, registrar_sync
from app.db.session import TenantContext, sync_reference_admin_session
from app.models import ConditionAttribute, RefVersion
from app.models.enums import FonteReferencia, StatusVersao
from app.reference.importers.cclasstrib import importar_cclasstrib
from app.reference.importers.common import Coleta, FonteIndisponivel, FormatoInvalido, baixar
from app.reference.importers.lc214 import importar_lc214
from app.reference.importers.nomenclatura import importar_nbs, importar_ncm
from app.reference.importers.normas import CATALOGO, ato_por_chave, importar_norma
from app.rules.official import aplicar_regras_geradas, gerar_regras
from app.rules.validation import revalidar_todas
from app.storage import files

log = structlog.get_logger()

IMPORTADORES = {
    FonteReferencia.NCM: importar_ncm,
    FonteReferencia.NBS: importar_nbs,
    FonteReferencia.CCLASSTRIB: importar_cclasstrib,
    FonteReferencia.LC214: importar_lc214,
}

INSTRUCOES_UPLOAD = {
    "ncm": "Portal Único Siscomex → Classificação Fiscal de Mercadorias → Tabela NCM → 'Download da tabela "
    "vigente' em formato JSON (portalunico.siscomex.gov.br/classif).",
    "nbs": "gov.br/mdic → NBS – Nomenclatura Brasileira de Serviços → 'Tabela em CSV da versão 2.0 da NBS'.",
    "cclasstrib": "Portal da Conformidade Fácil (dfe-portal.svrs.rs.gov.br/CFF/ClassificacaoTributaria): salve a "
    "página completa (Ctrl+S, 'somente HTML') ou use 'Exportar para JSON'.",
    "lc214": "planalto.gov.br/ccivil_03/leis/lcp/lcp214.htm: salve a página (Ctrl+S, 'somente HTML').",
}

ATRIBUTOS_BASE = [
    ("adicao_acucar", "item", "Há adição de açúcar ao produto?", "Adição de açúcares ao produto."),
    ("adicao_edulcorante", "item", "Há adição de edulcorantes (adoçantes)?", "Adição de edulcorantes."),
    ("adicao_conservante", "item", "Há adição de conservantes?", "Adição de conservantes."),
    (
        "forma_apresentacao",
        "item",
        "Qual a forma de apresentação (barra, líquido, pó, creme…)?",
        "Estado físico e forma de apresentação do produto.",
    ),
    (
        "destinado_alimentacao_humana",
        "item",
        "O produto é destinado à alimentação humana?",
        "Finalidade de consumo humano.",
    ),
    ("uso_veterinario", "item", "O produto é de uso veterinário?", "Destinação veterinária."),
    (
        "destinatario",
        "operacao",
        "Quem é o destinatário da operação (consumidor final, produtor rural, administração pública…)?",
        "Tipo de destinatário da operação.",
    ),
]


def garantir_catalogo_base() -> None:
    with sync_reference_admin_session(TenantContext(org_id=None, platform_admin=True)) as s:
        existentes = set(s.scalars(select(ConditionAttribute.chave)))
        for chave, fonte, pergunta, desc in ATRIBUTOS_BASE:
            if chave not in existentes:
                s.add(ConditionAttribute(chave=chave, fonte=fonte, pergunta=pergunta, descricao=desc, valores=[]))


def importar_ato(
    chave: str,
    *,
    arquivo_rel: str | None = None,
    nome_arquivo: str | None = None,
    usuario_id: uuid.UUID | None = None,
    usuario_email: str | None = None,
) -> dict[str, Any]:
    """Importa um ato normativo do catálogo (EC 132/2023, LC 227/2026, Decreto 12.955/2026...)."""
    ato = ato_por_chave(chave)
    coleta = Coleta(files.ler(arquivo_rel), None, "upload_manual", nome_arquivo) if arquivo_rel else baixar(ato.url)
    ctx = TenantContext(org_id=None, user_id=usuario_id, platform_admin=True)
    try:
        with sync_reference_admin_session(ctx) as sess:
            versao, criada = importar_norma(sess, coleta, ato, usuario_id, usuario_email)
            registrar_sync(
                sess,
                Acao.REFERENCIA_IMPORTADA,
                org_id=None,
                user_id=usuario_id,
                user_email=usuario_email,
                entidade="ref_version",
                entidade_id=versao.id,
                detalhes={"fonte": "normas", "ato": ato.rotulo, "criada": criada, "url": coleta.url},
            )
            return {
                "versao_id": str(versao.id),
                "criada": criada,
                "fonte": "normas",
                "estatisticas": versao.estatisticas,
            }
    except (FormatoInvalido, FonteIndisponivel) as e:
        raise ValueError(f"{e} Como alternativa, salve a página {ato.url} (Ctrl+S, somente HTML) e envie.") from e


def importar(
    fonte: str,
    *,
    url: str | None = None,
    arquivo_rel: str | None = None,
    nome_arquivo: str | None = None,
    usuario_id: uuid.UUID | None = None,
    usuario_email: str | None = None,
) -> dict[str, Any]:
    """Importa uma fonte (download ou arquivo enviado). Idempotente pelo hash do conteúdo."""
    fonte_enum = FonteReferencia(fonte)
    s = get_settings()
    if arquivo_rel:
        coleta = Coleta(files.ler(arquivo_rel), None, "upload_manual", nome_arquivo)
    else:
        url = (
            url
            or {
                "ncm": s.fonte_ncm_url,
                "nbs": s.fonte_nbs_url,
                "cclasstrib": s.fonte_cclasstrib_url,
                "lc214": s.fonte_lc214_url,
            }[fonte]
        )
        coleta = baixar(url)
    ctx = TenantContext(org_id=None, user_id=usuario_id, platform_admin=True)
    try:
        with sync_reference_admin_session(ctx) as sess:
            versao, criada = IMPORTADORES[fonte_enum](sess, coleta, usuario_id, usuario_email)
            resultado: dict[str, Any] = {
                "versao_id": str(versao.id),
                "criada": criada,
                "fonte": fonte,
                "estatisticas": versao.estatisticas,
            }
            registrar_sync(
                sess,
                Acao.REFERENCIA_IMPORTADA,
                org_id=None,
                user_id=usuario_id,
                user_email=usuario_email,
                entidade="ref_version",
                entidade_id=versao.id,
                detalhes={
                    "fonte": fonte,
                    "criada": criada,
                    "modo": coleta.modo,
                    "url": coleta.url,
                    "sha256": versao.sha256,
                },
            )
    except (FormatoInvalido, FonteIndisponivel) as e:
        raise ValueError(f"{e} Como alternativa, envie o arquivo manualmente: {INSTRUCOES_UPLOAD[fonte]}") from e
    if criada:
        pos_importacao(fonte)
    return resultado


def pos_importacao(fonte: str) -> dict[str, Any]:
    """Regenera regras (pendentes) e revalida tudo após uma nova versão de tabela."""
    garantir_catalogo_base()
    saida: dict[str, Any] = {}
    with sync_reference_admin_session(TenantContext(org_id=None, platform_admin=True)) as sess:
        if fonte in ("cclasstrib", "lc214"):
            try:
                saida["regras"] = aplicar_regras_geradas(sess, gerar_regras(sess))
            except ValueError as e:
                saida["regras"] = {"erro": str(e)}
        saida["validacao"] = revalidar_todas(sess)
    log.info("pos_importacao", fonte=fonte, **{k: str(v) for k, v in saida.items()})
    return saida


def status_base() -> dict[str, Any]:
    with sync_reference_admin_session(TenantContext(org_id=None, platform_admin=True)) as sess:
        saida: dict[str, Any] = {}
        atos = {
            v.rotulo: v
            for v in sess.scalars(
                select(RefVersion).where(RefVersion.fonte == "normas", RefVersion.status == StatusVersao.ATIVA)
            )
        }
        saida["atos_normativos"] = [
            {
                "chave": a.chave,
                "rotulo": a.rotulo,
                "ementa": a.ementa,
                "url": a.url,
                "versao": None
                if a.rotulo not in atos
                else {
                    "id": str(atos[a.rotulo].id),
                    "coletado_em": atos[a.rotulo].coletado_em.isoformat(),
                    "embeddings": atos[a.rotulo].embeddings_status,
                },
            }
            for a in CATALOGO
        ]
        for f in FonteReferencia:
            if f == FonteReferencia.NORMAS:
                continue
            v = sess.scalar(
                select(RefVersion)
                .where(RefVersion.fonte == f.value, RefVersion.status == StatusVersao.ATIVA)
                .order_by(RefVersion.coletado_em.desc())
                .limit(1)
            )
            saida[f.value] = (
                None
                if v is None
                else {
                    "id": str(v.id),
                    "rotulo": v.rotulo,
                    "coletado_em": v.coletado_em.isoformat(),
                    "embeddings": v.embeddings_status,
                }
            )
        return saida
