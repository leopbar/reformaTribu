"""Pipeline completo (LangGraph + PostgreSQL + motor de regras) com dublês da API do Claude e dos
embeddings. Os códigos e regras aqui são FIXTURES de teste, não a base legal."""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import func, select

pytestmark = pytest.mark.usefixtures("limpo")

NCM = {
    "34": "Sabões, agentes orgânicos de superfície, preparações para lavagem",
    "3401": "Sabões; produtos orgânicos tensoativos usados como sabão, em barras, pães ou pedaços",
    "340111": "De toucador (incluindo os de uso medicinal)",
    "34011190": "Sabões de toucador em barras, outros",
    "34013000": "Produtos e preparações orgânicos tensoativos para lavagem da pele, na forma de líquido ou de creme",
    "20": "Preparações de produtos hortícolas, de frutas",
    "2009": "Sucos (sumos) de frutas",
    "200961": "Suco de uva, com valor Brix não superior a 30",
    "20096100": "Suco de uva, outros",
    "22": "Bebidas, líquidos alcoólicos e vinagres",
    "22021000": "Águas, incluindo as águas minerais, adicionadas de açúcar, refrigerantes",
}


class FakeMensagem:
    def __init__(self, dados: dict[str, Any]) -> None:
        self._d = dados
        self._request_id = "req_teste"

    def to_dict(self) -> dict[str, Any]:
        return self._d


class FakeClaude:
    """Responde como o modelo responderia, a partir da descrição do item. Conta as chamadas."""

    def __init__(self) -> None:
        self.chamadas: list[str] = []
        self.messages = self

    def create(self, **params: Any) -> FakeMensagem:
        conteudo = json.loads(params["messages"][0]["content"])
        desc = conteudo["item"]["descricao_original"]
        candidatos = [c["codigo"] for c in conteudo["candidatos"]]
        self.chamadas.append(desc)
        escalonamento = "analise_anterior" in conteudo
        base = {
            "tipo_item": "produto",
            "descricao_suficiente": True,
            "sinais_de_duvida": [],
            "justificativa": "teste",
            "codigo_escolhido_da_lista": True,
            "nenhum_candidato_serve": False,
            "atributos_extraidos": {
                "forma_apresentacao": "desconhecido",
                "adicao_acucar": "desconhecido",
                "outros": [],
            },
        }
        if "LIQ" in desc:
            r = {**base, "ncm_atual_coerente": False, "codigo_sugerido": "34013000", "confianca": 0.94}
            r["atributos_extraidos"]["forma_apresentacao"] = "liquido"
        elif "BARRA" in desc:
            r = {**base, "ncm_atual_coerente": True, "codigo_sugerido": "34011190", "confianca": 0.97}
        elif "SUCO" in desc:
            r = {**base, "ncm_atual_coerente": True, "codigo_sugerido": "20096100", "confianca": 0.96}
        else:  # sugere um código fora da lista: deve ser descartado
            r = {**base, "ncm_atual_coerente": False, "codigo_sugerido": "99999999", "confianca": 0.99}
        assert r["codigo_sugerido"] in candidatos or r["codigo_sugerido"] == "99999999"
        if escalonamento:
            r["concorda_com_analise_anterior"] = True
        return FakeMensagem(
            {
                "content": [{"type": "text", "text": json.dumps(r)}],
                "stop_reason": "end_turn",
                "model": params["model"],
                "usage": {
                    "input_tokens": 1200,
                    "output_tokens": 300,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 900,
                },
            }
        )


def vetor(texto: str, dim: int) -> list[float]:
    h = hashlib.sha256(texto.lower().encode()).digest()
    v = [((h[i % len(h)] / 255.0) - 0.5) for i in range(dim)]
    n = sum(x * x for x in v) ** 0.5
    return [x / n for x in v]


