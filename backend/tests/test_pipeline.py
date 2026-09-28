"""Analista completo (LangGraph + PostgreSQL + investigação por família) com dublês da API do Claude e
dos embeddings. Os códigos, trechos e cClassTrib aqui são FIXTURES de teste, não a base legal."""

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


def _ref(conteudo: dict[str, Any], prefixo: str) -> str:
    for t in conteudo.get("trechos_normativos", []):
        if prefixo in (t.get("local") or ""):
            return str(t["ref"])
    return "P999"  # referência inexistente: o fundamento seria descartado


class FakeClaude:
    """Responde como o modelo responderia a cada tipo de pedido. Conta as chamadas por tipo."""

    def __init__(self) -> None:
        self.chamadas: list[str] = []
        self.messages = self

    def create(self, **params: Any) -> FakeMensagem:
        conteudo = json.loads(params["messages"][0]["content"])
        if "cclasstrib_candidatos" in conteudo:
            r = self._investigar(conteudo)
            self.chamadas.append("investigar:" + conteudo["codigo"]["codigo"])
        elif "fatos_pedidos" in conteudo:
            r = self._fatos(conteudo)
            self.chamadas.append("fatos:" + conteudo["item"]["descricao_original"])
        else:
            r = self._julgar(conteudo)
            self.chamadas.append(("escalar:" if "analise_anterior" in conteudo else "julgar:") + r["_desc"])
            del r["_desc"]
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

    def _julgar(self, conteudo: dict[str, Any]) -> dict[str, Any]:
        desc = conteudo["item"]["descricao_original"]
        candidatos = [c["codigo"] for c in conteudo["candidatos"]]
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
        elif "BARRA" in desc:
            r = {**base, "ncm_atual_coerente": True, "codigo_sugerido": "34011190", "confianca": 0.97}
        elif "SUCO" in desc:
            r = {**base, "ncm_atual_coerente": True, "codigo_sugerido": "20096100", "confianca": 0.96}
        else:  # sugere um código fora da lista: deve ser descartado
            r = {**base, "ncm_atual_coerente": False, "codigo_sugerido": "99999999", "confianca": 0.99}
        assert r["codigo_sugerido"] in candidatos or r["codigo_sugerido"] == "99999999"
        if "analise_anterior" in conteudo:
            r["concorda_com_analise_anterior"] = True
        return {**r, "_desc": desc}

    def _investigar(self, c: dict[str, Any]) -> dict[str, Any]:
        codigo = c["codigo"]["codigo"]
        geral = {
            "id": "HG",
            "titulo": "Tributação integral",
            "tipo": "regra_geral",
            "cclasstrib": "000001",
            "condicoes": [],
            "excecoes": [],
            "fundamentos": [{"ref": "T000001", "trecho": "regra geral"}],
            "explicacao": "Sem benefício aplicável.",
        }
        hipoteses: list[dict[str, Any]] = [geral]
        fatos: list[dict[str, Any]] = []
        if codigo == "34011190":
            hipoteses = [
                {
                    "id": "H1",
                    "titulo": "Anexo VIII — higiene pessoal (redução de 60%)",
                    "tipo": "beneficio",
                    "cclasstrib": "200035",
                    "condicoes": [],
                    "excecoes": [],
                    "fundamentos": [{"ref": _ref(c, "Anexo VIII"), "trecho": "sabões de toucador"}],
                    "explicacao": "Sabonete em barra consta do Anexo VIII.",
                },
                geral,
            ]
        elif codigo == "20096100":
            hipoteses = [
                {
                    "id": "H1",
                    "titulo": "Anexo VII — suco sem açúcar (redução de 60%)",
                    "tipo": "beneficio",
                    "cclasstrib": "200034",
                    "condicoes": [{"fato": "adicao_acucar", "valor_exigido": "nao", "explicacao": "sem açúcar"}],
                    "excecoes": [],
                    "fundamentos": [{"ref": _ref(c, "Anexo VII"), "trecho": "sucos sem adição de açúcar"}],
                    "explicacao": "Sucos naturais sem açúcar estão no Anexo VII.",
                },
                geral,
            ]
            fatos = [
                {
                    "fato": "adicao_acucar",
                    "escopo": "item",
                    "pergunta": "O suco tem adição de açúcar?",
                    "opcoes": ["sim", "nao"],
                    "como_identificar_na_descricao": "INTEGRAL indica sem açúcar",
                }
            ]
        return {
            "entendimento": c["codigo"]["descricao_oficial"],
            "hipoteses": hipoteses,
            "fatos_necessarios": fatos,
            "imposto_seletivo": {"situacao": "nao_sujeito", "condicoes": [], "fundamentos": [], "explicacao": ""},
            "conflitos": [],
            "observacoes": "",
        }

    def _fatos(self, c: dict[str, Any]) -> dict[str, Any]:
        desc = c["item"]["descricao_original"]
        saida = []
        for f in c["fatos_pedidos"]:
            if "INTEGRAL" in desc:
                saida.append({"fato": f["fato"], "valor": "nao", "base": "explicito", "evidencia": "INTEGRAL"})
            else:
                saida.append({"fato": f["fato"], "valor": "nao", "base": "inferencia", "evidencia": "suco comum"})
        return {"fatos": saida}


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
        CClassTribCorrelacao,
        Company,
        LegalProvision,
        NcmNode,
        Organization,
        OrgSettings,
        RefVersion,
    )
    from app.reference.importers.nomenclatura import No, montar_hierarquia
    from app.reference.snapshot import criar_ou_obter

    dim = get_settings().embeddings_dim
    fake = FakeClaude()
    gateway.cliente.cache_clear()
    monkeypatch.setattr(gateway, "cliente", lambda: fake)
    monkeypatch.setattr(emb, "embed", lambda textos, tentativas=4, tipo="consulta": [vetor(t, dim) for t in textos])

    agora = datetime.now(UTC)
    ref = TenantContext(org_id=None, platform_admin=True)

    def versao(fonte: str, letra: str) -> RefVersion:
        return RefVersion(
            fonte=fonte,
            rotulo="teste",
            modo_coleta="upload_manual",
            coletado_em=agora,
            sha256=letra * 64,
            arquivo_path="x",
            status="ativa",
            embeddings_status="concluido",
            estatisticas={},
            avisos=[],
        )

    with sync_reference_admin_session(ref) as s:
        v_ncm, v_cct, v_lc = versao("ncm", "a"), versao("cclasstrib", "b"), versao("lc214", "c")
        s.add_all([v_ncm, v_cct, v_lc])
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
        for cod, cst, nome, anexo in (
            ("000001", "000", "Situações tributadas integralmente pelo IBS e CBS.", None),
            ("200035", "200", "Fornecimento dos produtos de higiene pessoal do Anexo VIII", 8),
            ("200034", "200", "Fornecimento dos alimentos do Anexo VII", 7),
        ):
            s.add(
                CClassTribCode(
                    version_id=v_cct.id, codigo=cod, cst=cst, nome=nome, nro_anexo=anexo, ind_nfce=True, indicadores={}
                )
            )
        s.add_all(
            [
                CClassTribCorrelacao(
                    version_id=v_cct.id, cclasstrib="200035", nro_anexo=8, codigo_ncm_nbs="34011190", tipo_codigo="ncm"
                ),
                CClassTribCorrelacao(
                    version_id=v_cct.id,
                    cclasstrib="200034",
                    nro_anexo=7,
                    codigo_ncm_nbs="200961",
                    tipo_codigo="ncm",
                    descricao_condicao="sem adição de açúcar",
                ),
            ]
        )
        s.add_all(
            [
                LegalProvision(
                    version_id=v_lc.id,
                    tipo="anexo_item",
                    anexo="VIII",
                    item="1",
                    titulo_anexo="PRODUTOS DE HIGIENE PESSOAL",
                    texto="Sabões de toucador 3401.11.90",
                    codigos_citados=["34011190"],
                ),
                LegalProvision(
                    version_id=v_lc.id,
                    tipo="anexo_item",
                    anexo="VII",
                    item="9",
                    titulo_anexo="ALIMENTOS",
                    texto="Sucos naturais de fruta sem adição de açúcar 2009",
                    codigos_citados=["2009"],
                ),
                LegalProvision(
                    version_id=v_lc.id,
                    tipo="artigo",
                    artigo="4",
                    texto="Art. 4º O IBS e a CBS incidem sobre operações onerosas com bens ou com serviços.",
                    codigos_citados=[],
                ),
            ]
        )

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
                segmento="supermercado",
                atributos={},
            )
        )

    async def _snap() -> uuid.UUID:
        from app.db.session import tenant_session

        async with tenant_session(TenantContext(org_id=org_id)) as s:
            return (await criar_ou_obter(s)).id

    snap_id = asyncio.run(_snap())

    def nova_auditoria(
        itens: list[tuple[str, str]], modo: str = "tempo_real", marcas: list[str] | None = None
    ) -> tuple[uuid.UUID, list[uuid.UUID]]:
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
                    data_referencia=date(2027, 1, 1),
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
                    codigo_interno=f"C{desc[:12]}{n}",
                    marca=(marcas or [None] * len(itens))[n - 2],
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

    return {"org_id": org_id, "emp_id": emp_id, "fake": fake, "nova_auditoria": nova_auditoria}


