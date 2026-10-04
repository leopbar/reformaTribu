"""Avaliação de um item: aplica a tese da família aos fatos do item (função pura, testável).

1. Percorre as hipóteses na ordem de precedência: primeiro os regimes decididos pela operação (bares e
   restaurantes, farmácia de manipulação — `operacao.py`, valem mesmo sem NCM), depois as da tese da
   família do produto (específica → regra geral).
   - condição com fato conhecido e diferente do exigido, ou exceção confirmada → hipótese afastada;
   - todas as condições confirmadas e exceções descartadas → hipótese escolhida;
   - falta um fato → a hipótese continua possível: se as alternativas que restam levam a
     enquadramentos diferentes, nasce uma pergunta ("se A → X, se B → Y").
2. Monta o relatório de confiança por dimensão, sem número mágico.
3. Compara a conclusão com o que as pessoas já decidiram para o mesmo código, cenário e ramo
   (memória de decisões, ADR 0028): reforça ou contesta o resultado.
4. Decide o status e o nível de revisão.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Any

from app.analise import decisoes as decisoes_mod
from app.analise import fatos_padrao
from app.analise.fatos import DESCONHECIDO, chave, valor
from app.analise.natureza import condicao_do_fato
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

# Fato do dossiê que decide se o Imposto Seletivo é recolhido pela empresa (ADR 0029). O IS incide uma
# única vez, na fabricação ou na importação (LC 214/2025, arts. 409 e 412): quem só revende não recolhe.
FATO_IS = "fabrica_ou_importa_seletivo"
PERGUNTA_IS = (
    "A empresa fabrica ou importa algum produto sujeito ao Imposto Seletivo (bebidas alcoólicas, bebidas "
    "açucaradas, cigarros, veículos, embarcações, armas)?"
)
# Pergunta "o que é este item?" quando os códigos possíveis têm tratamentos diferentes (ADR 0029).
FATO_CODIGO = "codigo_do_item"
MESMO = "="  # o código alternativo tem a mesma assinatura jurídica do escolhido
# Certeza mínima para perguntar ao operador "o que é este item?". Perguntar exige menos que liberar o imposto
# sozinho (0,7 sem o NCM do ERP), porque a opção "Nenhuma destas" sempre leva ao contador (ADR 0029).
PISO_PERGUNTA_CODIGO = 0.4
NBS_ALIMENTACAO = "10301"  # NBS 1.0301: fornecimento de alimentação, incluindo refeições
# Palavras do nome oficial do cClassTrib que indicam outro cenário de operação (comprador ou destino
# diferentes, ADR 0026): não disputam o enquadramento da venda comum ao consumidor.
OUTRO_CENARIO = (
    "diferimento",
    "export",
    "administracao publica",
    "produtor rural",
    "zona franca",
    "zona de processamento",
    "cooperativa",
    "industria incentivada",
    "regime regular que promova industrializacao",
)


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
    # Agrupamento próprio da pergunta (sufixo da chave do grupo); vazio = o padrão do escopo.
    grupo: str = ""


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
    # Para os de imposto desconhecido: os anexos da lei que citam o código (explicam a pergunta ao operador).
    beneficios_em_disputa: dict[str, str] = field(default_factory=dict)
    # Produtos que um anexo da lei nomeia com outro código (checagem cruzada com os anexos).
    produtos_na_lei: list[dict[str, Any]] = field(default_factory=list)
    # Regimes decididos pela operação (ADR 0026): hipóteses avaliadas antes das do produto, com as
    # perguntas que as decidem. As referências e os cClassTrib deles já vêm em `refs` e `cclasstrib`.
    operacao: list[dict[str, Any]] = field(default_factory=list)
    operacao_fatos: list[dict[str, Any]] = field(default_factory=list)
    operacao_afastada: list[str] = field(default_factory=list)  # "regime: motivo" (vale para a empresa toda)
    # Decisões de pessoas para o mesmo código, cenário e ramo (ADR 0028), vindas de `decisoes.carregar`.
    decisoes: list[dict[str, Any]] = field(default_factory=list)
    # O NCM está no Anexo XVII (lista fechada do Imposto Seletivo)? None = não se aplica (NBS) ou sem base.
    is_no_anexo_xvii: bool | None = None


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
    # NCM/NBS a confirmar no cadastro sem mudar o imposto (ADR 0029); vazio = nada a ajustar.
    ajuste_cadastro: dict[str, Any] = field(default_factory=dict)

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
    # Dúvidas da instrução nova (ADR 0029): só pesa a que aponta palavras da própria descrição. "E se fosse
    # X?" sem nada na descrição que sugira X vira observação.
    if idt.get("duvidas"):
        fundamentadas, observadas = _separar_duvidas(idt["duvidas"], idt.get("descricao_normalizada") or "")
        duvidas = fundamentadas
        observacoes = observadas
    else:
        observacoes = []
    conf_parecer = float(idt.get("confianca_parecer") or conf)
    if idt.get("dois_votos") and idt.get("descricao_suficiente") is not False and conf_parecer >= 0.85:
        # O código do cadastro e o parecer que decide escolheram o mesmo código: dois votos contra um.
        texto = "O NCM/NBS do cadastro e o parecer da IA escolheram o mesmo código"
        pontos = [*duvidas, *observacoes]
        if pontos:
            texto += " · pontos observados (não mudaram a escolha): " + "; ".join(pontos)
        d_id = Dimensao("identificacao", OK, texto[:300])
    elif idt.get("descricao_suficiente") is False:
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


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def _separar_duvidas(duvidas: list[Any], descricao: str) -> tuple[list[str], list[str]]:
    """(dúvidas apoiadas em palavras da descrição, observações hipotéticas)."""
    desc = f" {_norm(descricao)} "
    apoiadas, hipoteticas = [], []
    for d in duvidas:
        if isinstance(d, str):
            apoiadas.append(d)
            continue
        texto, trecho = str(d.get("duvida") or ""), _norm(str(d.get("trecho") or ""))
        if trecho and f" {trecho} " in desc:
            apoiadas.append(f"{texto} (“{d.get('trecho')}”)")
        elif texto:
            hipoteticas.append(texto)
    return apoiadas, hipoteticas


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
    # cClassTrib de outro cenário (compra pública, exportação, produtor rural…) não vale na venda ao consumidor:
    # sem isso, a hipótese ficava pendurada e pedia fatos que nunca valem (ex.: "o comprador é órgão público?").
    outro_cenario = _de_outro_cenario(ent)
    produto = [
        h
        for h in (tese_produto or {}).get("hipoteses", [])
        if h.get("cclasstrib") not in so_operacao and h.get("cclasstrib") not in outro_cenario
    ]
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
                pergunta=fatos_padrao.pergunta(f) or info.get("pergunta") or _pergunta_padrao(f),
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
            atencao = bool(invalidos) and escolhida.get("tipo") != "regra_geral"
            dims["fonte"] = Dimensao("fonte", ATENCAO if atencao else OK, texto[:300])
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
    conflito_pendente: list[str] = []  # fatos que resolveriam um conflito real (viram pergunta)
    # cClassTrib que a própria tabela oficial veda para este código não disputam o enquadramento.
    vedados = {
        str(r.get("cclasstrib"))
        for r in ent.refs.values()
        if r.get("tipo") == "correlacao" and str(r.get("permissao") or "").upper() == "VEDADO"
    } | _de_outro_cenario(ent)
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
            # Aponta outro cClassTrib possível. Se o Jurista disse qual fato separa os dois enquadramentos
            # (ADR 0029), o fato decide: conhecido e diferente do que levaria ao outro → resolvido; ainda
            # desconhecido → pergunta. Sem fato que decida, só o especialista resolve.
            resolucao = _resolver_por_fato(c, ent.fatos)
            f_decide = chave(str(c.get("fato_que_decide") or ""))
            if resolucao == "resolvido":
                v_decide = _valor_fato(ent.fatos, f_decide)
                informativos.append(f"{texto} — resolvido pelo fato “{f_decide.replace('_', ' ')}” = {v_decide}")
            elif resolucao == "pendente":
                conflito_pendente.append(f_decide)
            else:
                relevantes.append(texto)
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
    medios = []
    for a in ent.alertas:
        if a.get("gravidade") == "alta" or not toca_o_item(a):
            continue
        if _restricao_conferida(a, escolhida, usados):
            # A lei restringe em palavras (ex.: "sem adição de açúcar") e a regra estruturada não: o Jurista
            # transformou a restrição em condição, e os fatos do item a confirmaram (ADR 0029).
            informativos.append(f"{a.get('descricao') or ''} — conferida com os fatos do item")
            continue
        medios.append(a.get("descricao") or "")
    analisados = {h["cclasstrib"] for h in hipoteses} | so_operacao
    comentado = " ".join(
        [tese.get("observacoes") or "", *(c.get("descricao") or "" for c in tese.get("conflitos", []))]
    )
    nao_analisados = sorted(
        c for c in set(ent.correlacionados) - analisados - _de_outro_cenario(ent) if c not in comentado
    )
    if nao_analisados and not op_escolhida:
        medios.append("correlação oficial não analisada: " + ", ".join(nao_analisados))
    if av.cclasstrib and not op_escolhida:
        for p in ent.precedentes:
            if p.get("cclasstrib") and p["cclasstrib"] != av.cclasstrib and not p.get("condicoes"):
                graves.append(f"regra aprovada ({p.get('dispositivo')}) indica {p['cclasstrib']}")
    for f in dict.fromkeys(conflito_pendente):
        if all(p.atributo != f for p in av.perguntas):
            info = necessarios.get(f, {})
            av.perguntas.append(
                PerguntaNecessaria(
                    atributo=f,
                    escopo=info.get("escopo") or "item",
                    pergunta=fatos_padrao.pergunta(f) or info.get("pergunta") or _pergunta_padrao(f),
                    opcoes=[
                        {"valor": valor(o), "rotulo": rotulo_opcao(o), "efeito": ""}
                        for o in info.get("opcoes") or ["sim", "nao"]
                    ],
                    motivo="Decide entre dois enquadramentos que as fontes oficiais admitem para este código.",
                    sugestao=ent.sugestoes.get(f),
                )
            )
    if graves or relevantes:
        dims["conflito"] = Dimensao("conflito", FALHA, "; ".join(graves + relevantes)[:400])
        motivos.append("CONFLITO_NORMATIVO")
    elif conflito_pendente:
        dims["conflito"] = Dimensao(
            "conflito",
            PENDENTE,
            "as fontes admitem outro enquadramento; decide: "
            + ", ".join(f.replace("_", " ") for f in dict.fromkeys(conflito_pendente)),
        )
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
    # O IS só alcança os bens do Anexo XVII (LC 214/2025, art. 409, § 1º): um NCM que o anexo não cita não é
    # sujeito, diga o parecer o que disser (ADR 0029).
    fora_do_anexo = sit in ("sujeito", "depende") and ent.is_no_anexo_xvii is False
    if fora_do_anexo:
        sit = "nao_sujeito"
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
                        pergunta=fatos_padrao.pergunta(f) or info.get("pergunta") or _pergunta_padrao(f),
                        opcoes=[
                            {"valor": valor(o), "rotulo": rotulo_opcao(o), "efeito": ""}
                            for o in info.get("opcoes") or ["sim", "nao"]
                        ],
                        motivo="Define se o item está sujeito ao Imposto Seletivo.",
                        sugestao=ent.sugestoes.get(f),
                    )
                )
    av.is_situacao = sit
    papel_is = _valor_fato(ent.fatos, FATO_IS) if sit == "sujeito" else DESCONHECIDO
    if sit == "sujeito" and papel_is == "nao":
        # O IS incide uma única vez, na fabricação ou na importação (LC 214/2025, arts. 409 e 412): quem só
        # revende não recolhe nem destaca o imposto. O produto continua sujeito; a venda desta empresa não.
        av.is_situacao = "na_origem"
        dims["imposto_seletivo"] = Dimensao(
            "imposto_seletivo",
            OK,
            "Produto sujeito ao Imposto Seletivo, cobrado uma única vez na fabricação ou na importação "
            "(LC 214/2025, arts. 409 e 412). A empresa informou que não fabrica nem importa esses produtos: "
            "na revenda o IS não é recolhido nem destacado.",
        )
    elif sit == "sujeito" and papel_is == DESCONHECIDO:
        dims["imposto_seletivo"] = Dimensao(
            "imposto_seletivo",
            PENDENTE,
            "sujeito ao Imposto Seletivo; falta saber se a empresa fabrica ou importa (quem só revende não recolhe)",
        )
        if all(p.atributo != FATO_IS for p in av.perguntas):
            av.perguntas.append(
                PerguntaNecessaria(
                    atributo=FATO_IS,
                    escopo="empresa",
                    pergunta=PERGUNTA_IS,
                    opcoes=[
                        {
                            "valor": "nao",
                            "rotulo": "Não, só revende",
                            "efeito": "o IS já foi cobrado na fábrica ou na importação; a venda segue sem IS",
                        },
                        {
                            "valor": "sim",
                            "rotulo": "Sim, fabrica ou importa",
                            "efeito": "o IS é recolhido nas vendas desses produtos (o contador confere)",
                        },
                    ],
                    motivo="O Imposto Seletivo incide uma única vez, na fabricação ou na importação (LC 214/2025, "
                    "arts. 409 e 412): define se a empresa recolhe o imposto.",
                )
            )
    elif sit == "sujeito":
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
    elif fora_do_anexo:
        dims["imposto_seletivo"] = Dimensao(
            "imposto_seletivo",
            OK,
            (
                "Não sujeito: o código não está no Anexo XVII da LC 214/2025, a lista dos bens do Imposto Seletivo "
                f"(art. 409, § 1º). O parecer da família apontava “{is_.get('situacao')}”: "
                f"{is_.get('explicacao') or ''}"
            )[:400],
        )
    else:
        dims["imposto_seletivo"] = Dimensao("imposto_seletivo", OK, is_.get("explicacao") or "não sujeito")
    if (
        sobre_is
        and not fora_do_anexo
        and dims["imposto_seletivo"].situacao == OK
        and sit != "nao_sujeito"
        and av.is_situacao == sit
    ):
        dims["imposto_seletivo"] = Dimensao("imposto_seletivo", ATENCAO, "; ".join(sobre_is)[:400])

    if _servico_de_alimentacao_sem_refeicoes(ent) and not op_escolhida:
        dims["identificacao"] = Dimensao(
            "identificacao",
            FALHA,
            "A IA classificou o item como serviço de alimentação (NBS), mas a empresa informou que não serve "
            "refeições: o item é mercadoria e precisa de um NCM. Informe o NCM do produto.",
        )

    # --- a dúvida sobre o código muda o imposto? (ADR 0019 e 0029) -----------------------------------
    if av.cclasstrib and sit in ("sujeito", "nao_sujeito") and not op_escolhida and not ent.produtos_na_lei:
        _duvida_de_codigo(ent, av, dims, sit)

    # --- regime da operação: o cClassTrib não depende do NCM ------------------------------------------
    if op_escolhida and escolhida is not None and escolhida.get("independe_do_codigo"):
        # O enquadramento vem da operação (ADR 0026): a dúvida sobre o NCM/NBS não muda o imposto. O código
        # segue em paralelo, para a nota fiscal, pela lista "Ajustes de cadastro" (ADR 0029).
        nota = f"O cClassTrib não depende dele: {escolhida['titulo']}."
        idt = ent.identidade or {}
        cod, erp = idt.get("codigo"), idt.get("codigo_erp")
        ruins = (ATENCAO, FALHA)
        if dims["identificacao"].situacao in ruins or dims["codigo_fiscal"].situacao in ruins:
            tipo = idt.get("tipo_codigo") or "ncm"
            if cod and cod != erp:
                texto = f"NCM/NBS a confirmar no cadastro: sugerido {formatar_codigo(tipo, cod)}" + (
                    f" no lugar de {formatar_codigo(tipo, erp)}" if erp else ""
                )
            elif not cod:
                texto = "NCM/NBS ainda não definido: defina-o no cadastro para a nota fiscal"
            else:
                texto = f"{formatar_codigo(tipo, cod)} do cadastro mantido"
            if cod != erp or not cod:
                av.ajuste_cadastro = {
                    "tipo_codigo": tipo,
                    "erp": erp,
                    "erp_informado": idt.get("codigo_anterior"),
                    "sugerido": cod,
                    "alternativas": list(idt.get("codigos_em_disputa") or []),
                    "tratamento": f"{av.cclasstrib}|regime",
                    "texto": f"{texto}. {nota}",
                }
            anterior = dims["identificacao"].texto if dims["identificacao"].situacao != OK else ""
            dims["identificacao"] = Dimensao(
                "identificacao",
                OK,
                (f"A dúvida sobre o código não muda o imposto. {nota}" + (f" Dúvida: {anterior}" if anterior else ""))[
                    :300
                ],
            )
            dims["codigo_fiscal"] = Dimensao("codigo_fiscal", OK, f"{texto}. {nota}"[:300])

    # --- a lei nomeia este produto com outro código? -------------------------------------------------
    lei = ent.produtos_na_lei[0] if ent.produtos_na_lei else None
    codigos_lei = [c.replace(".", "") for c in (lei or {}).get("codigos", [])]
    if (
        lei
        and dims["codigo_fiscal"].situacao != FALHA
        and av.cclasstrib
        and av.cclasstrib in (lei.get("cclasstrib_do_anexo") or [])
        and len(codigos_lei) == 1
        and (ent.identidade or {}).get("tipo_codigo", "ncm") == "ncm"
    ):
        # O item já tem o tratamento que o anexo dá ao produto (ADR 0030): o NCM que a lei cita não muda o
        # imposto. Vai para "Ajustes de cadastro", como as outras correções de NCM que não mudam o imposto.
        idt = ent.identidade or {}
        texto = (
            f"A lei cita “{lei['produto']}” no código {lei['codigos'][0]} (Anexo {lei['anexo']}, item {lei['item']}); "
            f"o item já tem o tratamento desse anexo ({av.cclasstrib}). NCM a confirmar no cadastro: sugerido "
            f"{lei['codigos'][0]}. Não muda o IBS/CBS."
        )
        av.ajuste_cadastro = {
            "tipo_codigo": "ncm",
            "erp": idt.get("codigo_erp") or idt.get("codigo"),
            "erp_informado": idt.get("codigo_anterior"),
            "sugerido": codigos_lei[0],
            "alternativas": [],
            "tratamento": f"{av.cclasstrib}|{sit}",
            "texto": texto,
        }
        dims["codigo_fiscal"] = Dimensao("codigo_fiscal", OK, texto[:300])
    elif lei and dims["codigo_fiscal"].situacao != FALHA:
        idt = ent.identidade or {}
        cod = idt.get("codigo_formatado") or idt.get("codigo")
        p = lei
        dims["codigo_fiscal"] = Dimensao(
            "codigo_fiscal",
            ATENCAO,
            (
                f"A lei cita “{p['produto']}” no código {' / '.join(p['codigos'])} (Anexo {p['anexo']}, item "
                f"{p['item']}); o item está em {cod}. Confira o NCM: com o código da lei o imposto pode mudar."
            )[:300],
        )
        motivos.append("PRODUTO_CITADO_NA_LEI")

    # --- o que as pessoas já decidiram para este código (ADR 0028) -----------------------------------
    if (
        ent.decisoes
        and escolhida is not None
        and av.cclasstrib
        and not op_escolhida
        and sit in ("sujeito", "nao_sujeito")
    ):
        fatos_decisivos = [{"atributo": f, "valor": ent.fatos[f].get("valor")} for f in usados if f in ent.fatos]
        cons = decisoes_mod.consolidar(
            ent.decisoes, decisoes_mod.resultado(av.cclasstrib, sit), decisoes_mod.chave_fatos(fatos_decisivos)
        )
        _pesar_decisoes(dims, motivos, cons, av.cclasstrib)

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
                " Imposto Seletivo: cobrado na fabricação ou importação; não incide na revenda."
                if av.is_situacao == "na_origem"
                else f" Imposto Seletivo: {'sujeito' if sit == 'sujeito' else 'não sujeito'}."
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


def _de_outro_cenario(ent: EntradaAvaliacao) -> set[str]:
    """cClassTrib do pacote cujo nome oficial indica outro cenário de operação (ADR 0026 e 0029)."""
    return {c for c, info in ent.cclasstrib.items() if any(k in _norm(info.get("nome") or "") for k in OUTRO_CENARIO)}


def _restricao_conferida(a: dict[str, Any], escolhida: dict[str, Any] | None, usados: list[str]) -> bool:
    restricao = a.get("tipo") == "DIV_RESTRICAO_TEXTUAL" or str(a.get("descricao") or "").startswith(
        "A lei restringe o benefício em palavras"
    )
    tem_condicao = bool((escolhida or {}).get("condicoes") or (escolhida or {}).get("excecoes"))
    return restricao and tem_condicao and bool(usados)


def _resolver_por_fato(c: dict[str, Any], fatos: dict[str, dict[str, Any]]) -> str:
    """Um conflito que o Jurista amarrou a um fato (ADR 0029): "resolvido", "pendente" ou "" (sem fato)."""
    if not c.get("fato_que_decide"):
        return ""
    outro = valor(c.get("valor_para_o_outro_enquadramento") or "")
    if outro == DESCONHECIDO:
        return ""
    v = _valor_fato(fatos, chave(str(c["fato_que_decide"])))
    if v == DESCONHECIDO:
        return "pendente"
    return "resolvido" if v != outro else ""


def _servico_de_alimentacao_sem_refeicoes(ent: EntradaAvaliacao) -> bool:
    """A IA deu ao item um código de SERVIÇO de alimentação (NBS 1.0301), mas a empresa informou que não
    serve refeições: o item é mercadoria (frango assado inteiro, bolo de vitrine) e precisa de NCM."""
    idt = ent.identidade or {}
    return (
        idt.get("tipo_codigo") == "nbs"
        and str(idt.get("codigo") or "").startswith(NBS_ALIMENTACAO)
        and _valor_fato(ent.fatos, "fornece_refeicoes") == "nao"
    )


def _tratamento_texto(t: str) -> str:
    cct, _, is_ = t.partition("|")
    return f"cClassTrib {cct}" + (" + Imposto Seletivo" if is_ == "sujeito" else "")


def _duvida_de_codigo(ent: EntradaAvaliacao, av: Avaliacao, dims: dict[str, Dimensao], sit: str) -> None:
    """A dúvida sobre o NCM/NBS muda o imposto? (ADR 0019 e 0029)

    Compara o tratamento do código escolhido com o de todos os códigos em disputa (o do ERP, o de cada
    parecer e as alternativas, inclusive as de outro capítulo trazidas pelo Navegador). Se todos dão o mesmo
    cClassTrib e Imposto Seletivo, a classificação do IBS/CBS sai e o código, quando muda o cadastro, vai
    para a lista "Ajustes de cadastro" (uma pessoa confirma o NCM sem travar o imposto); isso exige
    segurança. Se algum código leva (ou pode levar, quando o tratamento não é conhecido) a outro imposto,
    vira a pergunta "o que é este item?" ao operador, com certeza média: "Nenhuma destas" leva ao contador."""
    idt = ent.identidade or {}
    codigo = idt.get("codigo")
    if not codigo or idt.get("situacao") in (None, "indefinido", "memoria"):
        return
    ruins = (ATENCAO, FALHA)
    if dims["identificacao"].situacao not in ruins and dims["codigo_fiscal"].situacao not in ruins:
        return
    tipo = idt.get("tipo_codigo") or "ncm"
    atual = f"{av.cclasstrib}|{sit}"
    disputa = dict(ent.tratamento_alternativas)
    # Identidades anteriores à ADR 0029 não têm `codigo_erp`: o código anterior faz esse papel.
    erp = idt["codigo_erp"] if "codigo_erp" in idt else idt.get("codigo_anterior")
    if erp and erp != codigo and erp not in disputa:
        return  # o código que sairia do cadastro não foi comparado: não dá para dizer que o imposto é o mesmo
    # O código do cadastro entre as opções é uma âncora independente da IA: aceita certeza menor.
    ancora = bool(erp) and (erp == codigo or erp in disputa)
    conf = float(idt.get("confianca_modelo") or 0)
    # Descrição vaga: o produto verdadeiro pode estar fora das opções. Liberar sozinho só com uma âncora (o
    # NCM do ERP entre as opções) ou com os dois pareceres da IA de acordo.
    dois_pareceres = bool(idt.get("segundo_parecer") and idt.get("concordancia"))
    # O Navegador ficou em dúvida entre capítulos e não achou código em algum deles: o imposto desse outro
    # jeito de ser o item é desconhecido, então não dá para dizer que a dúvida não muda o imposto.
    em_aberto = bool((idt.get("arvore") or {}).get("capitulos_em_aberto"))
    seguro = (
        conf >= (0.5 if ancora else 0.7)
        and not (idt.get("descricao_suficiente") is False and not (ancora or dois_pareceres))
        and not em_aberto
    )
    if _servico_de_alimentacao_sem_refeicoes(ent):
        return
    if any(t not in (atual, MESMO) for t in disputa.values()):
        # Uma opção leva (ou pode levar) a outro imposto: quem conhece o produto diz o que ele é.
        if conf >= PISO_PERGUNTA_CODIGO:
            _pergunta_de_identificacao(ent, av, dims, disputa, atual)
        return
    if not seguro:
        return
    if not disputa and not (idt.get("dois_votos") or conf >= 0.85):
        return
    cod = idt.get("codigo_formatado") or formatar_codigo(tipo, codigo)
    outros = [formatar_codigo(tipo, c) for c in disputa]
    mesmo = (f"{cod} ou {' ou '.join(outros)} têm" if outros else f"{cod} tem") + (
        f" o mesmo tratamento ({_tratamento_texto(atual)})"
    )
    anterior = dims["identificacao"].texto if dims["identificacao"].situacao != OK else ""
    texto_id = f"A dúvida sobre o código não muda o imposto: {mesmo}." + (
        f" Dúvida registrada: {anterior}" if anterior else ""
    )
    dims["identificacao"] = Dimensao("identificacao", OK, texto_id[:300])
    if erp == codigo:
        if dims["codigo_fiscal"].situacao != OK:
            dims["codigo_fiscal"] = Dimensao(
                "codigo_fiscal", OK, f"{cod} do cadastro mantido; a dúvida não muda o imposto"
            )
        return
    # O código do cadastro muda (ou não existia): a pessoa confirma na lista "Ajustes de cadastro".
    erp_fmt = formatar_codigo(tipo, erp) if erp else None
    texto = (
        f"NCM/NBS a confirmar no cadastro: sugerido {cod}"
        + (f" no lugar de {erp_fmt}" if erp_fmt else " (o cadastro não tinha código válido)")
        + ". Não muda o IBS/CBS."
    )
    av.ajuste_cadastro = {
        "tipo_codigo": tipo,
        "erp": erp,
        "erp_informado": idt.get("codigo_anterior"),
        "sugerido": codigo,
        "alternativas": list(disputa),
        "tratamento": atual,
        "texto": texto,
    }
    dims["codigo_fiscal"] = Dimensao("codigo_fiscal", OK, texto[:300])


def _pergunta_de_identificacao(
    ent: EntradaAvaliacao, av: Avaliacao, dims: dict[str, Dimensao], disputa: dict[str, str | None], atual: str
) -> None:
    """Os códigos possíveis têm tratamentos diferentes: pergunta ao operador o que o item é (ADR 0029).

    As opções são o código escolhido, o do ERP e os que levam (ou podem levar) a outro imposto. Os demais
    têm o mesmo imposto do escolhido: não ajudam a decidir e só alongariam a lista."""
    idt = ent.identidade or {}
    if _valor_fato(ent.fatos, FATO_CODIGO) != DESCONHECIDO:
        return  # já respondida com "nenhuma destas": o contador decide
    tipo = idt.get("tipo_codigo") or "ncm"
    codigo = str(idt.get("codigo"))
    erp = idt.get("codigo_erp")
    descricoes = idt.get("descricoes_em_disputa") or {}
    rotulos = idt.get("rotulos_em_disputa") or {}
    codigos = [codigo, *(c for c, t in disputa.items() if c == erp or t not in (atual, MESMO))]
    opcoes = []
    for c in codigos:
        t = atual if c == codigo or disputa.get(c) == MESMO else disputa.get(c)
        if t is None:
            beneficio = ent.beneficios_em_disputa.get(c)
            efeito = "imposto analisado depois da resposta" + (
                f" (a lei cita este código: {beneficio})" if beneficio else ""
            )
        else:
            efeito = _tratamento_texto(t)
        nome = rotulos.get(c) or _nome_oficial(descricoes.get(c) or "") or "descrição oficial indisponível"
        opcoes.append({"valor": c, "rotulo": f"{nome} ({formatar_codigo(tipo, c)})"[:200], "efeito": efeito[:300]})
    opcoes.append({"valor": "outro", "rotulo": "Nenhuma destas", "efeito": "o contador define o código"})
    conhecidos = all(disputa.get(c) is not None for c in codigos[1:])
    av.perguntas.append(
        PerguntaNecessaria(
            atributo=FATO_CODIGO,
            escopo="item",
            pergunta="Qual destas descrições corresponde ao item? "
            + ("Cada uma leva a um imposto diferente." if conhecidos else "O imposto depende da resposta."),
            opcoes=opcoes,
            motivo=("O código do item muda o imposto: " if conhecidos else "O código do item pode mudar o imposto: ")
            + "; ".join(f"{o['rotulo']} → {o['efeito']}" for o in opcoes[:-1]),
            grupo="ident:" + "-".join(sorted(codigos)),
        )
    )
    dims["identificacao"] = Dimensao(
        "identificacao",
        PENDENTE,
        "Qual código descreve o item? As opções levam a impostos diferentes; a pergunta foi para o operador.",
    )
    dims["codigo_fiscal"] = Dimensao("codigo_fiscal", PENDENTE, "aguarda a resposta sobre o que é o item")


_GENERICOS = {"outros", "outras", "outro", "outra", "demais"}


def _nome_oficial(desc: str) -> str:
    """Nome do código pela descrição oficial, para quando a IA não deu um rótulo: o nível mais fundo que não é
    só "Outros" (ex.: 2005.99.00 → "Outros produtos hortícolas e misturas de produtos hortícolas (outros)")."""
    partes = [p.strip().rstrip(".:") for p in desc.split(" › ") if p.strip()]
    for n, parte in enumerate(reversed(partes)):
        if parte.strip("- ").lower() not in _GENERICOS:
            return parte + (" (outros)" if n else "")
    return partes[-1] if partes else ""


def _pergunta_padrao(fato: str) -> str:
    """Pergunta para um fato que a tese pediu sem formular a pergunta: a condição da lei, quando o fato é de
    chave fixa (ADR 0030); senão o próprio fato, legível. Antes: "Qual é o valor de “...”?"."""
    condicao = condicao_do_fato(fato)
    if condicao:
        return condicao.split(":")[0].rstrip(". ") + "?"
    return f"O item atende a esta condição: “{fato.replace('_', ' ')}”?"


def _vezes(n: int) -> str:
    return f"{n} vez" if n == 1 else f"{n} vezes"


def _pesar_decisoes(
    dims: dict[str, Dimensao], motivos: list[str], cons: decisoes_mod.Consolidado, cclasstrib: str
) -> None:
    """Reforça ou contesta a conclusão com as decisões anteriores de pessoas (ADR 0028)."""
    if cons.vazio:
        return
    conflito, fonte = dims["conflito"], dims["fonte"]
    if cons.contra:
        if cons.a_favor:
            texto = (
                f"Decisões anteriores divergem: {cons.a_favor} para {cclasstrib} e {cons.contra} para outro "
                f"enquadramento ({cons.outro})."
            )
            grave = False
        else:
            texto = (
                f"Pessoas já decidiram {cons.outro} para este código ({_vezes(cons.contra)}); "
                f"a análise indica {cclasstrib}."
            )
            grave = cons.contra >= decisoes_mod.CONFIRMA
        situacao = FALHA if grave or conflito.situacao == FALHA else ATENCAO
        anterior = conflito.texto if conflito.situacao != OK else ""
        dims["conflito"] = Dimensao("conflito", situacao, (texto + (f" {anterior}" if anterior else ""))[:400])
        motivos.append("DECISAO_ANTERIOR_DIVERGENTE")
        return
    n = cons.a_favor
    quem = f"{cons.empresas} empresa" + ("s" if cons.empresas != 1 else "")
    nota = f"decidido igual por pessoas {_vezes(n)} ({quem} do ramo)"
    if n >= decisoes_mod.CONFIRMA:
        nota = f"confirmado pelo uso: {nota}"
        if conflito.situacao in (FALHA, ATENCAO):
            dims["conflito"] = Dimensao(
                "conflito", OK, f"Resolvido por {n} decisões anteriores iguais. Apontado: {conflito.texto}"[:400]
            )
            motivos[:] = [m for m in motivos if m != "CONFLITO_NORMATIVO"]
    elif n >= decisoes_mod.DISPENSA_AVISOS and conflito.situacao == ATENCAO:
        dims["conflito"] = Dimensao(
            "conflito", OK, f"Aviso dispensado por {n} decisões anteriores iguais: {conflito.texto}"[:400]
        )
    situacao_fonte = OK if n >= decisoes_mod.DISPENSA_AVISOS and fonte.situacao == ATENCAO else fonte.situacao
    dims["fonte"] = Dimensao("fonte", situacao_fonte, f"{fonte.texto[:220]} · {nota}")


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
