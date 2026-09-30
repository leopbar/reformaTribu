"""Caminho de um item pelos agentes: por quais caixas passou, quais pulou e o que cada uma fez.

Função pura: recebe um `Registro` (montado a partir do item gravado ou, durante o processamento,
do checkpoint do grafo) e devolve a lista de passos na ordem do roteiro (`graph.py`). As rotas
reproduzem as arestas condicionais do grafo; se o grafo mudar, este módulo muda junto.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.codes import formatar_codigo

# Ordem das caixas por item (as da planilha inteira ficam na visão geral da auditoria).
ORDEM = [
    "arrumador",
    "fiscal",
    "arquivista",
    "pesquisador",
    "identificador",
    "segundo_parecer",
    "navegador",
    "jurista",
    "leitor",
    "juiz",
    "secretario",
]

# Etapa gravada pelo grafo (`AuditItem.etapa`) → caixa.
ETAPA_CAIXA = {
    "normalizar": "arrumador",
    "validar_estrutura": "fiscal",
    "buscar_memoria": "arquivista",
    "recuperar_candidatos": "pesquisador",
    "julgar_coerencia": "identificador",
    "escalar": "segundo_parecer",
    "navegar_arvore": "navegador",
    "investigar": "jurista",
    "levantar_fatos": "leitor",
}

# Nó da chamada de IA (`LlmCall.no`) → caixa.
NO_CAIXA = {
    "expandir_abreviacoes": "arrumador",
    "julgar_coerencia": "identificador",
    "escalar": "segundo_parecer",
    "navegar_arvore": "navegador",
    "investigar_enquadramento": "jurista",
    "extrair_fatos": "leitor",
}

ALARMES = {
    "baixa_confianca": "certeza abaixo do limite",
    "codigo_atual_incoerente": "o NCM do ERP não combina com a descrição",
    "sem_codigo_atual_valido": "o ERP não trouxe um código válido",
    "divergencia_busca_julgamento": "a IA escolheu um código que as buscas quase não consideraram",
    "sinais_de_duvida": "a IA registrou dúvidas",
}

STATUS_FINAIS = {"classificado", "aguardando_informacao", "revisao_contador", "revisao_especialista", "erro"}


@dataclass
class Registro:
    """Tudo o que se sabe da viagem do item (gravado ou ainda em andamento)."""

    descricao: str
    status: str
    data_referencia: str = ""
    marca: str | None = None
    descricao_normalizada: str | None = None
    expansoes: list[dict[str, Any]] = field(default_factory=list)
    tipo: str | None = None
    estrutura: dict[str, Any] = field(default_factory=dict)
    motivos: list[str] = field(default_factory=list)
    base_incompleta: bool = False
    memoria: dict[str, Any] | None = None
    confirmado_sem_ia: bool = False
    posicao_confirmacao: int | None = None
    candidatos: list[dict[str, Any]] = field(default_factory=list)
    candidatos_conhecidos: bool = True  # durante o processamento, a lista só existe depois do Pesquisador
    julgamento: dict[str, Any] | None = None
    julgamento_valido: bool | None = None
    gatilhos: list[str] = field(default_factory=list)
    escalonamento: dict[str, Any] | None = None
    identidade: dict[str, Any] = field(default_factory=dict)
    arvore: dict[str, Any] | None = None
    tese: dict[str, Any] | None = None
    tese_falha: str | None = None
    fatos_lidos: list[dict[str, Any]] = field(default_factory=list)
    sugestoes: dict[str, Any] = field(default_factory=dict)
    fatos_conhecidos: list[dict[str, Any]] = field(default_factory=list)
    hipotese: str | None = None
    cclasstrib: str | None = None
    cst: str | None = None
    conclusao: str | None = None
    dimensoes: dict[str, dict[str, Any]] = field(default_factory=dict)
    perguntas: list[dict[str, Any]] = field(default_factory=list)
    aprovado_automaticamente: bool = False
    erro: str | None = None
    caixa_atual: str | None = None  # em processamento: a caixa em que o item está agora
    aguardando_lote: bool = False
    chamadas: dict[str, dict[str, Any]] = field(default_factory=dict)  # caixa → chamada de IA


@dataclass
class Passo:
    caixa: str
    situacao: str  # feito | pulado | atual | aguardando | falhou
    resumo: str
    detalhes: list[dict[str, str]] = field(default_factory=list)
    ia: dict[str, Any] | None = None
    proximo: str | None = None

    def como_dict(self) -> dict[str, Any]:
        return {
            "caixa": self.caixa,
            "situacao": self.situacao,
            "resumo": self.resumo,
            "detalhes": self.detalhes,
            "ia": self.ia,
            "proximo": self.proximo,
        }


def _pct(v: Any) -> str:
    try:
        return f"{round(float(v) * 100)}%"
    except (TypeError, ValueError):
        return "—"


def _fmt(tipo: str | None, codigo: str | None) -> str:
    return formatar_codigo(tipo or "ncm", codigo) if codigo else "—"


def _ultimo_nivel(desc: str | None) -> str:
    """Os dois últimos níveis da hierarquia oficial ("Feijão comum › Outros"): o último sozinho diz pouco."""
    return " › ".join((desc or "").split(" › ")[-2:])


def _julgamento_valido(r: Registro) -> bool:
    if r.julgamento_valido is not None:
        return r.julgamento_valido
    j = r.julgamento or {}
    return bool(j) and not j.get("_descartado")


def rota(r: Registro) -> list[str]:
    """Caixas visitadas, na ordem, seguindo as mesmas decisões do grafo."""
    caminho = ["arrumador", "fiscal"]
    if r.base_incompleta:
        caminho.append("juiz")
    else:
        caminho.append("arquivista")
        if r.memoria:
            caminho.append("jurista")
        else:
            caminho.append("pesquisador")
            if r.confirmado_sem_ia:
                caminho.append("jurista")
            else:
                identificou = (
                    bool(r.julgamento)
                    or r.julgamento_valido is not None
                    or (bool(r.candidatos) and r.arvore is None)
                    or not r.candidatos_conhecidos
                )
                valido = _julgamento_valido(r)
                if identificou:
                    caminho.append("identificador")
                    if valido and (r.gatilhos or r.escalonamento):
                        caminho.append("segundo_parecer")
                if r.arvore is not None:
                    caminho.append("navegador")
                    caminho.append("jurista" if r.arvore.get("codigo") else "juiz")
                elif not identificou or (r.julgamento and not valido):
                    caminho.append("juiz")  # itens de antes da busca guiada: sem código, direto ao Juiz
                else:
                    caminho.append("jurista")
        if caminho[-1] == "jurista":
            if r.tese:
                caminho.append("leitor")
            caminho.append("juiz")
    if r.perguntas:
        caminho.append("secretario")
    return caminho


def montar(r: Registro) -> list[Passo]:
    visitadas = rota(r)
    em_andamento = r.status not in STATUS_FINAIS
    atual = r.caixa_atual if em_andamento else None
    if em_andamento and atual is None:
        atual = "arrumador"
    if atual is not None and atual in visitadas:
        visitadas = visitadas[: visitadas.index(atual)]
    elif atual is not None:
        # O grafo foi por um caminho que o registro parcial ainda não explica: confia na etapa gravada.
        visitadas = [c for c in visitadas if ORDEM.index(c) < ORDEM.index(atual)]
    ultima = max((ORDEM.index(c) for c in visitadas), default=-1)
    if atual is not None:
        ultima = max(ultima, ORDEM.index(atual))

    passos: list[Passo] = []
    for caixa in ORDEM:
        if caixa == atual:
            p = Passo(caixa, "atual", _resumo_atual(r, caixa))
        elif caixa in visitadas:
            p = _feito(r, caixa)
        elif ORDEM.index(caixa) < ultima or not em_andamento:
            p = Passo(caixa, "pulado", _motivo_pulo(r, caixa, visitadas))
        else:
            p = Passo(caixa, "aguardando", "Ainda não chegou aqui.")
        if caixa in visitadas:
            i = visitadas.index(caixa)
            p.proximo = visitadas[i + 1] if i + 1 < len(visitadas) else (atual if em_andamento else "resultado")
        if caixa in r.chamadas and p.situacao in ("feito", "atual", "falhou"):
            p.ia = r.chamadas[caixa]
        passos.append(p)
    return passos


def _resumo_atual(r: Registro, caixa: str) -> str:
    if r.aguardando_lote:
        return "Pergunta enviada à IA em lote; aguardando a resposta (pode levar alguns minutos ou horas)."
    return {
        "arrumador": "Arrumando a descrição agora…",
        "fiscal": "Conferindo o NCM do ERP na tabela oficial agora…",
        "arquivista": "Procurando no caderno de itens aprovados agora…",
        "pesquisador": "Separando os NCMs possíveis agora…",
        "identificador": "A IA está escolhendo o NCM agora…",
        "segundo_parecer": "O segundo parecer está conferindo agora…",
        "navegador": "Descendo pela tabela oficial (capítulo → posição → código) agora…",
        "jurista": "Estudando a lei para esta família agora (ou esperando outro item da mesma família)…",
        "leitor": "Lendo a descrição em busca dos fatos agora…",
        "juiz": "Aplicando o parecer e montando o boletim agora…",
        "secretario": "Organizando as perguntas agora…",
    }[caixa]


def _motivo_pulo(r: Registro, caixa: str, visitadas: list[str]) -> str:
    depois_do_fiscal = ("arquivista", "pesquisador", "identificador", "segundo_parecer", "jurista", "leitor")
    if r.base_incompleta and caixa in depois_do_fiscal:
        return "Pulado: a base oficial (tabela ou lei) não estava importada, então o item foi direto ao Juiz."
    if r.memoria and caixa in ("pesquisador", "identificador", "segundo_parecer"):
        return "Pulado: o item já estava no caderno de aprovados, então o NCM já era conhecido."
    if r.confirmado_sem_ia and caixa in ("identificador", "segundo_parecer"):
        return "Pulado: o NCM do ERP ficou em 1º lugar nas duas buscas, então foi confirmado sem IA."
    sem_alternativas = "pesquisador" in visitadas and not r.candidatos
    if caixa in ("identificador", "segundo_parecer", "jurista", "leitor") and sem_alternativas:
        return "Pulado: a busca não encontrou nenhum NCM possível."
    if caixa == "navegador":
        return "Pulado: o item já tinha um código definido; a busca guiada só entra quando falta o NCM."
    if caixa == "segundo_parecer":
        if "identificador" in visitadas and not _julgamento_valido(r):
            return "Pulado: a resposta do Identificador foi descartada, então o item foi ao Juiz."
        return "Pulado: nenhum alarme tocou; a resposta do Identificador foi aceita."
    if caixa in ("jurista", "leitor") and "identificador" in visitadas and not _julgamento_valido(r):
        return "Pulado: sem NCM confiável não há lei a estudar."
    if caixa == "leitor":
        if r.tese_falha:
            return "Pulado: o estudo da lei não foi concluído."
        return "Pulado: sem NCM definido não há parecer para aplicar."
    if caixa == "secretario":
        return "Nenhuma pergunta foi necessária para este item."
    return "Pulado."


def _feito(r: Registro, caixa: str) -> Passo:
    return {
        "arrumador": _arrumador,
        "fiscal": _fiscal,
        "arquivista": _arquivista,
        "pesquisador": _pesquisador,
        "identificador": _identificador,
        "segundo_parecer": _segundo_parecer,
        "navegador": _navegador,
        "jurista": _jurista,
        "leitor": _leitor,
        "juiz": _juiz,
        "secretario": _secretario,
    }[caixa](r)


def _arrumador(r: Registro) -> Passo:
    d: list[dict[str, str]] = [{"rotulo": "Descrição do ERP", "valor": r.descricao}]
    if r.descricao_normalizada:
        d.append({"rotulo": "Descrição arrumada", "valor": r.descricao_normalizada})
    if r.marca:
        d.append({"rotulo": "Marca retirada", "valor": r.marca})
    for e in r.expansoes:
        d.append(
            {
                "rotulo": "Abreviação traduzida",
                "valor": f"{e.get('abreviacao', '?')} → {e.get('expansao', '?')}",
            }
        )
    if r.tipo:
        palpite = {"produto": "produto", "servico": "serviço"}.get(r.tipo, "não sei ainda")
        d.append({"rotulo": "Palpite", "valor": palpite})
    resumo = f"“{r.descricao}” → “{r.descricao_normalizada}”" if r.descricao_normalizada else "Descrição arrumada."
    return Passo("arrumador", "feito", resumo, d)


def _fiscal(r: Registro) -> Passo:
    if r.base_incompleta:
        return Passo(
            "fiscal",
            "falhou",
            "A tabela oficial ou o texto da lei não estão importados: não há como conferir nem estudar.",
            [{"rotulo": "O que fazer", "valor": "Importe a base oficial em Base de referência e reanalise."}],
        )
    atual = r.estrutura.get("codigo_atual") or {}
    cod = atual.get("codigo")
    tipo = atual.get("tipo") or "ncm"
    d: list[dict[str, str]] = []
    if not cod:
        resumo = "O ERP não informou NCM nem NBS. O sistema vai procurar um pela descrição."
    elif atual.get("provavel"):
        provavel = _fmt(tipo, atual["provavel"])
        resumo = f"{cod} tem 7 dígitos: provavelmente o Excel apagou o zero da frente ({provavel})."
        d.append({"rotulo": "Provável código", "valor": f"{provavel} · {atual.get('descricao_provavel') or ''}"})
    elif not atual.get("existe"):
        resumo = f"{_fmt(tipo, cod)} não existe na tabela oficial."
    elif not atual.get("folha"):
        resumo = f"{_fmt(tipo, cod)} existe, mas está incompleto (não chega ao último nível)."
    elif atual.get("vigente") is False:
        resumo = f"{_fmt(tipo, cod)} existe, mas não vale em {r.data_referencia}."
    else:
        nome = _ultimo_nivel(atual.get("descricao_completa"))
        resumo = f"{_fmt(tipo, cod)} existe e vale em {r.data_referencia}: {nome}."
    if atual.get("descricao_completa"):
        d.append({"rotulo": "Nome oficial do código do ERP", "valor": atual["descricao_completa"]})
    d.append(
        {
            "rotulo": "Atenção",
            "valor": "O Fiscal só confere se o código existe e vale. Se ele combina com a descrição, "
            "quem decide é o Identificador.",
        }
    )
    return Passo("fiscal", "feito", resumo, d)


def _arquivista(r: Registro) -> Passo:
    if r.memoria:
        m = r.memoria
        return Passo(
            "arquivista",
            "feito",
            f"Achou! Este item já foi aprovado por uma pessoa com o {_fmt(m.get('tipo_codigo'), m.get('codigo'))}. "
            "Pula a identificação e vai direto ao Jurista.",
            [
                {
                    "rotulo": "Código aprovado",
                    "valor": f"{_fmt(m.get('tipo_codigo'), m.get('codigo'))} · {m.get('descricao_completa') or ''}",
                },
                *([{"rotulo": "Aprovado em", "valor": str(m["aprovado_em"])[:10]}] if m.get("aprovado_em") else []),
            ],
        )
    return Passo(
        "arquivista",
        "feito",
        "Não achou no caderno de itens aprovados desta empresa. Segue para o Pesquisador.",
        [
            {
                "rotulo": "Como procura",
                "valor": "Pela descrição arrumada (o código de barras só vale se a descrição também bater).",
            }
        ],
    )


def _pesquisador(r: Registro) -> Passo:
    cands = sorted(r.candidatos, key=lambda c: c.get("posicao") or 99)
    atual = next((c for c in cands if c.get("codigo_atual")), None)
    d: list[dict[str, str]] = []
    if atual is not None:
        sem, txt = atual.get("rank_semantico"), atual.get("rank_textual")
        d.append(
            {
                "rotulo": "NCM do ERP nas buscas",
                "valor": f"busca por palavras: {f'{txt}º lugar' if txt else 'não achou'} · "
                f"busca pelo sentido: {f'{sem}º lugar' if sem else 'não achou'}",
            }
        )
    for c in cands[:6]:
        origem = []
        if c.get("rank_textual"):
            origem.append(f"palavras {c['rank_textual']}º")
        if c.get("rank_semantico"):
            origem.append(f"sentido {c['rank_semantico']}º")
        if not origem:
            origem.append("NCM do ERP" if c.get("codigo_atual") else "irmão do NCM do ERP")
        d.append(
            {
                "rotulo": _fmt(c.get("tipo_codigo"), c.get("codigo")),
                "valor": f"{_ultimo_nivel(c.get('descricao_completa'))} ({', '.join(origem)})",
            }
        )
    if len(cands) > 6:
        d.append({"rotulo": "…", "valor": f"mais {len(cands) - 6} alternativas"})
    if r.confirmado_sem_ia:
        resumo = (
            f"Montou {len(cands)} alternativas. Atalho: o NCM do ERP ficou em 1º lugar nas duas buscas, "
            "então foi confirmado sem gastar com IA."
        )
    elif not cands:
        resumo = "Não encontrou nenhum NCM possível na tabela oficial. Sem alternativas, o item vai ao Juiz."
    else:
        resumo = f"Montou uma prova com {len(cands)} alternativas oficiais para o Identificador escolher."
    return Passo("pesquisador", "feito", resumo, d)


def _parecer(j: dict[str, Any]) -> list[dict[str, str]]:
    d: list[dict[str, str]] = []
    if j.get("justificativa"):
        d.append({"rotulo": "Justificativa", "valor": str(j["justificativa"])})
    if j.get("ncm_atual_coerente") is not None:
        d.append({"rotulo": "NCM do ERP combina?", "valor": "sim" if j["ncm_atual_coerente"] else "não"})
    if j.get("descricao_suficiente") is False:
        d.append({"rotulo": "Descrição", "valor": "insuficiente para decidir com segurança"})
    for s in j.get("sinais_de_duvida") or []:
        d.append({"rotulo": "Dúvida", "valor": str(s)})
    if j.get("_descartado"):
        d.append({"rotulo": "Resposta descartada", "valor": str(j["_descartado"])})
    return d


def _identificador(r: Registro) -> Passo:
    j = r.julgamento or {}
    tipo = r.identidade.get("tipo_codigo") or "ncm"
    if not _julgamento_valido(r):
        motivo = j.get("_descartado") or "a IA não conseguiu responder"
        return Passo("identificador", "falhou", f"Resposta descartada: {motivo}.", _parecer(j))
    if j.get("codigo_sugerido"):
        resumo = f"Escolheu {_fmt(tipo, j['codigo_sugerido'])} com {_pct(j.get('confianca'))} de certeza."
    else:
        resumo = f"Respondeu que nenhuma alternativa serve ({_pct(j.get('confianca'))} de certeza)."
    d = _parecer(j)
    if r.gatilhos:
        resumo += f" Tocaram {len(r.gatilhos)} alarme(s): pede segundo parecer."
        for g in r.gatilhos:
            d.append({"rotulo": "Alarme", "valor": ALARMES.get(g, g)})
    else:
        resumo += " Nenhum alarme tocou."
    return Passo("identificador", "feito", resumo, d)


def _segundo_parecer(r: Registro) -> Passo:
    e = r.escalonamento or {}
    j = r.julgamento or {}
    tipo = r.identidade.get("tipo_codigo") or "ncm"
    if not e:
        return Passo("segundo_parecer", "falhou", "O segundo parecer não pôde ser concluído.")
    if e.get("_descartado"):
        return Passo("segundo_parecer", "falhou", f"Resposta descartada: {e['_descartado']}.", _parecer(e))
    concorda = e.get("codigo_sugerido") == j.get("codigo_sugerido")
    if e.get("codigo_sugerido"):
        veredito = "Concordou" if concorda else "Discordou"
        resumo = f"{veredito}: {_fmt(tipo, e['codigo_sugerido'])} com {_pct(e.get('confianca'))} de certeza."
    else:
        resumo = f"Concluiu que nenhuma alternativa serve ({_pct(e.get('confianca'))} de certeza)."
    d = _parecer(e)
    d.append(
        {
            "rotulo": "Quem vale",
            "valor": "O NCM final é o do segundo parecer; a certeza final mistura 40% do Identificador "
            "e 60% do segundo parecer.",
        }
    )
    return Passo("segundo_parecer", "feito", resumo, d)


def _navegador(r: Registro) -> Passo:
    a = r.arvore or {}
    caminho = " › ".join(f"{c.get('codigo')} {c.get('descricao', '')[:60]}" for c in a.get("caminho", []))
    d: list[dict[str, str]] = []
    for p in a.get("passos", []):
        d.append(
            {
                "rotulo": f"Nível {p.get('nivel')}",
                "valor": f"escolheu {p.get('escolha') or 'nenhuma opção'} ({_pct(p.get('confianca'))}) · "
                f"{p.get('justificativa', '')}",
            }
        )
    for alt in a.get("alternativas", []):
        d.append(
            {
                "rotulo": f"Alternativa {alt.get('codigo_formatado')}",
                "valor": f"{alt.get('descricao')} · {alt.get('motivo')}",
            }
        )
    if a.get("codigo"):
        resumo = (
            f"Sem NCM, desceu pela tabela oficial e sugeriu {a.get('codigo_formatado')} "
            f"({_pct(a.get('confianca'))} de certeza). O contador confirma."
        )
        if caminho:
            d.insert(0, {"rotulo": "Caminho na árvore", "valor": caminho})
        return Passo("navegador", "feito", resumo, d)
    if a.get("erro"):
        return Passo("navegador", "falhou", f"A busca guiada não pôde ser feita: {a['erro']}", d)
    return Passo("navegador", "falhou", "Desceu pela tabela oficial, mas nenhuma opção descreve o item.", d)


def _jurista(r: Registro) -> Passo:
    t = r.tese
    if t is None:
        if r.tese_falha:
            return Passo("jurista", "falhou", r.tese_falha)
        return Passo("jurista", "pulado", "Sem NCM definido, não havia família para estudar.")
    hips = t.get("hipoteses") or []
    origem = (
        "Parecer reaproveitado de uma auditoria anterior: não custou nada."
        if t.get("reaproveitada")
        else f"Parecer escrito nesta auditoria e compartilhado por {t.get('itens_familia', 1)} item(ns) da família."
    )
    resumo = f"Família {t.get('codigo')}: {len(hips)} hipótese(s). {origem}"
    d: list[dict[str, str]] = []
    if t.get("entendimento"):
        d.append({"rotulo": "Entendimento", "valor": str(t["entendimento"])})
    for h in hips:
        conds = ", ".join(
            f"{c.get('fato', '').replace('_', ' ')} = {c.get('valor_exigido')}" for c in h.get("condicoes", [])
        )
        d.append(
            {
                "rotulo": f"{h.get('id')} · cClassTrib {h.get('cclasstrib')}",
                "valor": f"{h.get('titulo')}" + (f" (se {conds})" if conds else " (sem condições)"),
            }
        )
    for f in t.get("fatos_necessarios") or []:
        d.append({"rotulo": "Pergunta necessária", "valor": str(f.get("pergunta") or f.get("fato"))})
    return Passo("jurista", "feito", resumo, d)


def _leitor(r: Registro) -> Passo:
    d: list[dict[str, str]] = []
    for f in r.fatos_conhecidos:
        d.append(
            {
                "rotulo": "Já sabido",
                "valor": f"{str(f.get('atributo', '')).replace('_', ' ')} = {f.get('valor')} "
                f"({f.get('origem_rotulo') or f.get('origem')})",
            }
        )
    for f in r.fatos_lidos:
        d.append(
            {
                "rotulo": "Lido na descrição (fato)",
                "valor": f"{str(f.get('atributo', '')).replace('_', ' ')} = {f.get('valor')}"
                + (f" · “{f['evidencia']}”" if f.get("evidencia") else ""),
            }
        )
    for k, s in r.sugestoes.items():
        d.append(
            {
                "rotulo": "Palpite (só sugestão)",
                "valor": f"{k.replace('_', ' ')} = {s.get('valor')}"
                + (f" · {s['evidencia']}" if s.get("evidencia") else ""),
            }
        )
    if "leitor" not in r.chamadas and not r.fatos_lidos and not r.sugestoes:
        resumo = "Nada a ler: o parecer não depende de fatos do item, ou eles já eram conhecidos. Não chamou a IA."
    else:
        partes = []
        if r.fatos_lidos:
            partes.append(f"{len(r.fatos_lidos)} fato(s) escrito(s) na descrição")
        if r.sugestoes:
            partes.append(f"{len(r.sugestoes)} palpite(s) que viram só sugestão")
        resumo = "Leu a descrição: " + (" e ".join(partes) if partes else "não encontrou as respostas") + "."
    return Passo("leitor", "feito", resumo, d)


ROTULO_STATUS = {
    "classificado": "Classificado",
    "aguardando_informacao": "Aguardando informação",
    "revisao_contador": "Revisão do contador",
    "revisao_especialista": "Revisão do especialista",
    "erro": "Erro",
}
ROTULO_DIMENSAO = {"ok": "OK", "atencao": "Atenção", "pendente": "Pendente", "falha": "Falha", "na": "Não se aplica"}


def _juiz(r: Registro) -> Passo:
    if r.status == "erro":
        return Passo("juiz", "falhou", f"O processamento terminou com erro: {r.erro or 'falha desconhecida'}.")
    destino = ROTULO_STATUS.get(r.status, r.status)
    if r.cclasstrib:
        resumo = f"Aplicou {r.hipotese or 'a hipótese'} → cClassTrib {r.cclasstrib}"
        resumo += f" / CST {r.cst}" if r.cst else ""
        resumo += f". Resultado: {destino}."
    else:
        resumo = f"Não conseguiu fechar o enquadramento. Resultado: {destino}."
    if r.status == "classificado" and r.aprovado_automaticamente:
        resumo += " Aprovado automaticamente."
    d: list[dict[str, str]] = []
    if r.conclusao:
        d.append({"rotulo": "Conclusão", "valor": r.conclusao})
    for chave, dim in r.dimensoes.items():
        sit = dim.get("situacao", "")
        if sit and sit != "na":
            d.append(
                {
                    "rotulo": f"Nota · {dim.get('rotulo') or chave}",
                    "valor": f"{ROTULO_DIMENSAO.get(sit, sit)}" + (f" — {dim['texto']}" if dim.get("texto") else ""),
                }
            )
    return Passo("juiz", "feito", resumo, d)


def _secretario(r: Registro) -> Passo:
    d = [{"rotulo": p.get("grupo") or "Pergunta", "valor": str(p.get("pergunta") or "")} for p in r.perguntas]
    return Passo(
        "secretario",
        "feito",
        f"Enviou {len(r.perguntas)} pergunta(s) para a aba Perguntas. Quando alguém responder, "
        "o item volta só ao Juiz, sem IA.",
        d,
    )
