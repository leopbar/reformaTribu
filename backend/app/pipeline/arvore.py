"""Busca guiada pela árvore oficial (NCM/NBS) para itens que ficaram sem código.

Quando o ERP não trouxe um código válido, ou quando nenhum código da busca descreve o item, o
Navegador desce pela tabela oficial: capítulo → posição → código final. Em cada passo a IA escolhe só
entre opções oficiais, então o código certo está sempre entre as alternativas e nada é inventado.
O código encontrado é uma SUGESTÃO: o item segue para o Jurista (e recebe CST/cClassTrib), mas vai
para o contador confirmar o NCM. Quando a dúvida é entre capítulos (cru × preparado, fresco × conservado),
o Navegador também traz o código de cada capítulo alternativo, com um rótulo em linguagem de loja: se os
impostos diferem, a avaliação pergunta ao operador o que o item é (ADR 0029).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import structlog
from sqlalchemy import text

from app.core.codes import formatar_codigo
from app.db.session import sync_tenant_session
from app.llm import gateway
from app.llm.prompts import carregar
from app.llm.schemas import SCHEMA_NAVEGACAO, NavegacaoArvore
from app.models import AuditItem
from app.pipeline.nodes import Rt, _etapa, _executar, chave_conteudo
from app.pipeline.normalize import remover_marca
from app.pipeline.state import ItemState

log = structlog.get_logger()

# Com até este número de códigos finais sob o nível escolhido, pula direto para eles. Listas longas escondem
# o código certo (ADR 0029: os 51 códigos do capítulo 16, quase todos de peixe, esconderam o de frango).
MAX_FOLHAS_DIRETAS = 25
MAX_OPCOES = 150
MAX_CAPITULOS = 3  # capítulos tentados quando o anterior não tem código que sirva
# Abaixo desta certeza no capítulo, o Navegador também desce pelos capítulos alternativos (cru × preparado,
# fresco × conservado…): o código de cada um entra nas opções da pergunta "o que é este item?" (ADR 0029).
CERTEZA_CAPITULO_UNICO = 0.9


@dataclass
class _Descida:
    """Resultado de uma descida da raiz (capítulo) até o código final."""

    codigo: str | None = None
    descricao: str = ""
    rotulo: str = ""
    alternativas: list[dict[str, Any]] = field(default_factory=list)
    caminho: list[dict[str, str]] = field(default_factory=list)


def _tabela(fonte: str) -> str:
    return "nbs_nodes" if fonte == "nbs" else "ncm_nodes"


def _opcoes(s: Any, fonte: str, versao: uuid.UUID, pai: str | None) -> list[dict[str, Any]]:
    """Filhos diretos de um nó (ou as raízes da árvore)."""
    cond = "codigo_pai IS NULL" if pai is None else "codigo_pai = :pai"
    rows = s.execute(
        text(f"SELECT codigo, descricao, folha FROM {_tabela(fonte)} WHERE version_id = :v AND {cond} ORDER BY codigo"),
        {"v": versao, "pai": pai},
    ).all()
    return [{"codigo": r.codigo, "descricao": r.descricao, "folha": r.folha} for r in rows]


def _folhas(s: Any, fonte: str, versao: uuid.UUID, prefixo: str) -> list[dict[str, Any]]:
    rows = s.execute(
        text(
            f"SELECT codigo, descricao_completa FROM {_tabela(fonte)} "
            "WHERE version_id = :v AND folha AND codigo LIKE :p ORDER BY codigo LIMIT :lim"
        ),
        {"v": versao, "p": prefixo + "%", "lim": MAX_OPCOES},
    ).all()
    return [{"codigo": r.codigo, "descricao": r.descricao_completa, "folha": True} for r in rows]


def _descricao_folha(desc: str) -> str:
    """Os três últimos níveis da hierarquia: o suficiente para distinguir os códigos da mesma posição."""
    return " › ".join(desc.split(" › ")[-3:])


def precisa_navegar(state: ItemState) -> bool:
    from app.pipeline.analista import codigo_escolhido

    # Uma falha do Identificador (ex.: resposta cortada) não impede a busca guiada: ela serve de reserva.
    if state.memoria or state.confirmado_sem_ia or state.base_incompleta:
        return False
    return codigo_escolhido(state)[1] is None


def navegar_arvore(state: ItemState, runtime: Rt) -> dict[str, Any]:
    ctx = runtime.context
    if not precisa_navegar(state):
        return {}
    _etapa(ctx, state.item_id, "navegar_arvore")
    j = state.julgamento or {}
    esc = state.escalonamento or {}
    tipo_item = esc.get("tipo_item") or j.get("tipo_item") or state.tipo
    fonte = "nbs" if tipo_item == "servico" else "ncm"
    versao = ctx.versao(fonte)
    if versao is None:
        return {}
    with sync_tenant_session(ctx.tenant) as s:
        item = s.get(AuditItem, uuid.UUID(state.item_id))
        assert item is not None
        dados_item = {
            "descricao_original": remover_marca(item.descricao, item.marca),
            "descricao_normalizada": state.descricao_normalizada,
            **{k: v for k, v in {"categoria": item.categoria, "unidade": item.unidade}.items() if v},
        }
    pistas = [p for p in (j.get("justificativa"), esc.get("justificativa")) if p]
    prompt = carregar("navegar_arvore", ctx.prompts.get("navegar_arvore"))
    passos: list[dict[str, Any]] = []
    falhas: list[str] = []

    def perguntar(
        nivel: str,
        opcoes: list[dict[str, Any]],
        caminho: list[dict[str, str]],
        registro: list[dict[str, Any]],
        hipotese: str | None = None,
    ) -> NavegacaoArvore | None:
        conteudo: dict[str, Any] = {
            "item": dados_item,
            "nivel": nivel,
            "caminho": [f"{c['codigo']} – {c['descricao']}" for c in caminho],
            "opcoes": [
                {
                    "codigo": o["codigo"],
                    "descricao": _descricao_folha(o["descricao"]) if nivel == "codigo" else o["descricao"],
                }
                for o in opcoes
            ],
            "pistas": pistas,
        }
        if hipotese:
            conteudo["hipotese"] = hipotese
        req = gateway.RequisicaoLLM(
            no="navegar_arvore",
            modelo=ctx.modelo_navegador,
            prompt=prompt,
            conteudo_usuario=conteudo,
            schema=SCHEMA_NAVEGACAO,
            validador=NavegacaoArvore,
            esforco=ctx.esforco_navegador,
            chave_idempotencia=chave_conteudo(f"arvore-{nivel}", ctx.modelo_navegador, prompt.rotulo, conteudo),
            org_id=ctx.org_id,
            audit_id=ctx.audit_id,
            item_id=uuid.UUID(state.item_id),
            max_tokens=4000,
        )
        try:
            res = _executar(req, ctx)
        except (gateway.ChaveAPIAusente, gateway.IAIndisponivel):
            raise
        except gateway.FalhaIA as e:
            log.warning("navegacao_falhou", item=state.item_id, nivel=nivel, erro=str(e))
            falhas.append(str(e))
            return None
        r = NavegacaoArvore.model_validate(res.dados)
        validos = {o["codigo"] for o in opcoes}
        if r.escolha not in validos:
            r.escolha = None
        r.alternativas = [a for a in r.alternativas if a.codigo in validos and a.codigo != r.escolha][:2]
        registro.append(
            {"nivel": nivel, "escolha": r.escolha, "confianca": r.confianca, "justificativa": r.justificativa}
        )
        return r

    def descer(raiz: dict[str, Any], registro: list[dict[str, Any]], hipotese: str | None = None) -> _Descida:
        """Da raiz escolhida (capítulo) até o código final."""
        caminho = [{"codigo": raiz["codigo"], "descricao": raiz["descricao"]}]
        with sync_tenant_session(ctx.tenant) as s:
            opcoes = _opcoes(s, fonte, versao, raiz["codigo"])
        for _ in range(7):  # posição → subposições (quantas a tabela tiver) → código
            if not opcoes:
                break
            # Poucos códigos finais sob o nível atual: pergunta direto entre eles.
            with sync_tenant_session(ctx.tenant) as s:
                folhas = _folhas(s, fonte, versao, caminho[-1]["codigo"])
            if len(folhas) <= MAX_FOLHAS_DIRETAS:
                opcoes = folhas
            nivel = "codigo" if all(o["folha"] for o in opcoes) else "posicao"
            resposta = perguntar(nivel, opcoes, caminho, registro, hipotese)
            if resposta is None or resposta.escolha is None:
                break
            escolhido = next(o for o in opcoes if o["codigo"] == resposta.escolha)
            if escolhido["folha"]:
                por_codigo = {o["codigo"]: o for o in opcoes}
                alternativas = [
                    {**por_codigo[a.codigo], "motivo": a.motivo, "rotulo": a.rotulo}
                    for a in resposta.alternativas
                    if por_codigo[a.codigo]["folha"]
                ]
                caminho.append({"codigo": escolhido["codigo"], "descricao": _descricao_folha(escolhido["descricao"])})
                return _Descida(escolhido["codigo"], escolhido["descricao"], resposta.rotulo, alternativas, caminho)
            caminho.append({"codigo": escolhido["codigo"], "descricao": escolhido["descricao"]})
            with sync_tenant_session(ctx.tenant) as s:
                opcoes = _opcoes(s, fonte, versao, escolhido["codigo"])
        return _Descida(caminho=caminho)

    with sync_tenant_session(ctx.tenant) as s:
        raizes = _opcoes(s, fonte, versao, None)
    descida = _Descida()
    inicio = 0
    # Códigos achados nos capítulos alternativos: o item pode ser "de outro jeito" (cru × preparado…).
    outros_capitulos: list[dict[str, Any]] = []
    # Capítulos em dúvida em que nenhum código foi achado: o imposto deles fica desconhecido.
    capitulos_em_aberto: list[str] = []
    primeira = perguntar("capitulo", raizes, [], passos)
    if primeira is not None and primeira.escolha is not None:
        por_raiz = {o["codigo"]: o for o in raizes}
        hipoteses = {a.codigo: a for a in primeira.alternativas}
        # Se o capítulo escolhido não tiver código que sirva, tenta os alternativos, do mais provável ao
        # menos (até 3 no total: ex. café espresso → 22 bebidas, 09 café em grão, 21 preparações).
        tentativas = [primeira.escolha, *(a.codigo for a in primeira.alternativas)][:MAX_CAPITULOS]
        tentados: set[str] = set()
        for n, cap in enumerate(tentativas):
            inicio = len(passos)
            if n > 0:
                passos.append(
                    {
                        "nivel": "capitulo",
                        "escolha": cap,
                        "confianca": primeira.confianca,
                        "justificativa": f"{n + 1}º capítulo tentado: nos anteriores, nenhum código serviu.",
                    }
                )
            tentados.add(cap)
            descida = descer(por_raiz[cap], passos)
            if descida.codigo:
                break
        # Dúvida real entre capítulos: procura também o código de cada capítulo alternativo ainda não visto.
        # Se os impostos forem diferentes, a avaliação pergunta ao operador o que o item é, em vez de mandar
        # para o contador (ADR 0029).
        if descida.codigo and primeira.confianca < CERTEZA_CAPITULO_UNICO:
            for cap in tentativas:
                if cap in tentados:
                    continue
                hip = hipoteses[cap]
                passos_hip: list[dict[str, Any]] = []
                outra = descer(por_raiz[cap], passos_hip, hipotese=hip.motivo or hip.rotulo)
                if not outra.codigo:
                    capitulos_em_aberto.append(cap)
                    continue
                outros_capitulos.append(
                    {
                        "codigo": outra.codigo,
                        "descricao": outra.descricao,
                        "motivo": hip.motivo,
                        # O rótulo dado na escolha do capítulo mostra o que separa as opções (cru × preparado);
                        # o do código final tende a repetir o nome do item.
                        "rotulo": hip.rotulo or outra.rotulo,
                        "capitulo": cap,
                        "passos": passos_hip,
                    }
                )

    codigo = descida.codigo
    alternativas_folhas = [*outros_capitulos, *descida.alternativas]
    rotulo = descida.rotulo
    if outros_capitulos and primeira is not None and primeira.rotulo:
        rotulo = primeira.rotulo  # a pergunta é entre capítulos: vale o rótulo que os contrasta
    # Certeza do caminho que deu certo (a partir do capítulo em que o código foi achado).
    caminho_certo = [passos[0], *passos[inicio:]] if passos else []
    confianca = min((p["confianca"] for p in caminho_certo), default=0.0)
    with sync_tenant_session(ctx.tenant) as s:
        leque = _folhas(s, fonte, versao, codigo[:4]) if codigo else []
    vistos = {o["codigo"] for o in leque}
    leque += [
        {"codigo": o["codigo"], "descricao": o["descricao"]} for o in outros_capitulos if o["codigo"] not in vistos
    ]
    candidatos = [
        {
            "tipo_codigo": fonte,
            "codigo": o["codigo"],
            "descricao_completa": o["descricao"],
            "rank_semantico": None,
            "rank_textual": None,
            "score": 0.0,
            "posicao": i,
            "codigo_atual": False,
        }
        for i, o in enumerate(leque, start=1)
    ]
    arvore = {
        "tipo_codigo": fonte,
        "codigo": codigo,
        "codigo_formatado": formatar_codigo(fonte, codigo) if codigo else None,
        "confianca": round(confianca, 3),
        "justificativa": passos[-1]["justificativa"] if passos else "",
        "rotulo": rotulo,
        "caminho": descida.caminho,
        "passos": passos,
        "erro": falhas[-1] if falhas and not codigo else None,
        "modelo": ctx.modelo_navegador,
        "alternativas": [
            {
                "codigo": a["codigo"],
                "codigo_formatado": formatar_codigo(fonte, a["codigo"]),
                "descricao": _descricao_folha(a["descricao"]),
                "motivo": a.get("motivo", ""),
                "rotulo": a.get("rotulo", ""),
                **({"capitulo": a["capitulo"]} if a.get("capitulo") else {}),
            }
            for a in alternativas_folhas
        ],
        **(
            {
                "outros_capitulos": [
                    {"capitulo": o["capitulo"], "codigo": o["codigo"], "passos": o["passos"]} for o in outros_capitulos
                ]
            }
            if outros_capitulos
            else {}
        ),
        **({"capitulos_em_aberto": capitulos_em_aberto} if capitulos_em_aberto else {}),
    }
    saida: dict[str, Any] = {"arvore": arvore}
    if candidatos:
        # A prova passa a ter os códigos oficiais da posição encontrada (mostrados na revisão com "Usar").
        existentes = {c["codigo"] for c in candidatos}
        saida["candidatos"] = candidatos + [c for c in state.candidatos if c["codigo"] not in existentes]
    return saida
