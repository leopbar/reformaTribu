"""Normalização de descrições: expansão de abreviações (dicionário editável) e inferência de tipo."""

from __future__ import annotations

import re
import unicodedata

_UNIDADE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(ml|l|lt|kg|g|gr|mg|un|und|cm|mm|m|pct|cx)\b", re.I)
_BARRA = re.compile(r"\b([csCS])/\s*")

PALAVRAS_SERVICO = (
    "servico",
    "servicos",
    "consultoria",
    "assessoria",
    "manutencao",
    "instalacao",
    "honorario",
    "honorarios",
    "mensalidade",
    "aula",
    "curso",
    "treinamento",
    "frete",
    "transporte",
    "locacao",
    "aluguel",
    "reparo",
    "conserto",
    "mao de obra",
    "hospedagem",
    "licenciamento",
    "assinatura",
    "auditoria",
    "contabil",
    "limpeza predial",
    "dedetizacao",
    "vigilancia",
    "seguranca patrimonial",
    "digitacao",
    "desenvolvimento de",
    "suporte tecnico",
    "projeto",
    "elaboracao",
    "exame",
    "consulta",
    "terapia",
    "sessao",
    "diaria",
)


def sem_acento(t: str) -> str:
    return unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode()


def normalizar_descricao(descricao: str, abreviacoes: dict[str, str]) -> tuple[str, list[dict[str, str]]]:
    """Expande abreviações conhecidas. Devolve (descrição normalizada, expansões aplicadas)."""
    t = (descricao or "").strip()
    t = _BARRA.sub(lambda m: "com " if m.group(1).lower() == "c" else "sem ", t)
    t = _UNIDADE.sub(lambda m: f"{m.group(1)} {m.group(2).lower()}", t)
    tokens = re.split(r"(\s+|[;,()\-/])", t)
    saida: list[str] = []
    aplicadas: list[dict[str, str]] = []
    for tok in tokens:
        chave = sem_acento(tok).lower().rstrip(".")
        if chave and chave in abreviacoes:
            exp = abreviacoes[chave]
            saida.append(exp)
            aplicadas.append({"abreviacao": tok, "expansao": exp})
        else:
            saida.append(tok.lower())
    normalizada = re.sub(r"\s+", " ", "".join(saida)).strip()
    return normalizada, aplicadas


def tokens_desconhecidos(descricao_normalizada: str) -> list[str]:
    """Tokens curtos em maiúsculas/sem vogais que parecem abreviações não resolvidas."""
    return [
        w
        for w in re.findall(r"[a-z]{2,5}", sem_acento(descricao_normalizada))
        if not re.search(r"[aeiou]", w) or len(w) <= 3
    ]


def inferir_tipo(tipo_informado: str | None, ncm: str | None, nbs: str | None, descricao_normalizada: str) -> str:
    if tipo_informado in ("produto", "servico"):
        return tipo_informado
    if nbs and not ncm:
        return "servico"
    if ncm and not nbs:
        return "produto"
    d = sem_acento(descricao_normalizada).lower()
    if any(p in d for p in PALAVRAS_SERVICO):
        return "servico"
    if re.search(r"\b\d+\s*(ml|l|kg|g|gr|mg|un|cx|pct)\b", d):
        return "produto"
    return "desconhecido"


def _sem_acento(t: str) -> str:
    return unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()


def remover_marca(texto: str, marca: str | None) -> str:
    """Tira a marca comercial da descrição: marca não define NCM, e itens iguais de marcas diferentes
    passam a ter a mesma análise (uma única chamada de IA para todos)."""
    alvo = re.findall(r"[a-z0-9]+", _sem_acento(marca or ""))
    if not alvo or " ".join(alvo) in ("sem marca", "diversos", "producao propria", "marca propria"):
        return texto
    palavras = texto.split()
    base = [" ".join(re.findall(r"[a-z0-9]+", _sem_acento(w))) for w in palavras]
    n = len(alvo)
    for i in range(len(base) - n + 1):
        if base[i : i + n] == alvo:
            restante = palavras[:i] + palavras[i + n :]
            return " ".join(restante) or texto
    return texto