def _item(org_id: uuid.UUID, item_id: uuid.UUID) -> Any:
    from app.db.session import TenantContext, sync_tenant_session
    from app.models import AuditItem

    with sync_tenant_session(TenantContext.sistema(org_id)) as s:
        return s.get(AuditItem, item_id)


def test_analista_completo_tempo_real(ambiente: dict[str, Any]) -> None:
    from app.analise import pendencias
    from app.analise.aplicacao import reavaliar
    from app.audits.processing import processar_itens
    from app.db.session import TenantContext, sync_tenant_session
    from app.models import Audit, CompanyFact, Pendencia, TaxProfile, TaxThesis

    org, fake = ambiente["org_id"], ambiente["fake"]
    aid, (barra, liq, suco, integral, invalido) = ambiente["nova_auditoria"](
        [
            ("SAB BARRA ERVA DOCE 90G", "34011190"),
            ("SAB LIQ ERVA DOCE 250ML", "34011190"),
            ("SUCO UVA 1L", "20096100"),
            ("SUCO UVA INTEGRAL 1L", "20096100"),
            ("PRODUTO MISTERIOSO", "22021000"),
        ]
    )
    processar_itens(aid, org, [barra, liq, suco, integral, invalido])

    # Sabonete em barra: benefício do Anexo VIII, fundamentado, confiança alta e aprovado automaticamente.
    b = _item(org, barra)
    assert b.status == "classificado", (b.motivos, b.dimensoes)
    assert (b.cclasstrib_sugerido, b.cst_sugerido, b.confianca_global) == ("200035", "200", "alta")
    assert b.revisao_status == "aprovado" and b.aprovado_automaticamente
    assert "Anexo VIII" in b.dispositivo_legal
    assert b.identidade["situacao"] == "confirmado"

    # Sabonete líquido: código corrigido (dois pareceres concordam) e regra geral.
    lq = _item(org, liq)
    assert lq.status == "classificado", lq.dimensoes
    assert lq.identidade["situacao"] == "corrigido" and lq.codigo_sugerido == "34013000"
    assert lq.cclasstrib_sugerido == "000001"
    assert "NCM_INCOERENTE_COM_DESCRICAO" in lq.identidade["problemas_cadastro"]

    # Suco comum: a IA só supõe; a suposição não vira fato e nasce uma pergunta decisiva.
    s_ = _item(org, suco)
    assert s_.status == "aguardando_informacao"
    assert s_.perguntas[0]["atributo"] == "adicao_acucar"
    assert s_.perguntas[0]["sugestao"]["valor"] == "nao"
    assert s_.cclasstrib_sugerido is None

    # Suco integral: o fato está explícito na descrição e vira fato com evidência.
    it = _item(org, integral)
    assert it.status == "classificado" and it.cclasstrib_sugerido == "200034"
    assert it.fatos_usados[0]["origem"] == "descricao"

    inv = _item(org, invalido)
    assert inv.status == "revisao_contador"
    assert "CODIGO_SUGERIDO_INVALIDO" in inv.motivos

    investigacoes = [c for c in fake.chamadas if c.startswith("investigar:")]
    assert sorted(investigacoes) == ["investigar:20096100", "investigar:34011190", "investigar:34013000"]

    with sync_tenant_session(TenantContext.sistema(org)) as s:
        assert s.get(Audit, aid).status == "concluida"
        assert s.scalar(select(func.count()).select_from(TaxThesis)) == 3
        p = s.scalar(select(Pendencia).where(Pendencia.audit_id == aid))
        assert p.escopo == "grupo" and p.grupo_chave == "familia:ncm:20096100"
        assert p.item_ids == [suco]
        pid = p.id
        assert s.scalar(select(func.count()).select_from(CompanyFact).where(CompanyFact.origem == "descricao")) == 1

    # Resposta à pergunta: vira fato do grupo e o item é reavaliado sem nova chamada de IA.
    chamadas = len(fake.chamadas)
    with sync_tenant_session(TenantContext.sistema(org)) as s:
        autor = pendencias.Autor(uuid.uuid4(), "operador@teste.com.br")
        afetados = pendencias.responder(s, pid, autor, valor="nao")
        for i in afetados:
            reavaliar(s, i, "resposta")
    s2 = _item(org, suco)
    assert s2.status == "classificado" and s2.cclasstrib_sugerido == "200034"
    assert s2.fatos_usados[0]["origem"] == "usuario"
    assert len(fake.chamadas) == chamadas
    with sync_tenant_session(TenantContext.sistema(org)) as s:
        versoes = list(s.scalars(select(TaxProfile).where(TaxProfile.item_id == suco).order_by(TaxProfile.versao)))
        assert [(v.versao, v.ativo, v.status) for v in versoes] == [
            (1, False, "aguardando_informacao"),
            (2, True, "classificado"),
        ]
        assert s.get(Pendencia, pid).status == "respondida"


