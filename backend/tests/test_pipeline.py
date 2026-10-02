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
    "28": "Produtos químicos inorgânicos",
    "2828": "Hipocloritos",
    "282890": "Outros",
    "28289011": "Hipoclorito de sódio",
    "38": "Produtos diversos das indústrias químicas",
    "3808": "Inseticidas, desinfetantes e produtos semelhantes",
    "380894": "Desinfetantes",
    "38089419": "Desinfetantes para uso domissanitário, outros",
    "30": "Produtos farmacêuticos",
    "3004": "Medicamentos acondicionados para venda a retalho",
    "300490": "Outros",
    "30049036": "Cloridrato de fenilefrina; mirtecaína; propranolol ou seus sais",
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
        self.pacotes: dict[str, dict[str, Any]] = {}  # o que o Jurista recebeu, por código
        self.messages = self

    def create(self, **params: Any) -> FakeMensagem:
        conteudo = json.loads(params["messages"][0]["content"])
        if "cclasstrib_candidatos" in conteudo:
            r = self._investigar(conteudo)
            self.chamadas.append("investigar:" + conteudo["codigo"]["codigo"])
        elif "fatos_pedidos" in conteudo:
            r = self._fatos(conteudo)
            self.chamadas.append("fatos:" + conteudo["item"]["descricao_original"])
        elif "opcoes" in conteudo and "nivel" in conteudo:
            # Busca guiada na árvore: "PROD DIVERSOS" não cabe em nenhum capítulo.
            r = self._arvore(conteudo)
            self.chamadas.append(f"arvore-{conteudo['nivel']}:" + conteudo["item"]["descricao_original"])
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
        citados = [c["codigo"] for c in conteudo["candidatos"] if c.get("citado_na_lei")]
        if "AGUA SANITARIA" in desc:
            escolha = citados[0] if citados else "28289011"
            r = {**base, "ncm_atual_coerente": not citados, "codigo_sugerido": escolha, "confianca": 0.92}
        elif "LIQ" in desc:
            r = {**base, "ncm_atual_coerente": False, "codigo_sugerido": "34013000", "confianca": 0.94}
        elif "BARRA" in desc:
            r = {**base, "ncm_atual_coerente": True, "codigo_sugerido": "34011190", "confianca": 0.97}
        elif "NALDECON" in desc:
            # A marca é o nome do produto: ela precisa chegar ao modelo, com o tipo do ERP.
            assert conteudo["item"]["informacoes_adicionais"].get("tipo_no_erp") == "medicamento para revenda"
            r = {**base, "ncm_atual_coerente": True, "codigo_sugerido": "30049036", "confianca": 0.95}
        elif "SUCO" in desc:
            r = {**base, "ncm_atual_coerente": True, "codigo_sugerido": "20096100", "confianca": 0.96}
        else:  # sugere um código fora da lista: deve ser descartado
            r = {**base, "ncm_atual_coerente": False, "codigo_sugerido": "99999999", "confianca": 0.99}
        assert r["codigo_sugerido"] in candidatos or r["codigo_sugerido"] == "99999999"
        if "analise_anterior" in conteudo:
            r["concorda_com_analise_anterior"] = True
        return {**r, "_desc": desc}

    def _arvore(self, c: dict[str, Any]) -> dict[str, Any]:
        opcoes = [o["codigo"] for o in c["opcoes"]]
        nada = {"escolha": None, "alternativas": [], "confianca": 0.1, "justificativa": "teste"}
        if "SABONETE CAPITULO ERRADO" in c["item"]["descricao_original"]:
            # 1º capítulo sem código que sirva; o alternativo (34) tem o código certo.
            if c["nivel"] == "capitulo":
                return {
                    **nada,
                    "escolha": "20",
                    "alternativas": [{"codigo": "34", "motivo": "sabão"}],
                    "confianca": 0.6,
                }
            if "34013000" in opcoes:
                return {**nada, "escolha": "34013000", "confianca": 0.8}
            return nada
        if "KIT SABONETE" not in c["item"]["descricao_original"]:
            return nada  # ex.: "PRODUTO MISTERIOSO" não cabe em nenhum capítulo
        for alvo in ("34013000", "3401", "34"):
            if alvo in opcoes:
                alt = [{"codigo": "34011190", "motivo": "se for em barra"}] if alvo == "34013000" else []
                return {"escolha": alvo, "alternativas": alt, "confianca": 0.8, "justificativa": "sabonete líquido"}
        return nada

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
        self.pacotes[codigo] = c
        if codigo == "30049036":
            lei = {
                x["cclasstrib"]: x["ref"]
                for x in c["correlacoes_oficiais"]
                if str(x.get("fonte", "")).startswith("lei")
            }
            hipoteses = [
                {
                    "id": "H1",
                    "titulo": "Alíquota zero — lista do art. 146",
                    "tipo": "beneficio",
                    "cclasstrib": "200009",
                    "condicoes": [{"fato": "lista_aliquota_zero", "valor_exigido": "sim", "explicacao": ""}],
                    "excecoes": [],
                    "fundamentos": [{"ref": lei.get("200009", "C999"), "trecho": "art. 146"}],
                    "explicacao": "",
                },
                {
                    "id": "H2",
                    "titulo": "Medicamento registrado na Anvisa (redução de 60%)",
                    "tipo": "beneficio",
                    "cclasstrib": "200032",
                    "condicoes": [],
                    "excecoes": [],
                    "fundamentos": [{"ref": lei.get("200032", "C999"), "trecho": "art. 133"}],
                    "explicacao": "",
                },
                geral,
            ]
            fatos = [
                {
                    "fato": "lista_aliquota_zero",
                    "escopo": "item",
                    "pergunta": "O medicamento está na lista de alíquota zero?",
                    "opcoes": ["sim", "nao"],
                    "como_identificar_na_descricao": "",
                }
            ]
        elif codigo == "34011190":
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
            if f["fato"] == "preparado_no_estabelecimento" and ("ESPRESSO" in desc or "LATA" in desc):
                v, ev = ("sim", "ESPRESSO") if "ESPRESSO" in desc else ("nao", "LATA")
                saida.append({"fato": f["fato"], "valor": v, "base": "explicito", "evidencia": ev})
            elif f["fato"] == "bebida_alcoolica" and "CAFE" in desc:
                saida.append({"fato": f["fato"], "valor": "nao", "base": "explicito", "evidencia": "CAFE"})
            elif "INTEGRAL" in desc:
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
            ("200047", "200", "Bares e Restaurantes, observado o art. 275", None),
            ("200009", "200", "Medicamentos registrados na Anvisa, observado o art. 146", None),
            ("200032", "200", "Medicamentos registrados na Anvisa, observado o art. 133", None),
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
                    tipo="anexo_item",
                    anexo="VIII",
                    item="5",
                    titulo_anexo="PRODUTOS DE HIGIENE PESSOAL E LIMPEZA",
                    texto="Água sanitária classificada no código 3808.94.19 da NCM/SH",
                    codigos_citados=["38089419"],
                ),
                *(
                    LegalProvision(
                        version_id=v_lc.id,
                        tipo="artigo",
                        artigo=art,
                        texto=f"Art. {art}. Texto de teste do regime de bares e restaurantes.",
                        codigos_citados=[],
                    )
                    for art in ("273", "274", "275", "133", "146")
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

    def virar_restaurante() -> None:
        from app.analise import fatos as fatos_mod
        from app.models.enums import EscopoFato, OrigemFato

        with sync_tenant_session(TenantContext.sistema(org_id)) as s:
            s.get(Company, emp_id).segmento = "restaurante"
            fatos_mod.registrar(
                s,
                org_id=org_id,
                company_id=emp_id,
                escopo=EscopoFato.EMPRESA,
                atributo="fornece_refeicoes",
                valor_="sim",
                origem=OrigemFato.USUARIO,
            )

    return {
        "org_id": org_id,
        "emp_id": emp_id,
        "fake": fake,
        "nova_auditoria": nova_auditoria,
        "virar_restaurante": virar_restaurante,
    }


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
    # Nem a prova nem a busca guiada acharam código: o NCM do ERP fica como referência, não confirmado.
    assert inv.identidade["situacao"] == "nao_confirmado" and inv.identidade["erp_mantido"] is True
    assert inv.dimensoes["codigo_fiscal"]["situacao"] == "atencao"

    investigacoes = [c for c in fake.chamadas if c.startswith("investigar:")]
    assert sorted(investigacoes) == [
        "investigar:20096100",
        "investigar:22021000",
        "investigar:34011190",
        "investigar:34013000",
    ]

    with sync_tenant_session(TenantContext.sistema(org)) as s:
        assert s.get(Audit, aid).status == "concluida"
        assert s.scalar(select(func.count()).select_from(TaxThesis)) == 4
        p = s.scalar(select(Pendencia).where(Pendencia.audit_id == aid))
        assert p.escopo == "grupo" and p.grupo_chave == "familia:ncm:20096100"
        assert p.item_ids == [suco]
        pid = p.id
        assert s.scalar(select(func.count()).select_from(CompanyFact).where(CompanyFact.origem == "descricao")) == 1

    # Resposta à pergunta: vira fato de cada item listado e o item é reavaliado sem nova chamada de IA.
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


def test_item_sem_ncm_recebe_sugestao_pela_arvore_oficial(ambiente: dict[str, Any]) -> None:
    from app.audits.processing import processar_itens

    org, fake = ambiente["org_id"], ambiente["fake"]
    aid, (kit,) = ambiente["nova_auditoria"]([("KIT SABONETE PRESENTE", None)])
    processar_itens(aid, org, [kit])
    i = _item(org, kit)
    # A IA não achou nada na busca; a árvore sugeriu o código e o Jurista enquadrou.
    assert i.codigo_sugerido == "34013000"
    assert i.identidade["via_arvore"] is True and i.identidade["situacao"] == "sugerido"
    assert [a["codigo"] for a in i.identidade["arvore"]["alternativas"]] == ["34011190"]
    assert i.cclasstrib_sugerido is not None
    assert i.status == "revisao_contador"  # o NCM sugerido precisa de confirmação
    assert any(c.startswith("arvore-capitulo:") for c in fake.chamadas)
    assert any(c.startswith("arvore-codigo:") for c in fake.chamadas)


def test_navegador_tenta_o_capitulo_alternativo(ambiente: dict[str, Any]) -> None:
    from app.audits.processing import processar_itens

    org = ambiente["org_id"]
    aid, (item,) = ambiente["nova_auditoria"]([("SABONETE CAPITULO ERRADO", None)])
    processar_itens(aid, org, [item])
    i = _item(org, item)
    assert i.codigo_sugerido == "34013000"
    assert i.identidade["arvore"]["caminho"][0]["codigo"] == "34"


def test_codigo_citado_na_lei_entra_na_prova_e_a_troca_vai_ao_contador(ambiente: dict[str, Any]) -> None:
    from app.audits.processing import processar_itens

    org = ambiente["org_id"]
    aid, (agua,) = ambiente["nova_auditoria"]([("AGUA SANITARIA 2L", "28289011")])
    processar_itens(aid, org, [agua])
    i = _item(org, agua)
    # O código que a lei atribui ao produto entrou na prova e a IA corrigiu o NCM.
    assert i.codigo_sugerido == "38089419"
    assert i.identidade["situacao"] == "corrigido"
    assert "Anexo VIII" in i.identidade["corrigido_pela_lei"]
    # A troca não muda o imposto aqui (ADR 0029): o IBS/CBS sai, e o NCM novo espera uma pessoa na lista
    # "Ajustes de cadastro". Enquanto isso, a exportação mantém o NCM do ERP.
    assert i.status == "classificado"
    assert i.ajuste_cadastro_status == "pendente"
    assert i.ajuste_cadastro["sugerido"] == "38089419" and i.ajuste_cadastro["erp"] == "28289011"
    assert i.final_codigo == "28289011"


def test_resposta_em_grupo_vale_so_para_os_itens_listados(ambiente: dict[str, Any]) -> None:
    """Um item da mesma família que chega depois recebe a pergunta de novo (ADR 0026)."""
    from app.analise import pendencias
    from app.analise.aplicacao import reavaliar
    from app.audits.processing import processar_itens
    from app.db.session import TenantContext, sync_tenant_session
    from app.models import CompanyFact, Pendencia

    org = ambiente["org_id"]
    aid, (suco,) = ambiente["nova_auditoria"]([("SUCO UVA 1L", "20096100")])
    processar_itens(aid, org, [suco])
    with sync_tenant_session(TenantContext.sistema(org)) as s:
        p = s.scalar(select(Pendencia).where(Pendencia.audit_id == aid))
        afetados = pendencias.responder(s, p.id, pendencias.Autor(uuid.uuid4(), "op@teste.com.br"), valor="nao")
        for i in afetados:
            reavaliar(s, i, "resposta")
        fatos = list(s.scalars(select(CompanyFact).where(CompanyFact.atributo == "adicao_acucar")))
        assert [(f.escopo, f.item_chave) for f in fatos] == [("item", _item(org, suco).codigo_interno)]
    assert _item(org, suco).cclasstrib_sugerido == "200034"

    aid2, (outro,) = ambiente["nova_auditoria"]([("SUCO UVA 500ML", "20096100")])
    processar_itens(aid2, org, [outro])
    o = _item(org, outro)
    assert o.status == "aguardando_informacao" and o.perguntas[0]["atributo"] == "adicao_acucar"


def test_restaurante_espresso_sem_ncm_sai_pelo_regime_da_operacao(ambiente: dict[str, Any]) -> None:
    """O caso que motivou a ADR 0026: nem a prova nem a árvore acham o NCM, e o cClassTrib sai assim mesmo."""
    from app.audits.processing import processar_itens

    org, fake = ambiente["org_id"], ambiente["fake"]
    ambiente["virar_restaurante"]()
    aid, (cafe, lata) = ambiente["nova_auditoria"](
        [("CAFE ESPRESSO 50ML", None), ("REFRIGERANTE COLA LATA 350ML", "22021000")]
    )
    processar_itens(aid, org, [cafe, lata])

    c = _item(org, cafe)
    assert c.identidade["situacao"] == "indefinido"
    assert (c.cclasstrib_sugerido, c.cst_sugerido, c.hipotese) == ("200047", "200", "OP-restaurante")
    assert c.dimensoes["codigo_fiscal"]["situacao"] == "ok"  # o NCM vai para "Ajustes de cadastro"
    assert c.ajuste_cadastro_status == "pendente"
    assert c.status == "revisao_contador"  # sem NCM, o Imposto Seletivo não foi avaliado
    assert {f["atributo"]: f["origem"] for f in c.fatos_usados} == {
        "preparado_no_estabelecimento": "descricao",
        "servido_como_alimentacao": "cadastro",
        "bebida_alcoolica": "descricao",
    }
    assert "fatos:CAFE ESPRESSO 50ML" in fake.chamadas

    r = _item(org, lata)
    # Comprado pronto e só revendido: fora do regime do restaurante (art. 273, § 2º, II).
    assert r.cclasstrib_sugerido == "000001"


def test_farmacia_naldecon_recebe_os_codigos_de_medicamento_pela_lei(ambiente: dict[str, Any]) -> None:
    """Simulação do ADR 0027: a tabela oficial não liga 3004.90.36 aos cClassTrib de medicamento humano."""
    from app.audits.processing import processar_itens
    from app.db.session import TenantContext, sync_tenant_session
    from app.models import AuditItem

    org, fake = ambiente["org_id"], ambiente["fake"]
    aid, (item,) = ambiente["nova_auditoria"]([("NALDECON PACK", "30049036")], marcas=["Naldecon"])
    with sync_tenant_session(TenantContext.sistema(org)) as s:
        s.get(AuditItem, item).tipo_informado = "medicamento para revenda"
    processar_itens(aid, org, [item])

    pacote = fake.pacotes["30049036"]
    candidatos = {c["codigo"] for c in pacote["cclasstrib_candidatos"]}
    assert {"200009", "200032"} <= candidatos
    assert any(t["local"] == "Art. 133" for t in pacote["trechos_normativos"])
    i = _item(org, item)
    assert i.descricao_normalizada.upper().startswith("NALDECON")  # a marca é o produto: ficou
    # Falta saber se está na lista de alíquota zero; se não estiver, 60% (200032) — nunca a integral.
    assert i.status == "aguardando_informacao"
    efeitos = {o["valor"]: o["efeito"] for o in i.perguntas[0]["opcoes"]}
    assert "200009" in efeitos["sim"] and "200032" in efeitos["nao"]


# ---------------------------------------------------- menos revisão humana (ADR 0029) --
def test_falha_da_plataforma_pausa_a_auditoria_e_nao_manda_o_item_para_revisao(
    ambiente: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.audits import processing
    from app.db.session import TenantContext, sync_tenant_session
    from app.llm import gateway, provedores
    from app.models import Audit

    org = ambiente["org_id"]
    aid, (item,) = ambiente["nova_auditoria"]([("SAB LIQ ERVA DOCE 250ML", "34011190")])
    original = gateway._chamar

    def sem_credito(req: Any) -> dict[str, Any]:
        raise provedores.ErroTransitorio("HTTP 429: You have no credits remaining")

    monkeypatch.setattr(gateway, "_chamar", sem_credito)
    monkeypatch.setattr(gateway, "_espera", lambda tentativa, erro: 0.0)
    enfileirados: list[uuid.UUID] = []
    monkeypatch.setattr(processing, "enfileirar_itens", lambda a, o, ids: enfileirados.extend(ids))
    processing.processar_itens(aid, org, [item])

    i = _item(org, item)
    assert i.status not in ("revisao_contador", "revisao_especialista", "erro")  # nada vai para uma pessoa
    with sync_tenant_session(TenantContext.sistema(org)) as s:
        a = s.get(Audit, aid)
        assert a.status == "pausada_ia" and a.configuracao["pausa_ia"]["seguidas"] == 1
        assert "créditos" in (a.erro or "")
    # Antes da hora marcada, a tarefa periódica não retoma; forçada (ou na hora), retoma.
    assert processing.retomar_pausadas_por_ia(org) == 0
    monkeypatch.setattr(gateway, "_chamar", original)
    assert processing.retomar_pausadas_por_ia(org, forcar=True) == 1
    assert enfileirados == [item]
    processing.processar_itens(aid, org, enfileirados)
    i = _item(org, item)
    assert i.status in ("classificado", "aguardando_informacao", "revisao_contador")
    assert i.codigo_sugerido == "34013000"
    with sync_tenant_session(TenantContext.sistema(org)) as s:
        assert "pausa_ia" not in (s.get(Audit, aid).configuracao or {})


def test_itens_parecidos_aprovados_por_pessoas_confirmam_o_ncm_do_erp(ambiente: dict[str, Any]) -> None:
    from app.config import get_settings
    from app.db.session import TenantContext, sync_tenant_session
    from app.models import ApprovedMemory
    from app.pipeline.nodes import _confirmacao_por_parecidos, parecidos_aprovados
    from app.pipeline.state import ItemState

    org, emp = ambiente["org_id"], ambiente["emp_id"]
    dim = get_settings().embeddings_dim
    with sync_tenant_session(TenantContext.sistema(org)) as s:
        for desc, cod in (("sabonete barra erva doce 90g", "34011190"), ("sabonete liquido 250ml", "34013000")):
            s.add(
                ApprovedMemory(
                    org_id=org,
                    company_id=emp,
                    descricao_normalizada=desc,
                    descricao_hash=desc,
                    tipo_codigo="ncm",
                    codigo=cod,
                    atributos={},
                )
            )
        s.flush()
        # Os vetores que faltam são calculados na primeira busca.
        viz = parecidos_aprovados(s, "sabonete barra erva doce 90g", vetor("sabonete barra erva doce 90g", dim))
        assert viz[0]["codigo"] == "34011190" and viz[0]["similaridade"] > 0.99
        assert all(m.embedding is not None for m in s.scalars(select(ApprovedMemory)))

    st = ItemState(item_id="1", audit_id="1", org_id="1")
    atual = {"tipo": "ncm", "codigo": "34011190", "existe": True, "folha": True, "vigente": True}
    igual = [{"codigo": "34011190", "similaridade": 0.97, "descricao": "x", "tipo_codigo": "ncm"}]
    assert _confirmacao_por_parecidos(st, atual, [], igual)["posicao_confirmacao"] == 0
    # Um item parecido decidido com outro código impede a confirmação.
    contra = [*igual, {"codigo": "34013000", "similaridade": 0.94, "descricao": "y", "tipo_codigo": "ncm"}]
    assert _confirmacao_por_parecidos(st, atual, [], contra) is None
    # Semelhança abaixo do limite não confirma.
    assert _confirmacao_por_parecidos(st, atual, [], [{**igual[0], "similaridade": 0.93}]) is None
    # A lei cita o produto com outro código: a IA precisa comparar.
    assert _confirmacao_por_parecidos(st, atual, [{"citado_na_lei": "Anexo VIII"}], igual) is None


def test_resposta_o_que_e_o_item_vira_memoria_e_reanalisa(ambiente: dict[str, Any]) -> None:
    from app.analise import pendencias
    from app.db.session import TenantContext, sync_tenant_session
    from app.models import ApprovedMemory, AuditItem, Pendencia

    org = ambiente["org_id"]
    aid, (item,) = ambiente["nova_auditoria"]([("SUCO UVA 1L", "20096100")])
    autor = pendencias.Autor(uuid.uuid4(), "op@teste.com.br")
    with sync_tenant_session(TenantContext.sistema(org)) as s:
        i = s.get(AuditItem, item)
        i.status, i.identidade = "aguardando_informacao", {"tipo_codigo": "ncm", "codigo": "20096100"}
        p = Pendencia(
            org_id=org,
            audit_id=aid,
            company_id=i.company_id,
            atributo=pendencias.FATO_CODIGO,
            escopo="grupo",
            grupo_chave="ident:20096100-22021000",
            grupo_rotulo="t",
            pergunta="Qual destas descrições corresponde ao item?",
            motivo="t",
            opcoes=[{"valor": "20096100"}, {"valor": "22021000"}, {"valor": "outro"}],
            nivel="operacional",
            item_ids=[item],
            status="aberta",
            respostas_itens={},
        )
        s.add(p)
        s.flush()
        afetados = pendencias.responder(s, p.id, autor, valor="22021000")
        reprocessar = pendencias.identificar_pela_resposta(s, p.id, autor, afetados)
        assert reprocessar == [item]
        mem = s.scalar(select(ApprovedMemory).where(ApprovedMemory.ativo.is_(True)))
        assert mem.codigo == "22021000" and mem.aprovado_por == autor.user_id
        assert s.get(AuditItem, item).status == "pendente"


def _em_revisao(org: uuid.UUID, ids: list[uuid.UUID], *, ajuste: dict[str, Any] | None = None) -> None:
    """Põe itens no estado de "revisão do contador" pelo Imposto Seletivo (mesma decisão para todos)."""
    from app.db.session import TenantContext, sync_tenant_session
    from app.models import AuditItem

    with sync_tenant_session(TenantContext.sistema(org)) as s:
        for iid in ids:
            i = s.get(AuditItem, iid)
            i.status, i.nivel_revisao, i.revisao_status = "revisao_contador", "contador", "pendente"
            i.identidade = {"tipo_codigo": "ncm", "codigo": i.ncm, "descricao_oficial": "a › b"}
            i.tipo_codigo_sugerido, i.codigo_sugerido = "ncm", i.ncm
            i.cclasstrib_sugerido, i.cst_sugerido, i.is_situacao = "000001", "000", "sujeito"
            i.motivos, i.perguntas, i.fatos_usados = ["SUJEITO_A_IMPOSTO_SELETIVO"], [], []
            i.dimensoes = {
                "identificacao": {"rotulo": "Identificação", "situacao": "ok", "texto": ""},
                "imposto_seletivo": {"rotulo": "Imposto Seletivo", "situacao": "atencao", "texto": "Anexo XVII"},
            }
            if ajuste:
                i.ajuste_cadastro, i.ajuste_cadastro_status = ajuste, "pendente"


def test_aprovar_um_item_vale_na_hora_para_os_iguais_e_desfaz_em_lote(ambiente: dict[str, Any]) -> None:
    from app.db.session import TenantContext, sync_tenant_session
    from app.review import service

    org = ambiente["org_id"]
    aid, ids = ambiente["nova_auditoria"](
        [
            ("REFRIGERANTE COLA 2L", "22021000"),
            ("REFRIGERANTE COLA 600ML", "22021000"),
            ("REFRIGERANTE GUARANA 2L", "22021000"),
            ("SUCO UVA 1L", "20096100"),
        ]
    )
    _em_revisao(org, ids)
    revisor = service.Revisor(user_id=uuid.uuid4(), email="contador@teste.com.br")
    with sync_tenant_session(TenantContext.sistema(org)) as s:
        grupos = service.grupos_de_revisao(s, aid)
        assert [len(g.item_ids) for g in grupos] == [3, 1]  # uma decisão resolve os três refrigerantes
        _, lote, n = service.aprovar_e_aplicar_aos_iguais(s, ids[0], revisor, "conferido")
    assert n == 2 and lote is not None
    assert [_item(org, i).revisao_status for i in ids] == ["aprovado", "aprovado", "aprovado", "pendente"]
    assert _item(org, ids[1]).aprovado_automaticamente is False
    with sync_tenant_session(TenantContext.sistema(org)) as s:
        assert service.desfazer_lote(s, aid, lote, revisor) == 2
    assert [_item(org, i).revisao_status for i in ids[:3]] == ["aprovado", "pendente", "pendente"]


def test_ajuste_de_cadastro_aceito_ou_mantido_define_o_ncm_exportado(ambiente: dict[str, Any]) -> None:
    from app.analise.aplicacao import codigo_para_o_cadastro
    from app.db.session import TenantContext, sync_tenant_session
    from app.models import ApprovedMemory, AuditItem
    from app.review import service

    org = ambiente["org_id"]
    aid, (a, b) = ambiente["nova_auditoria"]([("SAB LIQ ERVA DOCE 250ML", "34011190"), ("SABONETE X", "34011190")])
    ajuste = {"tipo_codigo": "ncm", "erp": "34011190", "sugerido": "34013000", "alternativas": [], "texto": "t"}
    _em_revisao(org, [a, b], ajuste=ajuste)
    revisor = service.Revisor(user_id=uuid.uuid4(), email="contador@teste.com.br")
    with sync_tenant_session(TenantContext.sistema(org)) as s:
        # Enquanto pendente, a exportação mantém o NCM do ERP.
        assert codigo_para_o_cadastro(s.get(AuditItem, a)) == "34011190"
        assert service.decidir_ajustes_cadastro(s, aid, [a], "aceitar", revisor) == 1
        assert service.decidir_ajustes_cadastro(s, aid, [b], "manter", revisor) == 1
        assert codigo_para_o_cadastro(s.get(AuditItem, a)) == "34013000"
        assert codigo_para_o_cadastro(s.get(AuditItem, b)) == "34011190"
        codigos = {m.codigo for m in s.scalars(select(ApprovedMemory).where(ApprovedMemory.ativo.is_(True)))}
        assert codigos == {"34013000", "34011190"}  # a decisão sobre o NCM vira memória da empresa
    assert _item(org, a).ajuste_cadastro_status == "aceito"
    with sync_tenant_session(TenantContext.sistema(org)) as s:
        service.desfazer(s, a, revisor)
    assert _item(org, a).ajuste_cadastro_status == "pendente"


def test_pergunta_da_empresa_respondida_num_item_vale_para_a_empresa(ambiente: dict[str, Any]) -> None:
    """O usuário respondeu "não fabrica nem importa" pelo botão do item: a resposta é da empresa."""
    from app.analise import pendencias
    from app.db.session import TenantContext, sync_tenant_session
    from app.models import CompanyFact, Pendencia

    org = ambiente["org_id"]
    aid, (a, b) = ambiente["nova_auditoria"]([("CERVEJA LATA 350ML", "22030000"), ("VINHO TINTO 750ML", "22042100")])
    autor = pendencias.Autor(uuid.uuid4(), "op@teste.com.br")
    with sync_tenant_session(TenantContext.sistema(org)) as s:
        emp = ambiente["emp_id"]
        p = Pendencia(
            org_id=org,
            audit_id=aid,
            company_id=emp,
            atributo="fabrica_ou_importa_seletivo",
            escopo="empresa",
            grupo_chave="",
            grupo_rotulo="Toda a empresa",
            pergunta="A empresa fabrica ou importa?",
            motivo="t",
            opcoes=[{"valor": "nao"}, {"valor": "sim"}],
            nivel="operacional",
            item_ids=[a, b],
            status="aberta",
            respostas_itens={},
        )
        s.add(p)
        s.flush()
        afetados = pendencias.responder(s, p.id, autor, respostas_itens={a: "nao"})
        assert set(afetados) == {a, b}
        fatos = list(s.scalars(select(CompanyFact).where(CompanyFact.atributo == "fabrica_ou_importa_seletivo")))
        assert [(f.escopo, f.valor) for f in fatos] == [("empresa", "nao")]
        assert s.get(Pendencia, p.id).status == "respondida"


def test_reaplicar_usa_a_tese_do_proprio_item_e_respeita_a_pessoa(ambiente: dict[str, Any]) -> None:
    from app.analise.aplicacao import reaplicar_item
    from app.audits.processing import processar_itens
    from app.db.session import TenantContext, sync_tenant_session
    from app.models import AuditItem, TaxThesis
    from app.review import service

    org = ambiente["org_id"]
    aid, (suco, sab) = ambiente["nova_auditoria"](
        [("SUCO UVA INTEGRAL 1L", "20096100"), ("SABONETE BARRA", "34011190")]
    )
    processar_itens(aid, org, [suco, sab])
    revisor = service.Revisor(user_id=uuid.uuid4(), email="contador@teste.com.br")
    with sync_tenant_session(TenantContext.sistema(org)) as s:
        # Uma pessoa aprova o sabonete com outro cClassTrib: as regras não chegam lá, nada muda.
        service.editar(
            s, sab, revisor, cst="000", cclasstrib="000001", comentario="decisão do contador", aprovar_em_seguida=True
        )
        antes = (s.get(AuditItem, sab).final_cclasstrib, s.get(AuditItem, sab).status)
        assert reaplicar_item(s, s.get(AuditItem, sab)) == "mantido"
        assert (s.get(AuditItem, sab).final_cclasstrib, s.get(AuditItem, sab).status) == antes
        # Parecer refeito ("Refazer pareceres"): o item precisa de reanálise, não de pergunta nova.
        tese = s.get(TaxThesis, s.get(AuditItem, suco).thesis_id)
        tese.status = "substituida"
        s.flush()
        assert reaplicar_item(s, s.get(AuditItem, suco)) == "reanalisar"
