"""Motor de regras declarativo: aplica as regras aprovadas a um código NCM/NBS e aos atributos do item.

Nenhuma regra legal está escrita aqui. O motor só interpreta a estrutura declarativa
(abrangência por prefixo de código, exceções, condições e vigência) guardada no banco.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import LegalRule
from app.models.enums import StatusRegra, TipoTratamento
from app.pipeline.reasons import Motivo

_STOP = {
    "exceto",
    "excetuados",
    "produtos",
    "produto",
    "codigos",
    "codigo",
    "subposicao",
    "subposicoes",
    "posicao",
    "ncm",
    "sh",
    "dos",
    "das",
    "de",
    "da",
    "do",
    "e",
    "os",
    "as",
    "o",
    "a",
    "com",
    "sem",
    "para",
    "em",
    "no",
    "na",
    "caracteristicas",
    "tecnicas",
    "especificas",
    "uso",
    "operacional",
    "forcas",
    "armadas",
    "orgaos",
    "seguranca",
    "publica",
    "ressalvados",
    "ressalvadas",
    "classificados",
    "classificadas",
    "outros",
    "outras",
    "seguintes",
    "demais",
    "quaisquer",
    "qualquer",
    "materia",
    "legislacao",
}


def normalizar_texto(t: str) -> str:
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", t)).strip()


def palavras_chave(t: str) -> set[str]:
    return {w for w in normalizar_texto(t).split() if len(w) >= 5 and w not in _STOP and not w.isdigit()}


@dataclass(frozen=True)
class RegraMem:
    id: uuid.UUID
    slug: str
    versao: int
    status: str
    anexo: str | None
    item: str | None
    descricao_legal: str
    dispositivo_legal: str
    tipo_tratamento: str
    tipo_codigo: str | None
    universal: bool
    codigos: tuple[str, ...]
    excecoes_codigo: tuple[str, ...]
    excecoes_texto: tuple[str, ...]
    condicoes: tuple[dict[str, Any], ...]
    cst: str | None
    cclasstrib: str | None
    vigencia_inicio: date | None
    vigencia_fim: date | None
    prioridade: int
    controverso: bool
    nota_controversia: str | None

    @staticmethod
    def de(r: LegalRule) -> RegraMem:
        return RegraMem(
            id=r.id,
            slug=r.slug,
            versao=r.versao,
            status=r.status,
            anexo=r.anexo,
            item=r.item,
            descricao_legal=r.descricao_legal,
            dispositivo_legal=r.dispositivo_legal,
            tipo_tratamento=r.tipo_tratamento,
            tipo_codigo=r.tipo_codigo,
            universal=bool((r.abrangencia or {}).get("universal")),
            codigos=tuple(c["codigo"] for c in (r.abrangencia or {}).get("codigos", [])),
            excecoes_codigo=tuple(e["codigo"] for e in r.excecoes or [] if e.get("codigo")),
            excecoes_texto=tuple(e["descricao"] for e in r.excecoes or [] if e.get("descricao")),
            condicoes=tuple(r.condicoes or []),
            cst=r.cst_ibs_cbs,
            cclasstrib=r.cclasstrib,
            vigencia_inicio=r.vigencia_inicio,
            vigencia_fim=r.vigencia_fim,
            prioridade=r.prioridade,
            controverso=r.controverso,
            nota_controversia=r.nota_controversia,
        )

    def vigente(self, d: date) -> bool:
        return (self.vigencia_inicio is None or self.vigencia_inicio <= d) and (
            self.vigencia_fim is None or self.vigencia_fim >= d
        )

    def resumo(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "slug": self.slug,
            "versao": self.versao,
            "anexo": self.anexo,
            "item": self.item,
            "dispositivo": self.dispositivo_legal,
            "cclasstrib": self.cclasstrib,
            "tipo_tratamento": self.tipo_tratamento,
        }


@dataclass
class ConjuntoRegras:
    aprovadas: list[RegraMem]
    pendentes: list[RegraMem]
    _indice: dict[tuple[str, str], list[RegraMem]] = field(default_factory=dict)
    padrao: RegraMem | None = None
    slugs_aprovados: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        idx: dict[tuple[str, str], list[RegraMem]] = defaultdict(list)
        for r in [*self.aprovadas, *self.pendentes]:
            if r.universal:
                if r.status == StatusRegra.APROVADA and r.tipo_tratamento == TipoTratamento.TRIBUTACAO_INTEGRAL:
                    self.padrao = r
                continue
            for c in r.codigos:
                idx[(r.tipo_codigo or "", c)].append(r)
        self._indice = dict(idx)
        self.slugs_aprovados = {r.slug for r in self.aprovadas}

    @classmethod
    def carregar(cls, session: Session, aprovadas: list[Any], pendentes: list[Any]) -> ConjuntoRegras:
        ids = [uuid.UUID(str(i)) for i in [*aprovadas, *pendentes]]
        regras = {r.id: RegraMem.de(r) for r in session.scalars(select(LegalRule).where(LegalRule.id.in_(ids)))}
        return cls(
            aprovadas=[regras[uuid.UUID(str(i))] for i in aprovadas if uuid.UUID(str(i)) in regras],
            pendentes=[regras[uuid.UUID(str(i))] for i in pendentes if uuid.UUID(str(i)) in regras],
        )

    def que_abrangem(self, tipo: str, codigo: str) -> list[RegraMem]:
        vistos: dict[uuid.UUID, RegraMem] = {}
        for n in range(1, len(codigo) + 1):
            for r in self._indice.get((tipo, codigo[:n]), []):
                vistos[r.id] = r
        return list(vistos.values())


@dataclass
class Pergunta:
    atributo: str
    pergunta: str
    fonte: str
    regra: str

    def como_dict(self) -> dict[str, str]:
        return {"atributo": self.atributo, "pergunta": self.pergunta, "fonte": self.fonte, "regra": self.regra}


@dataclass
class Enquadramento:
    regra: RegraMem | None = None
    cst: str | None = None
    cclasstrib: str | None = None
    tipo_tratamento: str | None = None
    dispositivo: str | None = None
    motivos: list[str] = field(default_factory=list)
    perguntas: list[Pergunta] = field(default_factory=list)
    consideradas: list[dict[str, Any]] = field(default_factory=list)
    imposto_seletivo: bool = False
    regra_seletivo: RegraMem | None = None
    certeza: float = 0.0

    @property
    def definido(self) -> bool:
        return (
            self.cclasstrib is not None and not self.perguntas and Motivo.REGRA_PENDENTE_DE_REVISAO not in self.motivos
        )


def _valor(v: Any) -> str:
    if isinstance(v, bool):
        return "sim" if v else "nao"
    if v is None:
        return "desconhecido"
    s = normalizar_texto(str(v))
    return {
        "s": "sim",
        "true": "sim",
        "verdadeiro": "sim",
        "n": "nao",
        "false": "nao",
        "falso": "nao",
        "nao sei": "desconhecido",
        "": "desconhecido",
    }.get(s, s)


def avaliar_condicoes(regra: RegraMem, atributos: dict[str, dict[str, Any]]) -> tuple[str, list[Pergunta]]:
    """Devolve ('ok' | 'falha' | 'pendente', perguntas pendentes)."""
    pendentes: list[Pergunta] = []
    for c in regra.condicoes:
        fonte = c.get("fonte", "item")
        valor = _valor(atributos.get(fonte, {}).get(c["atributo"]))
        esperado = _valor(c.get("deve_ser"))
        if valor == "desconhecido":
            pendentes.append(Pergunta(c["atributo"], c.get("pergunta") or c["atributo"], fonte, regra.slug))
        elif valor != esperado:
            return "falha", []
    return ("pendente", pendentes) if pendentes else ("ok", [])


def enquadrar(
    conjunto: ConjuntoRegras,
    tipo_codigo: str,
    codigo: str,
    descricao: str,
    atributos: dict[str, dict[str, Any]],
    data_referencia: date,
) -> Enquadramento:
    """Aplica as regras ao código. `atributos` = {"item": {...}, "empresa": {...}, "operacao": {...}}."""
    res = Enquadramento()
    chaves_desc = palavras_chave(descricao)
    aplicaveis: list[RegraMem] = []
    condicionais: list[tuple[RegraMem, list[Pergunta]]] = []
    pendentes_revisao: list[RegraMem] = []

    for r in sorted(conjunto.que_abrangem(tipo_codigo, codigo), key=lambda x: x.prioridade):
        if not r.vigente(data_referencia):
            res.consideradas.append({**r.resumo(), "resultado": "fora_de_vigencia"})
            continue
        if any(codigo.startswith(e) for e in r.excecoes_codigo):
            res.consideradas.append({**r.resumo(), "resultado": "excecao_por_codigo"})
            continue
        if r.status != StatusRegra.APROVADA:
            if r.slug not in conjunto.slugs_aprovados:
                pendentes_revisao.append(r)
                res.consideradas.append({**r.resumo(), "resultado": "regra_pendente_de_revisao"})
            continue
        excecao_textual = next((e for e in r.excecoes_texto if palavras_chave(e) & chaves_desc), None)
        if excecao_textual:
            res.motivos.append(Motivo.EXCECAO_LEGAL_POSSIVEL)
            res.perguntas.append(
                Pergunta("excecao_textual", f"O item se enquadra na exceção “{excecao_textual}”?", "item", r.slug)
            )
            res.consideradas.append({**r.resumo(), "resultado": "excecao_textual_possivel", "excecao": excecao_textual})
            continue
        situacao, perguntas = avaliar_condicoes(r, atributos)
        if situacao == "falha":
            res.consideradas.append({**r.resumo(), "resultado": "condicao_nao_atendida"})
        elif situacao == "pendente":
            condicionais.append((r, perguntas))
            res.consideradas.append(
                {**r.resumo(), "resultado": "condicao_pendente", "perguntas": [p.pergunta for p in perguntas]}
            )
        else:
            if r.tipo_tratamento == TipoTratamento.IMPOSTO_SELETIVO:
                res.imposto_seletivo, res.regra_seletivo = True, r
                res.consideradas.append({**r.resumo(), "resultado": "imposto_seletivo"})
            else:
                aplicaveis.append(r)
                res.consideradas.append({**r.resumo(), "resultado": "aplicavel"})

    if res.imposto_seletivo:
        res.motivos.append(Motivo.SUJEITO_A_IMPOSTO_SELETIVO)
    cond_ibs = [(r, p) for r, p in condicionais if r.tipo_tratamento != TipoTratamento.IMPOSTO_SELETIVO]
    cond_is = [(r, p) for r, p in condicionais if r.tipo_tratamento == TipoTratamento.IMPOSTO_SELETIVO]
    if cond_is:
        res.motivos.append(Motivo.CONDICAO_LEGAL_NAO_VERIFICAVEL)
        res.perguntas.extend(p for _, ps in cond_is for p in ps)
    if pendentes_revisao:
        res.motivos.append(Motivo.REGRA_PENDENTE_DE_REVISAO)

    # Tratamento de IBS/CBS
    ccts_aplicaveis = {r.cclasstrib for r in aplicaveis}
    ccts_condicionais = {r.cclasstrib for r, _ in cond_ibs}
    escolhida: RegraMem | None = None
    if len(ccts_aplicaveis) == 1 and not (ccts_condicionais - ccts_aplicaveis):
        escolhida = aplicaveis[0]
    elif len(ccts_aplicaveis) > 1:
        res.motivos.append(Motivo.MULTIPLAS_REGRAS_APLICAVEIS)
        res.perguntas.append(
            Pergunta(
                "regra_aplicavel",
                "Mais de um enquadramento legal se aplica ao código: "
                + "; ".join(f"{r.dispositivo_legal} (cClassTrib {r.cclasstrib})" for r in aplicaveis)
                + ". Qual corresponde à operação?",
                "operacao",
                aplicaveis[0].slug,
            )
        )
    elif cond_ibs:
        res.motivos.append(Motivo.CONDICAO_LEGAL_NAO_VERIFICAVEL)
        for _, ps in cond_ibs:
            for p in ps:
                if all(p.pergunta != q.pergunta for q in res.perguntas):
                    res.perguntas.append(p)
    elif not aplicaveis and not pendentes_revisao and Motivo.EXCECAO_LEGAL_POSSIVEL not in res.motivos:
        if conjunto.padrao is not None:
            escolhida = conjunto.padrao
            res.consideradas.append({**conjunto.padrao.resumo(), "resultado": "regra_padrao"})
        else:
            res.motivos.append(Motivo.BASE_REFERENCIA_INCOMPLETA)

    if escolhida is not None and not pendentes_revisao:
        res.regra, res.cst, res.cclasstrib = escolhida, escolhida.cst, escolhida.cclasstrib
        res.tipo_tratamento, res.dispositivo = escolhida.tipo_tratamento, escolhida.dispositivo_legal
        if escolhida.controverso:
            res.motivos.append(Motivo.CASO_CONTROVERSO)
        res.certeza = 1.0 if not res.perguntas and not escolhida.controverso else 0.5
    res.motivos = list(dict.fromkeys(res.motivos))
    return res