def test_memoria_e_tese_reaproveitadas_em_nova_auditoria(ambiente: dict[str, Any]) -> None:
    from app.audits.processing import processar_itens
    from app.db.session import TenantContext, sync_tenant_session
    from app.review import service

    org, fake = ambiente["org_id"], ambiente["fake"]
    aid, (liq,) = ambiente["nova_auditoria"]([("SAB LIQ ERVA DOCE 250ML", "34011190")])
    processar_itens(aid, org, [liq])
    revisor = service.Revisor(user_id=uuid.uuid4(), email="revisor@teste.com.br")
    with sync_tenant_session(TenantContext.sistema(org)) as s:
        service.desfazer  # noqa: B018 (a aprovação automática já foi feita; aprovamos manualmente por cima)
        service.aprovar(s, liq, revisor, "conferido")
    assert _item(org, liq).aprovado_automaticamente is False

    chamadas = len(fake.chamadas)
    aid2, (liq2,) = ambiente["nova_auditoria"]([("SAB LIQ ERVA DOCE 250ML", "34011190")])
    processar_itens(aid2, org, [liq2])
    i2 = _item(org, liq2)
    assert i2.origem == "memoria_aprovada" and i2.identidade["situacao"] == "memoria"
    assert i2.status == "classificado" and i2.cclasstrib_sugerido == "000001"
    assert len(fake.chamadas) == chamadas  # nem identificação nem investigação: tudo reaproveitado


