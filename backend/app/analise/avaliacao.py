"""Avaliação de um item: aplica a tese da família aos fatos do item (função pura, testável).

1. Percorre as hipóteses na ordem de precedência: primeiro os regimes decididos pela operação (bares e
   restaurantes, farmácia de manipulação — `operacao.py`, valem mesmo sem NCM), depois as da tese da
   família do produto (específica → regra geral).
   - condição com fato conhecido e diferente do exigido, ou exceção confirmada → hipótese afastada;
   - todas as condições confirmadas e exceções descartadas → hipótese escolhida;
   - falta um fato → a hipótese continua possível: se as alternativas que restam levam a
     enquadramentos diferentes, nasce uma pergunta ("se A → X, se B → Y").
2. Monta o relatório de confiança por dimensão, sem número mágico.
3. Decide o status e o nível de revisão.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from app.analise.fatos import DESCONHECIDO, chave, valor
from app.analise.operacao import ORIGEM as ORIGEM_OPERACAO
from app.analise.operacao import cclasstrib_da_operacao
from app.core.codes import formatar_codigo
from app.models.enums import NivelRevisao, StatusItem

OK, ATENCAO, PENDENTE, FALHA, NA = "ok", "atencao", "pendente", "falha", "nao_aplicavel"

DIMENSOES: tuple[tuple[str, str], ...] = (
    ("identificacao", "Identificação do item"),
    ("codigo_fiscal", "NCM/NBS"),
    ("contexto", "Contexto comercial"),
    ("regra", "Regra jurídica"),
    ("condicoes", "Condições legais"),
    ("excecoes", "Exceções"),
    ("cclasstrib", "cClassTrib"),
    ("fonte", "Fonte oficial"),
    ("conflito", "Conflito normativo"),
    ("imposto_seletivo", "Imposto Seletivo"),
)
ROTULOS = dict(DIMENSOES)
_CCLASSTRIB_OPERACAO = cclasstrib_da_operacao()


@dataclass
class Dimensao:
    chave: str
    situacao: str
    texto: str

    def como_dict(self) -> dict[str, str]:
        return {"rotulo": ROTULOS.get(self.chave, self.chave), "situacao": self.situacao, "texto": self.texto}


@dataclass
class PerguntaNecessaria:
    atributo: str
    escopo: str  # empresa | item
    pergunta: str
    opcoes: list[dict[str, str]]
    motivo: str
    nivel: str = NivelRevisao.OPERACIONAL
    sugestao: dict[str, str] | None = None


@dataclass
class EntradaAvaliacao:
    identidade: dict[str, Any]
    tese: dict[str, Any] | None
    cclasstrib: dict[str, dict[str, Any]]
    refs: dict[str, dict[str, Any]]
    fatos: dict[str, dict[str, Any]]
    correlacionados: list[str] = field(default_factory=list)
    precedentes: list[dict[str, Any]] = field(default_factory=list)
    alertas: list[dict[str, Any]] = field(default_factory=list)
    sugestoes: dict[str, dict[str, str]] = field(default_factory=dict)
    tese_falha: str | None = None
    base_incompleta: bool = False
    is_exige_analise: bool = True
    tese_aprovada: bool = False
    # Códigos alternativos citados na dúvida de identificação → "cClassTrib|IS" que teriam
    # (None = não dá para saber sem investigar). Serve para saber se a dúvida muda o imposto.
    tratamento_alternativas: dict[str, str | None] = field(default_factory=dict)
    # Produtos que um anexo da lei nomeia com outro código (checagem cruzada com os anexos).
    produtos_na_lei: list[dict[str, Any]] = field(default_factory=list)
    # Regimes decididos pela operação (ADR 0026): hipóteses avaliadas antes das do produto, com as
    # perguntas que as decidem. As referências e os cClassTrib deles já vêm em `refs` e `cclasstrib`.
    operacao: list[dict[str, Any]] = field(default_factory=list)
    operacao_fatos: list[dict[str, Any]] = field(default_factory=list)
    operacao_afastada: list[str] = field(default_factory=list)  # "regime: motivo" (vale para a empresa toda)


@dataclass
class Avaliacao:
    status: str
    nivel: str | None
    confianca_global: str
    hipotese: str | None = None
    cclasstrib: str | None = None
    cst: str | None = None
    perc_red_ibs: float | None = None
    perc_red_cbs: float | None = None
    tratamento: str | None = None
    conclusao: str = ""
    is_situacao: str | None = None
    dimensoes: list[Dimensao] = field(default_factory=list)
    perguntas: list[PerguntaNecessaria] = field(default_factory=list)
    fatos_usados: list[dict[str, Any]] = field(default_factory=list)
    fundamentos: list[dict[str, Any]] = field(default_factory=list)
    motivos: list[str] = field(default_factory=list)
    hipoteses_avaliadas: list[dict[str, Any]] = field(default_factory=list)

    def dimensoes_dict(self) -> dict[str, dict[str, str]]:
        return {d.chave: d.como_dict() for d in self.dimensoes}

    def perguntas_dict(self) -> list[dict[str, Any]]:
        return [asdict(p) for p in self.perguntas]


# ---------------------------------------------------------------------------- hipóteses --
@dataclass
class _Resultado:
    situacao: str  # escolhida | afastada | possivel
    faltando: list[str]
    motivo: str
    usados: list[str]


def _valor_fato(fatos: dict[str, dict[str, Any]], f: str) -> str:
    registro = fatos.get(chave(f))
    return valor(registro.get("valor")) if registro else DESCONHECIDO


def _testar(h: dict[str, Any], fatos: dict[str, dict[str, Any]]) -> _Resultado:
    faltando: list[str] = []
    usados: list[str] = []
    for c in h.get("condicoes", []):
        f = chave(c["fato"])
        v = _valor_fato(fatos, f)
        if v == DESCONHECIDO:
            faltando.append(f)
            continue
        usados.append(f)
        if v != valor(c["valor_exigido"]):
            return _Resultado("afastada", [], f"condição não atendida: {f} = {v}", usados)
    for e in h.get("excecoes", []):
        if not e.get("fato"):
            continue
        f = chave(e["fato"])
        v = _valor_fato(fatos, f)
        if v == DESCONHECIDO:
            faltando.append(f)
            continue
        usados.append(f)
        if e.get("valor_que_exclui") and v == valor(e["valor_que_exclui"]):
            return _Resultado("afastada", [], f"exceção aplicável: {e.get('descricao')}", usados)
    if faltando:
        return _Resultado("possivel", list(dict.fromkeys(faltando)), "depende de fatos não confirmados", usados)
    return _Resultado("escolhida", [], "todas as condições confirmadas", usados)


def escolher(
    hipoteses: list[dict[str, Any]], fatos: dict[str, dict[str, Any]]
) -> tuple[dict[str, Any] | None, list[str], list[dict[str, Any]]]:
    """Devolve (hipótese escolhida | None, fatos que faltam para decidir, avaliação de cada hipótese)."""
    avaliadas: list[dict[str, Any]] = []
    possiveis: list[tuple[dict[str, Any], _Resultado]] = []
    escolhida: dict[str, Any] | None = None
    for h in hipoteses:
        r = _testar(h, fatos)
        avaliadas.append({"id": h["id"], "titulo": h["titulo"], "cclasstrib": h["cclasstrib"], **asdict(r)})
        if r.situacao == "afastada":
            continue
        if r.situacao == "possivel":
            possiveis.append((h, r))
            continue
        escolhida = h
        break
    if escolhida is None and not possiveis:
        return None, [], avaliadas
    if not possiveis:
        return escolhida, [], avaliadas
    # Há hipóteses anteriores ainda possíveis. Se todas levam ao mesmo cClassTrib da escolhida,
    # a informação que falta não muda o enquadramento: não há o que perguntar.
    destinos = {h["cclasstrib"] for h, _ in possiveis} | ({escolhida["cclasstrib"]} if escolhida else set())
    if escolhida is not None and len(destinos) == 1:
        return escolhida, [], avaliadas
    faltando = list(dict.fromkeys(f for _, r in possiveis for f in r.faltando))
    return None, faltando, avaliadas


def _efeitos(
    hipoteses: list[dict[str, Any]],
    fatos: dict[str, dict[str, Any]],
    atributo: str,
    opcoes: list[str],
    sem_destino: str = "nenhuma hipótese se sustenta",
) -> list[dict[str, str]]:
    """Para cada resposta possível, o que o analista concluiria (simulação)."""
    saida = []
    for op in opcoes or ["sim", "nao"]:
        simulado = {**fatos, atributo: {"valor": valor(op), "origem": "simulacao"}}
        h, faltando, _ = escolher(hipoteses, simulado)
        if h is not None:
            efeito = f"{h['titulo']} (cClassTrib {h['cclasstrib']})"
        elif faltando:
            efeito = "ainda depende de: " + ", ".join(f.replace("_", " ") for f in faltando)
        else:
            efeito = sem_destino
        saida.append({"valor": valor(op), "rotulo": rotulo_opcao(op), "efeito": efeito})
    return saida


def rotulo_opcao(op: str) -> str:
    return {"sim": "Sim", "nao": "Não", "não": "Não"}.get(op.strip().lower(), op.strip().capitalize())


# ----------------------------------------------------------------------------- avaliação --
def _identidade(ent: EntradaAvaliacao) -> tuple[Dimensao, Dimensao]:
    idt = ent.identidade or {}
    sit = idt.get("situacao")
    conf = float(idt.get("confianca_modelo") or 0)
    duvidas = idt.get("sinais_de_duvida") or []
    if sit == "nao_confirmado":
        # O NCM do ERP foi mantido só como referência: a IA acha que ele não descreve o item e não achou outro.
        cod = idt.get("codigo_formatado") or idt.get("codigo")
        return (
            Dimensao("identificacao", ATENCAO, (idt.get("entendimento") or "identificação não confirmada")[:300]),
            Dimensao(
                "codigo_fiscal",
                ATENCAO,
                f"NCM do ERP ({cod}) mantido como referência, não confirmado: provavelmente não descreve o item, "
                "e a busca não encontrou código melhor. Confirme ou corrija.",
            ),
        )
    if sit in (None, "indefinido") or not idt.get("codigo"):
        motivo = idt.get("motivo") or "não foi possível identificar o item com segurança"
        return Dimensao("identificacao", FALHA, motivo[:300]), Dimensao("codigo_fiscal", FALHA, "sem código definido")
    concordam = bool(idt.get("segundo_parecer") and idt.get("concordancia"))
    if idt.get("via_arvore"):
        # Código achado pela busca guiada na árvore oficial: um ponto de partida para o contador confirmar.
        cod = idt.get("codigo_formatado") or idt.get("codigo")
        texto = f"NCM/NBS sugerido pela busca na tabela oficial ({cod}); confirme antes de usar"
        situacao = FALHA if conf < 0.4 else ATENCAO
        return (
            Dimensao("identificacao", situacao, (idt.get("entendimento") or texto)[:300]),
            Dimensao("codigo_fiscal", ATENCAO, texto),
        )
    if idt.get("descricao_suficiente") is False:
        d_id = Dimensao(
            "identificacao", ATENCAO, ("descrição incompleta: " + "; ".join(duvidas))[:300] or "descrição incompleta"
        )
    elif sit == "memoria":
        d_id = Dimensao("identificacao", OK, "item já classificado e aprovado antes nesta empresa")
    elif conf >= (0.85 if concordam else 0.9) and idt.get("concordancia", True):
        # Dúvidas registradas pelo modelo que não mudaram o código (dois pareceres concordam) não bloqueiam.
        texto = idt.get("entendimento") or "identificação inequívoca"
        if duvidas:
            texto += " · pontos observados: " + "; ".join(duvidas)
        d_id = Dimensao("identificacao", OK, texto[:300])
    elif conf >= 0.85 and not duvidas:
        d_id = Dimensao("identificacao", OK, idt.get("entendimento") or "identificação inequívoca")
    elif conf >= 0.7:
        d_id = Dimensao("identificacao", ATENCAO, "; ".join(duvidas)[:300] or "pequena ambiguidade na descrição")
    else:
        d_id = Dimensao("identificacao", FALHA, "; ".join(duvidas)[:300] or "identificação com baixa segurança")
    cod = idt.get("codigo_formatado") or idt.get("codigo")
    anterior = idt.get("codigo_anterior_formatado") or idt.get("codigo_anterior")
    if idt.get("corrigido_pela_lei"):
        # O NCM foi trocado pelo código que a lei atribui ao produto: uma pessoa confirma antes de valer.
        return d_id, Dimensao(
            "codigo_fiscal",
            ATENCAO,
            (
                f"NCM {'corrigido de ' + str(anterior) + ' para ' if anterior else 'sugerido: '}{cod}, "
                f"o código que a lei atribui ao produto ({idt['corrigido_pela_lei']}). Confirme a correção."
            )[:300],
        )
    if sit in ("confirmado", "memoria"):
        d_cod = Dimensao("codigo_fiscal", OK, f"{cod} confirmado")
    elif sit == "corrigido":
        if idt.get("concordancia"):
            d_cod = Dimensao("codigo_fiscal", OK, f"corrigido de {anterior} para {cod}; dois pareceres concordam")
        else:
            d_cod = Dimensao("codigo_fiscal", FALHA, f"correção de {anterior} para {cod} sem confirmação")
    elif sit == "sugerido":
        situacao = OK if idt.get("concordancia") else ATENCAO
        d_cod = Dimensao("codigo_fiscal", situacao, f"{cod} sugerido (o cadastro não tinha código válido)")
    else:
        d_cod = Dimensao("codigo_fiscal", ATENCAO, f"{cod}")
    return d_id, d_cod


def _rotulo_ref(r: dict[str, Any], ref: str) -> str:
    if r.get("tipo") == "trecho":
        return f"{r.get('norma') or ''} {r.get('local') or ''}".strip()
    if r.get("tipo") == "correlacao":
        return f"correlação oficial cClassTrib {r.get('cclasstrib')}"
    if r.get("tipo") == "cclasstrib":
        return f"tabela cClassTrib {ref.removeprefix('T')}"
    return f"precedente aprovado ({r.get('dispositivo') or ref})"


def _cclasstrib_citados(conflito: dict[str, Any], ent: EntradaAvaliacao) -> set[str]:
    """cClassTrib que o conflito põe em disputa: os declarados, os das referências e os citados no texto."""
    saida = {str(x) for x in conflito.get("cclasstrib_em_jogo") or []}
    for ref in conflito.get("refs") or []:
        r = ent.refs.get(ref) or {}
        if r.get("cclasstrib"):
            saida.add(str(r["cclasstrib"]))
        elif ref.startswith("T") and ref[1:].isdigit():
            saida.add(ref[1:])
    texto = conflito.get("descricao") or ""
    saida |= {c for c in ent.cclasstrib if c in texto}
    return saida


def _texto_fatos(fatos: dict[str, dict[str, Any]], usados: list[str]) -> str:
    partes = []
    for f in usados:
        r = fatos.get(f)
        if r:
            partes.append(f"{f.replace('_', ' ')} = {r.get('valor')} ({r.get('origem_rotulo') or r.get('origem')})")
    return "; ".join(partes)


def avaliar(ent: EntradaAvaliacao) -> Avaliacao:
    d_id, d_cod = _identidade(ent)
    dims: dict[str, Dimensao] = {"identificacao": d_id, "codigo_fiscal": d_cod}
    motivos: list[str] = []

    if ent.base_incompleta:
        motivos.append("BASE_REFERENCIA_INCOMPLETA")
    tese_produto = ent.tese if not ent.tese_falha else None
    sem_produto = tese_produto is None or not tese_produto.get("hipoteses")
    if sem_produto and not ent.operacao:
        texto = ent.tese_falha or (
            "base de referência incompleta" if ent.base_incompleta else "investigação jurídica não realizada"
        )
        for k in ("contexto", "regra", "condicoes", "excecoes", "cclasstrib", "fonte", "conflito", "imposto_seletivo"):
            dims[k] = Dimensao(k, NA, "")
        dims["regra"] = Dimensao("regra", FALHA if d_id.situacao != FALHA else NA, texto[:300])
        if ent.tese_falha:
            motivos.append("TESE_NAO_CONCLUIDA")
        return _finalizar(Avaliacao(status="", nivel=None, confianca_global=""), dims, motivos)

    # Regimes da operação primeiro; depois as hipóteses do produto (sem as que só a operação decide).
    so_operacao = _CCLASSTRIB_OPERACAO
    produto = [h for h in (tese_produto or {}).get("hipoteses", []) if h.get("cclasstrib") not in so_operacao]
    tese: dict[str, Any] = {
        "imposto_seletivo": None,
        "conflitos": [],
        **(tese_produto or {}),
        "hipoteses": [*ent.operacao, *produto],
        "fatos_necessarios": [*ent.operacao_fatos, *(tese_produto or {}).get("fatos_necessarios", [])],
    }
    hipoteses = tese["hipoteses"]
    escolhida, faltando, avaliadas = escolher(hipoteses, ent.fatos)
    op_escolhida = escolhida is not None and escolhida.get("origem") == ORIGEM_OPERACAO
    necessarios: dict[str, dict[str, Any]] = {}
    for f in tese["fatos_necessarios"]:
        necessarios.setdefault(chave(f["fato"]), f)
    av = Avaliacao(status="", nivel=None, confianca_global="", hipoteses_avaliadas=avaliadas)
    cod_item = (ent.identidade or {}).get("codigo_formatado") or (ent.identidade or {}).get("codigo")
    falta_produto = (
        f"o estudo da lei para o produto ({cod_item}) não foi concluído; reanalise o item"
        if cod_item
        else "o enquadramento pelo produto depende do NCM/NBS, ainda não definido"
    )
    # O efeito de uma resposta aparece numa pergunta que junta vários itens: não cita o código de um só.
    sem_destino = (
        "vale o tratamento do produto (NCM/NBS), que ainda precisa ser estudado"
        if sem_produto
        else "nenhuma hipótese se sustenta"
    )

    # --- perguntas decisivas ---------------------------------------------------------------------
    for f in faltando:
        info = necessarios.get(f, {})
        escopo = info.get("escopo") or "item"
        opcoes = _efeitos(hipoteses, ent.fatos, f, info.get("opcoes") or ["sim", "nao"], sem_destino)
        av.perguntas.append(
            PerguntaNecessaria(
                atributo=f,
                escopo=escopo,
                pergunta=info.get("pergunta") or f"Qual é o valor de “{f.replace('_', ' ')}”?",
                opcoes=opcoes,
                motivo="A resposta muda o enquadramento: "
                + "; ".join(f"se {o['rotulo'].lower()} → {o['efeito']}" for o in opcoes),
                sugestao=ent.sugestoes.get(f),
            )
        )
    empresa_pend = [p for p in av.perguntas if p.escopo == "empresa"]
    dims["contexto"] = (
        Dimensao("contexto", PENDENTE, "falta no dossiê: " + ", ".join(p.atributo for p in empresa_pend))
        if empresa_pend
        else Dimensao(
            "contexto",
            OK,
            "dossiê suficiente para este item"
            + ("; não se aplica à empresa: " + "; ".join(ent.operacao_afastada) if ent.operacao_afastada else ""),
        )
    )

    # --- hipótese escolhida ----------------------------------------------------------------------
    usados: list[str] = []
    if escolhida is not None:
        res = next(a for a in avaliadas if a["id"] == escolhida["id"])
        usados = res["usados"]
        info_cct = ent.cclasstrib.get(escolhida["cclasstrib"])
        av.hipotese, av.cclasstrib = escolhida["id"], escolhida["cclasstrib"]
        av.tratamento = escolhida.get("tipo")
        afastadas = [a for a in avaliadas if a["situacao"] == "afastada"]
        dims["regra"] = Dimensao(
            "regra",
            OK,
            f"{escolhida['titulo']}"
            + (f"; hipóteses afastadas: {', '.join(a['titulo'] for a in afastadas)}" if afastadas else ""),
        )
        n_cond = len(escolhida.get("condicoes", []))
        dims["condicoes"] = Dimensao(
            "condicoes",
            OK,
            ("todas confirmadas: " + _texto_fatos(ent.fatos, usados)) if n_cond else "a hipótese não tem condições",
        )
        n_exc = len(escolhida.get("excecoes", []))
        dims["excecoes"] = Dimensao(
            "excecoes", OK, f"{n_exc} exceção(ões) verificada(s)" if n_exc else "nenhuma exceção prevista"
        )
        # cClassTrib: existe na tabela, vale na data, é permitido no documento e o CST confere.
        if info_cct is None:
            dims["cclasstrib"] = Dimensao("cclasstrib", FALHA, f"{escolhida['cclasstrib']} fora da tabela oficial")
        elif not info_cct.get("vigente_na_data"):
            dims["cclasstrib"] = Dimensao("cclasstrib", FALHA, f"{escolhida['cclasstrib']} não vigente na data")
        elif not info_cct.get("permitido_no_documento"):
            dims["cclasstrib"] = Dimensao(
                "cclasstrib", ATENCAO, f"{escolhida['cclasstrib']} não é indicado para o documento fiscal do cenário"
            )
        else:
            av.cst = info_cct.get("cst")
            av.perc_red_ibs = info_cct.get("reducao_ibs_pct")
            av.perc_red_cbs = info_cct.get("reducao_cbs_pct")
            dims["cclasstrib"] = Dimensao(
                "cclasstrib", OK, f"{escolhida['cclasstrib']} / CST {info_cct.get('cst')} — {info_cct.get('nome')}"
            )
        # Fontes: só valem referências que existem no pacote de evidências.
        validos = [f for f in escolhida.get("fundamentos", []) if f.get("ref") in ent.refs]
        invalidos = [f["ref"] for f in escolhida.get("fundamentos", []) if f.get("ref") not in ent.refs]
        normativos = [f for f in validos if ent.refs[f["ref"]]["tipo"] in ("trecho", "correlacao", "precedente")]
        av.fundamentos = [
            {**f, **{k: v for k, v in ent.refs[f["ref"]].items() if k in ("tipo", "norma", "local", "id", "nome")}}
            for f in validos
        ]
        if not validos:
            dims["fonte"] = Dimensao("fonte", FALHA, "nenhum fundamento verificável na base normativa")
        elif escolhida.get("tipo") != "regra_geral" and not normativos:
            dims["fonte"] = Dimensao("fonte", FALHA, "benefício sem trecho legal ou correlação oficial citada")
        else:
            texto = ", ".join(dict.fromkeys(_rotulo_ref(ent.refs[f["ref"]], f["ref"]) for f in validos))
            if ent.tese_aprovada and not op_escolhida:
                texto += " · tese validada por revisor"
            dims["fonte"] = Dimensao("fonte", ATENCAO if invalidos else OK, texto[:300])
    elif faltando:
        dims["regra"] = Dimensao("regra", PENDENTE, "hipóteses em aberto: depende de " + ", ".join(faltando))
        dims["condicoes"] = Dimensao("condicoes", PENDENTE, "fatos a confirmar: " + ", ".join(faltando))
        dims["excecoes"] = Dimensao("excecoes", NA, "")
        dims["cclasstrib"] = Dimensao("cclasstrib", NA, "")
        dims["fonte"] = Dimensao("fonte", NA, "")
    elif sem_produto:
        # O regime da operação foi afastado e o produto não pôde ser estudado (sem NCM ou sem tese).
        afastadas = [a for a in avaliadas if a["situacao"] == "afastada"]
        porque = "; ".join(f"{a['titulo']}: {a['motivo'].rstrip('.')}" for a in afastadas)
        base = ent.tese_falha or falta_produto
        dims["regra"] = Dimensao(
            "regra", FALHA if d_id.situacao != FALHA else NA, (f"{porque}. " if porque else "") + base
        )
        for k in ("condicoes", "excecoes", "cclasstrib", "fonte"):
            dims[k] = Dimensao(k, NA, "")
        if ent.tese_falha:
            motivos.append("TESE_NAO_CONCLUIDA")
    else:
        dims["regra"] = Dimensao("regra", FALHA, "nenhuma hipótese se sustenta com os fatos conhecidos")
        for k in ("condicoes", "excecoes", "cclasstrib", "fonte"):
            dims[k] = Dimensao(k, NA, "")
        motivos.append("SEM_HIPOTESE_SUSTENTADA")

    # --- conflitos ---------------------------------------------------------------------------------
    # Só pesa o conflito que toca a conclusão: a hipótese escolhida (suas referências ou seu cClassTrib).
    # Comentários sobre hipóteses afastadas ou de outros cenários ficam registrados, sem bloquear.
    is_ = tese.get("imposto_seletivo") or {}
    refs_is = {f.get("ref") for f in is_.get("fundamentos", [])}
    refs_escolhida = {f.get("ref") for f in (escolhida or {}).get("fundamentos", [])}
    cct = av.cclasstrib or ""
    relevantes, sobre_is, informativos = [], [], []
    # cClassTrib que a própria tabela oficial veda para este código não disputam o enquadramento.
    vedados = {
        str(r.get("cclasstrib"))
        for r in ent.refs.values()
        if r.get("tipo") == "correlacao" and str(r.get("permissao") or "").upper() == "VEDADO"
    }
    for c in tese.get("conflitos", []):
        texto, refs = c.get("descricao") or "", set(c.get("refs") or [])
        if op_escolhida and not (refs & refs_is or "seletivo" in texto.lower()):
            informativos.append(texto)  # conflito da família do produto: o regime da operação prevalece
            continue
        if c.get("muda_resultado") is False:
            informativos.append(texto)  # o próprio Jurista diz que não muda o cClassTrib
            continue
        em_jogo = _cclasstrib_citados(c, ent)
        toca = escolhida is not None and (
            bool(refs & refs_escolhida) or (bool(cct) and (cct in texto or cct in em_jogo)) or f"T{cct}" in refs
        )
        if toca and (em_jogo - {cct} - vedados):
            relevantes.append(texto)  # aponta outro cClassTrib possível: só o especialista decide
        elif toca:
            informativos.append(texto)  # fontes coerentes com a conclusão: não muda o resultado
        elif refs & refs_is or "seletivo" in texto.lower():
            sobre_is.append(texto)
        else:
            informativos.append(texto)
    codigo_item = (ent.identidade or {}).get("codigo") or ""

    def toca_o_item(a: dict[str, Any]) -> bool:
        # A divergência vale para o item se for do cClassTrib aplicado e citar o código (ou um prefixo dele).
        cods = [str(c).replace(".", "") for c in a.get("codigos") or []]
        return a.get("cclasstrib") == cct and (not cods or any(codigo_item.startswith(c) for c in cods))

    graves = [a.get("descricao") or "" for a in ent.alertas if a.get("gravidade") == "alta" and toca_o_item(a)]
    medios = [a.get("descricao") or "" for a in ent.alertas if a.get("gravidade") != "alta" and toca_o_item(a)]
    analisados = {h["cclasstrib"] for h in hipoteses} | so_operacao
    comentado = " ".join(
        [tese.get("observacoes") or "", *(c.get("descricao") or "" for c in tese.get("conflitos", []))]
    )
    nao_analisados = sorted(c for c in set(ent.correlacionados) - analisados if c not in comentado)
    if nao_analisados and not op_escolhida:
        medios.append("correlação oficial não analisada: " + ", ".join(nao_analisados))
    if av.cclasstrib and not op_escolhida:
        for p in ent.precedentes:
            if p.get("cclasstrib") and p["cclasstrib"] != av.cclasstrib and not p.get("condicoes"):
                graves.append(f"regra aprovada ({p.get('dispositivo')}) indica {p['cclasstrib']}")
    if graves or relevantes:
        dims["conflito"] = Dimensao("conflito", FALHA, "; ".join(graves + relevantes)[:400])
        motivos.append("CONFLITO_NORMATIVO")
    elif medios:
        dims["conflito"] = Dimensao("conflito", ATENCAO, "; ".join(medios)[:400])
    elif informativos:
        dims["conflito"] = Dimensao(
            "conflito", OK, ("nenhum conflito na hipótese aplicada; observações: " + "; ".join(informativos))[:400]
        )
    else:
        dims["conflito"] = Dimensao("conflito", OK, "nenhum conflito identificado")

    # --- Imposto Seletivo ----------------------------------------------------------------------------
    sit = is_.get("situacao", "nao_sujeito") if not sem_produto else "nao_avaliado"
    if sit == "depende":
        h_is = {"id": "IS", "titulo": "Imposto Seletivo", "cclasstrib": "IS", "condicoes": is_.get("condicoes", [])}
        r = _testar(h_is, ent.fatos)
        sit = {"escolhida": "sujeito", "afastada": "nao_sujeito"}.get(r.situacao, "indefinido")
        for f in r.faltando if sit == "indefinido" else []:
            if all(p.atributo != f for p in av.perguntas):
                info = necessarios.get(f, {})
                av.perguntas.append(
                    PerguntaNecessaria(
                        atributo=f,
                        escopo=info.get("escopo") or "item",
                        pergunta=info.get("pergunta") or f"Qual é o valor de “{f.replace('_', ' ')}”?",
                        opcoes=[
                            {"valor": valor(o), "rotulo": rotulo_opcao(o), "efeito": ""}
                            for o in info.get("opcoes") or ["sim", "nao"]
                        ],
                        motivo="Define se o item está sujeito ao Imposto Seletivo.",
                        sugestao=ent.sugestoes.get(f),
                    )
                )
    av.is_situacao = sit
    if sit == "sujeito":
        dims["imposto_seletivo"] = Dimensao(
            "imposto_seletivo", ATENCAO if ent.is_exige_analise else OK, is_.get("explicacao") or "sujeito ao IS"
        )
        motivos.append("SUJEITO_A_IMPOSTO_SELETIVO")
    elif sit == "indefinido":
        dims["imposto_seletivo"] = Dimensao("imposto_seletivo", PENDENTE, "depende de fato do item")
    elif sit == "nao_avaliado":
        dims["imposto_seletivo"] = Dimensao(
            "imposto_seletivo",
            ATENCAO if escolhida is not None else NA,
            "não avaliado: o Imposto Seletivo depende do NCM do produto, que ainda não foi estudado"
            if escolhida is not None
            else "",
        )
    else:
        dims["imposto_seletivo"] = Dimensao("imposto_seletivo", OK, is_.get("explicacao") or "não sujeito")
    if sobre_is and dims["imposto_seletivo"].situacao == OK and sit != "nao_sujeito":
        dims["imposto_seletivo"] = Dimensao("imposto_seletivo", ATENCAO, "; ".join(sobre_is)[:400])

    # --- a dúvida de identificação muda o imposto? ---------------------------------------------------
    alternativas = ent.tratamento_alternativas
    if (
        alternativas
        and dims["identificacao"].situacao == ATENCAO
        and av.cclasstrib
        and sit not in ("indefinido", "nao_avaliado")
        and not op_escolhida
    ):
        atual = f"{av.cclasstrib}|{'sujeito' if sit == 'sujeito' else 'nao_sujeito'}"
        if all(t == atual for t in alternativas.values()):
            idt = ent.identidade or {}
            cod = idt.get("codigo_formatado") or idt.get("codigo")
            outros = " ou ".join(formatar_codigo(idt.get("tipo_codigo") or "ncm", c) for c in alternativas)
            mesmo = f"{cod} ou {outros} têm o mesmo tratamento (cClassTrib {av.cclasstrib})"
            # Só dispensa a pessoa quando o NCM do ERP foi mantido, a descrição basta e a certeza é razoável.
            # Criar ou trocar um NCM mexe no cadastro (e em outros impostos): isso sempre é confirmado.
            seguro = (
                idt.get("situacao") == "confirmado"
                and idt.get("descricao_suficiente") is not False
                and float(idt.get("confianca_modelo") or 0) >= 0.7
            )
            if seguro:
                dims["identificacao"] = Dimensao(
                    "identificacao",
                    OK,
                    (
                        f"A dúvida sobre o código não muda o imposto: {mesmo}. "
                        f"Dúvida registrada: {dims['identificacao'].texto}"
                    )[:300],
                )
            else:
                dims["identificacao"] = Dimensao(
                    "identificacao",
                    ATENCAO,
                    (
                        f"{dims['identificacao'].texto} · O imposto seria o mesmo ({mesmo}), mas o NCM precisa "
                        "de confirmação."
                    )[:300],
                )

    # --- regime da operação: o cClassTrib não depende do NCM ------------------------------------------
    if op_escolhida and escolhida is not None and escolhida.get("independe_do_codigo"):
        nota = f"O cClassTrib não depende dele: {escolhida['titulo']}."
        d = dims["codigo_fiscal"]
        if d.situacao == FALHA:
            dims["codigo_fiscal"] = Dimensao(
                "codigo_fiscal", ATENCAO, f"NCM/NBS ainda não definido: defina-o para a nota fiscal. {nota}"
            )
        elif d.situacao == ATENCAO:
            dims["codigo_fiscal"] = Dimensao("codigo_fiscal", ATENCAO, f"{d.texto} · {nota}"[:300])

    # --- a lei nomeia este produto com outro código? -------------------------------------------------
    if ent.produtos_na_lei and dims["codigo_fiscal"].situacao != FALHA:
        idt = ent.identidade or {}
        cod = idt.get("codigo_formatado") or idt.get("codigo")
        p = ent.produtos_na_lei[0]
        dims["codigo_fiscal"] = Dimensao(
            "codigo_fiscal",
            ATENCAO,
            (
                f"A lei cita “{p['produto']}” no código {' / '.join(p['codigos'])} (Anexo {p['anexo']}, item "
                f"{p['item']}); o item está em {cod}. Confira o NCM: com o código da lei o imposto pode mudar."
            )[:300],
        )
        motivos.append("PRODUTO_CITADO_NA_LEI")

    # --- conclusão em linguagem humana ---------------------------------------------------------------
    av.fatos_usados = [
        {"atributo": f, **{k: v for k, v in ent.fatos[f].items() if k != "atributo"}} for f in usados if f in ent.fatos
    ]
    if escolhida is not None:
        cond = _texto_fatos(ent.fatos, usados)
        av.conclusao = (
            f"{escolhida['titulo']}. {escolhida.get('explicacao', '').strip()}"
            + (f" Fatos determinantes: {cond}." if cond else "")
            + (
                f" Imposto Seletivo: {'sujeito' if sit == 'sujeito' else 'não sujeito'}."
                if sit not in ("indefinido", "nao_avaliado")
                else ""
            )
        ).strip()
    elif faltando:
        av.conclusao = "Não classificado: " + " ".join(p.motivo for p in av.perguntas[:2])
    elif sem_produto:
        av.conclusao = "Não classificado: " + dims["regra"].texto
    else:
        av.conclusao = "Não classificado: nenhuma hipótese se sustenta com os fatos conhecidos."
    if av.perguntas:
        motivos.append("FATO_PENDENTE")
    return _finalizar(av, dims, motivos)


def _finalizar(av: Avaliacao, dims: dict[str, Dimensao], motivos: list[str]) -> Avaliacao:
    av.dimensoes = [dims.get(k) or Dimensao(k, NA, "") for k, _ in DIMENSOES]
    situacoes = {d.chave: d.situacao for d in av.dimensoes}
    valores = set(situacoes.values())
    identificacao_ruim = FALHA in (situacoes["identificacao"], situacoes["codigo_fiscal"])
    juridico_ruim = any(situacoes[k] == FALHA for k in ("regra", "cclasstrib", "fonte", "conflito"))
    if identificacao_ruim:
        av.status, av.nivel = StatusItem.REVISAO_CONTADOR, NivelRevisao.CONTADOR
    elif juridico_ruim:
        av.status, av.nivel = StatusItem.REVISAO_ESPECIALISTA, NivelRevisao.ESPECIALISTA
    elif PENDENTE in valores:
        av.status, av.nivel = StatusItem.AGUARDANDO_INFORMACAO, NivelRevisao.OPERACIONAL
    elif ATENCAO in valores:
        av.status, av.nivel = StatusItem.REVISAO_CONTADOR, NivelRevisao.CONTADOR
    else:
        av.status, av.nivel = StatusItem.CLASSIFICADO, None
    if FALHA in valores:
        av.confianca_global = "baixa"
    elif PENDENTE in valores:
        av.confianca_global = "incompleta"
    elif ATENCAO in valores:
        av.confianca_global = "media"
    else:
        av.confianca_global = "alta"
    if av.status != StatusItem.CLASSIFICADO and av.cclasstrib is None:
        av.cst = None
    av.motivos = list(dict.fromkeys(motivos))
    return av