@pytest.fixture
def ambiente(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    from app.config import get_settings
    from app.db.session import TenantContext, sync_reference_admin_session, sync_tenant_session
    from app.embeddings import client as emb
    from app.llm import gateway
    from app.models import (
        Audit,
        AuditItem,
        CClassTribCode,
        Company,
        LegalRule,
        NcmNode,
        Organization,
        OrgSettings,
        RefVersion,
    )
    from app.reference.importers.nomenclatura import No, montar_hierarquia
    from app.reference.snapshot import criar_ou_obter
    from app.rules.official import sincronizar_codigos

    dim = get_settings().embeddings_dim
    fake = FakeClaude()
    gateway.cliente.cache_clear()
    monkeypatch.setattr(gateway, "cliente", lambda: fake)
    monkeypatch.setattr(emb, "embed", lambda textos, tentativas=4, tipo="consulta": [vetor(t, dim) for t in textos])

    agora = datetime.now(UTC)
    ref = TenantContext(org_id=None, platform_admin=True)
    with sync_reference_admin_session(ref) as s:
        v_ncm = RefVersion(
            fonte="ncm",
            rotulo="teste",
            modo_coleta="upload_manual",
            coletado_em=agora,
            sha256="a" * 64,
            arquivo_path="x",
            status="ativa",
            embeddings_status="concluido",
            estatisticas={},
            avisos=[],
        )
        v_cct = RefVersion(
            fonte="cclasstrib",
            rotulo="teste",
            modo_coleta="upload_manual",
            coletado_em=agora,
            sha256="b" * 64,
            arquivo_path="x",
            status="ativa",
            estatisticas={},
            avisos=[],
        )
        s.add_all([v_ncm, v_cct])
        s.flush()
        for linha in montar_hierarquia([No(c, d) for c, d in NCM.items()], (2, 4, 5, 6, 7), 8):
            s.add(
                NcmNode(
                    version_id=v_ncm.id,
                    codigo_formatado=linha["codigo"],
                    nivel="x",
                    embedding=vetor(linha["descricao_completa"], dim) if linha["folha"] else None,
                    **linha,
                )
            )
        for cod, cst, nome in (
            ("000001", "000", "Tributação integral"),
            ("200035", "200", "Higiene Anexo VIII"),
            ("200034", "200", "Alimentos Anexo VII"),
        ):
            s.add(CClassTribCode(version_id=v_cct.id, codigo=cod, cst=cst, nome=nome, indicadores={}))
        regras = [
            LegalRule(
                slug="padrao",
                descricao_legal="Tributação integral",
                dispositivo_legal="LC 214/2025, art. 4",
                tipo_tratamento="tributacao_integral",
                tipo_codigo=None,
                abrangencia={"universal": True, "codigos": []},
                cst_ibs_cbs="000",
                cclasstrib="000001",
                status="aprovada",
                origem="manual",
                prioridade=1000,
            ),
            LegalRule(
                slug="sabonete-barra",
                anexo="VIII",
                item="1",
                descricao_legal="Sabões de toucador 3401.11.90",
                dispositivo_legal="LC 214/2025, art. 136, Anexo VIII, item 1",
                tipo_tratamento="reducao_60",
                tipo_codigo="ncm",
                abrangencia={"codigos": [{"codigo": "34011190", "nivel": "item"}]},
                cst_ibs_cbs="200",
                cclasstrib="200035",
                status="aprovada",
                origem="manual",
            ),
            LegalRule(
                slug="suco-sem-acucar",
                anexo="VII",
                item="9",
                descricao_legal="Sucos sem adição de açúcar",
                dispositivo_legal="LC 214/2025, Anexo VII",
                tipo_tratamento="reducao_60",
                tipo_codigo="ncm",
                abrangencia={"codigos": [{"codigo": "200961", "nivel": "subposicao"}]},
                condicoes=[
                    {
                        "atributo": "adicao_acucar",
                        "fonte": "item",
                        "deve_ser": "nao",
                        "pergunta": "O suco tem adição de açúcar?",
                    }
                ],
                cst_ibs_cbs="200",
                cclasstrib="200034",
                status="aprovada",
                origem="manual",
            ),
        ]
        s.add_all(regras)
        s.flush()
        for r in regras:
            sincronizar_codigos(s, r)

    org_id, emp_id = uuid.uuid4(), uuid.uuid4()
    with sync_tenant_session(TenantContext(org_id=org_id, platform_admin=True)) as s:
        s.add(Organization(id=org_id, nome="Org teste", tipo="empresa"))
        s.flush()
        s.add(OrgSettings(org_id=org_id, orcamento_mensal_usd=Decimal("100")))
        s.add(
            Company(
                id=emp_id,
                org_id=org_id,
                razao_social="Mercado Teste",
                cnpj="11222333000181",
                regime_tributario="lucro_real",
                uf="SP",
                atributos={},
            )
        )

    async def _snap() -> uuid.UUID:
        from app.db.session import tenant_session

        async with tenant_session(TenantContext(org_id=org_id)) as s:
            return (await criar_ou_obter(s)).id

    snap_id = asyncio.run(_snap())

    def nova_auditoria(itens: list[tuple[str, str]], modo: str = "tempo_real") -> tuple[uuid.UUID, list[uuid.UUID]]:
        aid = uuid.uuid4()
        ids = []
        with sync_tenant_session(TenantContext.sistema(org_id)) as s:
            s.add(
                Audit(
                    id=aid,
                    org_id=org_id,
                    company_id=emp_id,
                    nome="t",
                    mapeamento={},
                    status="processando",
                    modo=modo,
                    data_referencia=date(2026, 9, 26),
                    snapshot_id=snap_id,
                    contexto_operacao={},
                    configuracao={},
                )
            )
            s.flush()
            for n, (desc, ncm) in enumerate(itens, start=2):
                i = AuditItem(
                    org_id=org_id,
                    audit_id=aid,
                    company_id=emp_id,
                    linha=n,
                    codigo_interno=f"C{n}",
                    descricao=desc,
                    ncm=ncm,
                    ncm_informado=ncm,
                    tipo="produto",
                    problemas=[],
                    status="pendente",
                    motivos=[],
                    revisao_status="pendente",
                )
                s.add(i)
                s.flush()
                ids.append(i.id)
        return aid, ids

    return {"org_id": org_id, "fake": fake, "nova_auditoria": nova_auditoria}


def _item(org_id: uuid.UUID, item_id: uuid.UUID) -> Any:
    from app.db.session import TenantContext, sync_tenant_session
    from app.models import AuditItem

    with sync_tenant_session(TenantContext.sistema(org_id)) as s:
        return s.get(AuditItem, item_id)


def test_fluxo_completo_tempo_real(ambiente: dict[str, Any]) -> None:
    from app.audits.processing import processar_itens
    from app.db.session import TenantContext, sync_tenant_session
    from app.models import Audit, ItemCandidate, LlmCall

    org = ambiente["org_id"]
    aid, (barra, liq, suco, invalido) = ambiente["nova_auditoria"](
        [
            ("SAB BARRA ERVA DOCE 90G", "34011190"),
            ("SAB LIQ ERVA DOCE 250ML", "34011190"),
            ("SUCO UVA 1L", "20096100"),
            ("PRODUTO MISTERIOSO", "22021000"),
        ]
    )
    processar_itens(aid, org, [barra, liq, suco, invalido])

    b = _item(org, barra)
    assert b.status == "confirmado", b.motivos
    assert (b.codigo_sugerido, b.cclasstrib_sugerido) == ("34011190", "200035")
    assert b.dispositivo_legal.endswith("Anexo VIII, item 1")

    lq = _item(org, liq)
    assert lq.status == "corrigido", lq.motivos
    assert lq.codigo_sugerido == "34013000"
    assert lq.cclasstrib_sugerido == "000001"  # sabonete líquido não está no Anexo VIII
    assert "NCM_INCOERENTE_COM_DESCRICAO" in lq.motivos
    assert lq.escalonamento.get("concorda_com_analise_anterior") is True

    s_ = _item(org, suco)
    assert s_.status == "analise_humana"
    assert "CONDICAO_LEGAL_NAO_VERIFICAVEL" in s_.motivos
    assert s_.perguntas[0]["pergunta"] == "O suco tem adição de açúcar?"

    inv = _item(org, invalido)
    assert inv.status == "analise_humana"
    assert "CODIGO_SUGERIDO_INVALIDO" in inv.motivos

    with sync_tenant_session(TenantContext.sistema(org)) as s:
        assert s.get(Audit, aid).status == "concluida"
        assert s.scalar(select(func.count()).select_from(ItemCandidate).where(ItemCandidate.item_id == barra)) > 0
        calls = list(s.scalars(select(LlmCall).where(LlmCall.audit_id == aid)))
        assert all(c.custo_usd > 0 and c.prompt_versao.startswith(("julgar_coerencia@", "escalar@")) for c in calls)
        assert s.get(Audit, aid).custo_usd > 0


def test_memoria_aprovada_dispensa_ia_e_revisao_recalcula(ambiente: dict[str, Any]) -> None:
    from app.audits.processing import processar_itens
    from app.db.session import TenantContext, sync_tenant_session
    from app.review import service

    org, fake = ambiente["org_id"], ambiente["fake"]
    aid, (suco,) = ambiente["nova_auditoria"]([("SUCO UVA 1L", "20096100")])
    processar_itens(aid, org, [suco])
    revisor = service.Revisor(user_id=uuid.uuid4(), email="revisor@teste.com.br")
    from app.core.errors import Conflito

    with sync_tenant_session(TenantContext.sistema(org)) as s, pytest.raises(Conflito):
        service.aprovar(s, suco, revisor)  # pergunta pendente impede aprovação
    with sync_tenant_session(TenantContext.sistema(org)) as s:
        item = service.editar(s, suco, revisor, respostas={"adicao_acucar": "nao"}, aprovar_em_seguida=True)
        assert item.final_cclasstrib == "200034"
        assert item.revisao_status == "aprovado"

    chamadas_antes = len(fake.chamadas)
    aid2, (suco2,) = ambiente["nova_auditoria"]([("SUCO UVA 1L", "20096100")])
    processar_itens(aid2, org, [suco2])
    s2 = _item(org, suco2)
    assert s2.origem == "memoria_aprovada"
    assert s2.status == "confirmado" and s2.cclasstrib_sugerido == "200034"
    assert len(fake.chamadas) == chamadas_antes  # nenhuma chamada de IA

    with sync_tenant_session(TenantContext.sistema(org)) as s:
        service.desfazer(s, suco, revisor)
    assert _item(org, suco).revisao_status == "pendente"


def test_modo_lote_interrompe_e_retoma_sem_cobrar_duas_vezes(ambiente: dict[str, Any]) -> None:
    from app.audits.processing import processar_itens
    from app.db.session import TenantContext, sync_tenant_session
    from app.llm.gateway import registrar_resposta
    from app.models import LlmCall

    org, fake = ambiente["org_id"], ambiente["fake"]
    aid, (barra,) = ambiente["nova_auditoria"]([("SAB BARRA ERVA DOCE 90G", "34011190")], modo="lote")
    processar_itens(aid, org, [barra])
    assert _item(org, barra).etapa == "aguardando_lote"
    with sync_tenant_session(TenantContext.sistema(org)) as s:
        call = s.scalar(select(LlmCall).where(LlmCall.item_id == barra))
        assert call.status == "na_fila" and call.modo == "lote"
        # Simula o resultado devolvido pela Message Batches API.
        resp = fake.create(**call.requisicao["params"]).to_dict()
        registrar_resposta(call, resp, lote=True)
        call.status = "concluida"
    chamadas = len(fake.chamadas)
    processar_itens(aid, org, [barra])  # retomada a partir do checkpoint
    assert _item(org, barra).status == "confirmado"
    processar_itens(aid, org, [barra])  # reprocessar o mesmo bloco não refaz nada
    assert len(fake.chamadas) == chamadas
    with sync_tenant_session(TenantContext.sistema(org)) as s:
        assert s.scalar(select(func.count()).select_from(LlmCall).where(LlmCall.item_id == barra)) == 1


class QuedaSimulada(BaseException):
    """Simula a morte do processo do worker (não é tratada como erro do item)."""


def test_retoma_apos_queda_do_worker_sem_repetir_chamada(
    ambiente: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.audits.processing import processar_itens
    from app.pipeline import graph, nodes

    org, fake = ambiente["org_id"], ambiente["fake"]
    aid, (liq,) = ambiente["nova_auditoria"]([("SAB LIQ ERVA DOCE 250ML", "34011190")])
    original = nodes.enquadrar
    estado = {"caiu": False}

    def quebra(state, runtime):  # type: ignore[no-untyped-def]
        if not estado["caiu"]:
            estado["caiu"] = True
            raise QuedaSimulada()
        return original(state, runtime)

    monkeypatch.setattr(nodes, "enquadrar", quebra)
    graph.grafo.cache_clear()
    with pytest.raises(QuedaSimulada):
        processar_itens(aid, org, [liq])
    assert _item(org, liq).status == "processando"
    chamadas = len(fake.chamadas)  # julgamento + escalonamento já feitos antes da queda
    assert chamadas == 2

    # A tarefa é reentregue (acks_late) ou recuperada: o grafo retoma do checkpoint.
    processar_itens(aid, org, [liq])
    graph.grafo.cache_clear()
    assert _item(org, liq).status == "corrigido"
    assert len(fake.chamadas) == chamadas  # nenhuma chamada repetida