def test_correcao_do_codigo_pelo_revisor_reanalisa_o_item(ambiente: dict[str, Any]) -> None:
    from app.audits.processing import processar_itens
    from app.db.session import TenantContext, sync_tenant_session
    from app.review import service

    org = ambiente["org_id"]
    aid, (inv,) = ambiente["nova_auditoria"]([("PRODUTO MISTERIOSO", "22021000")])
    processar_itens(aid, org, [inv])
    assert _item(org, inv).status == "revisao_contador"
    revisor = service.Revisor(user_id=uuid.uuid4(), email="revisor@teste.com.br")
    from app.models import Audit

    with sync_tenant_session(TenantContext.sistema(org)) as s:
        _, reprocessar = service.editar(s, inv, revisor, tipo_codigo="ncm", codigo="34011190", comentario="é sabão")
        s.get(Audit, aid).status = "processando"  # como faz a rota de edição
    assert reprocessar
    processar_itens(aid, org, [inv])
    i = _item(org, inv)
    assert i.identidade["situacao"] == "memoria" and i.cclasstrib_sugerido == "200035"


def _concluir_pendentes_do_lote(org: uuid.UUID, fake: FakeClaude) -> int:
    from app.db.session import TenantContext, sync_tenant_session
    from app.llm.gateway import registrar_resposta
    from app.models import LlmCall

    n = 0
    with sync_tenant_session(TenantContext.sistema(org)) as s:
        for call in s.scalars(select(LlmCall).where(LlmCall.status == "na_fila")):
            resp = fake.create(**call.requisicao["params"]).to_dict()
            registrar_resposta(call, resp, lote=True)
            call.status = "concluida"
            n += 1
    return n


def test_modo_lote_interrompe_e_retoma_sem_cobrar_duas_vezes(ambiente: dict[str, Any]) -> None:
    from app.audits.processing import processar_itens
    from app.db.session import TenantContext, sync_tenant_session
    from app.models import LlmCall

    org, fake = ambiente["org_id"], ambiente["fake"]
    aid, (barra,) = ambiente["nova_auditoria"]([("SAB BARRA ERVA DOCE 90G", "34011190")], modo="lote")
    processar_itens(aid, org, [barra])
    assert _item(org, barra).etapa == "aguardando_lote"
    # Julgamento e depois a investigação da família: cada um espera o seu lote.
    for _ in range(4):
        if _item(org, barra).status == "classificado":
            break
        assert _concluir_pendentes_do_lote(org, fake) >= 1
        processar_itens(aid, org, [barra])
    assert _item(org, barra).status == "classificado"
    chamadas = len(fake.chamadas)
    processar_itens(aid, org, [barra])  # reprocessar o mesmo bloco não refaz nada
    assert len(fake.chamadas) == chamadas
    with sync_tenant_session(TenantContext.sistema(org)) as s:
        nos = sorted(c.no for c in s.scalars(select(LlmCall).where(LlmCall.audit_id == aid)))
        assert nos == ["investigar_enquadramento", "julgar_coerencia"]


class QuedaSimulada(BaseException):
    """Simula a morte do processo do worker (não é tratada como erro do item)."""


def test_retoma_apos_queda_do_worker_sem_repetir_chamada(
    ambiente: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.audits.processing import processar_itens
    from app.pipeline import analista, graph

    org, fake = ambiente["org_id"], ambiente["fake"]
    aid, (liq,) = ambiente["nova_auditoria"]([("SAB LIQ ERVA DOCE 250ML", "34011190")])
    original = analista.concluir
    estado = {"caiu": False}

    def quebra(state, runtime):  # type: ignore[no-untyped-def]
        if not estado["caiu"]:
            estado["caiu"] = True
            raise QuedaSimulada()
        return original(state, runtime)

    monkeypatch.setattr(analista, "concluir", quebra)
    graph.grafo.cache_clear()
    with pytest.raises(QuedaSimulada):
        processar_itens(aid, org, [liq])
    assert _item(org, liq).status == "processando"
    chamadas = len(fake.chamadas)  # julgamento + segundo parecer + investigação já feitos antes da queda
    assert chamadas == 3

    # A tarefa é reentregue (acks_late) ou recuperada: o grafo retoma do checkpoint.
    processar_itens(aid, org, [liq])
    graph.grafo.cache_clear()
    assert _item(org, liq).status == "classificado"
    assert len(fake.chamadas) == chamadas  # nenhuma chamada repetida


def test_itens_iguais_de_marcas_diferentes_fazem_uma_unica_analise(ambiente: dict[str, Any]) -> None:
    from app.audits.processing import processar_itens

    org, fake = ambiente["org_id"], ambiente["fake"]
    aid, ids = ambiente["nova_auditoria"](
        [("SUCO UVA ESTRELA 1L", "20096100"), ("SUCO UVA PRIMOR 1L", "20096100"), ("SUCO UVA 1L", "20096100")],
        marcas=["Estrela", "Primor", None],
    )
    processar_itens(aid, org, ids)
    julgamentos = [c for c in fake.chamadas if c.startswith("julgar:")]
    assert len(julgamentos) == 1, fake.chamadas  # uma chamada serve às três linhas
    assert len([c for c in fake.chamadas if c.startswith("investigar:")]) == 1
    assert {_item(org, i).status for i in ids} == {"aguardando_informacao"}
