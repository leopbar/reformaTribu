"""Formato declarativo das regras (o mesmo usado na exportação/importação YAML)."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator

from app.core.codes import somente_digitos

Nivel = Literal["capitulo", "posicao", "subposicao", "item", "subitem", "secao"]


def nivel_por_tamanho(tipo: str, codigo: str) -> str:
    n = len(codigo)
    if tipo == "nbs":
        return {1: "secao", 3: "capitulo", 5: "posicao", 6: "subposicao", 7: "subposicao", 8: "item", 9: "item"}.get(
            n, "item"
        )
    return {2: "capitulo", 4: "posicao", 5: "subposicao", 6: "subposicao", 7: "item", 8: "item"}.get(n, "item")


class CodigoAbrangido(BaseModel):
    codigo: str
    nivel: str = "item"

    @field_validator("codigo")
    @classmethod
    def _digitos(cls, v: str) -> str:
        d = somente_digitos(v)
        if not d:
            raise ValueError("Código vazio.")
        return d


class Abrangencia(BaseModel):
    tipo_codigo: Literal["ncm", "nbs"] | None = None
    universal: bool = False  # regra padrão (tributação integral) vale para qualquer código
    codigos: list[CodigoAbrangido] = Field(default_factory=list)


class Excecao(BaseModel):
    codigo: str | None = None
    nivel: str | None = None
    descricao: str | None = None
    trecho_legal: str | None = None


class Condicao(BaseModel):
    atributo: str
    fonte: Literal["item", "empresa", "operacao"] = "item"
    deve_ser: str  # "sim" | "nao" | valor
    pergunta: str
    trecho_legal: str | None = None


class RegraDeclarativa(BaseModel):
    id: str
    versao: int = 1
    anexo: str | None = None
    item: str | None = None
    titulo_anexo: str | None = None
    descricao_legal: str
    dispositivo_legal: str
    tipo_tratamento: str
    abrangencia: Abrangencia
    excecoes: list[Excecao] = Field(default_factory=list)
    condicoes: list[Condicao] = Field(default_factory=list)
    cst_ibs_cbs: str | None = None
    cclasstrib: str | None = None
    vigencia: dict[str, date | None] = Field(default_factory=lambda: dict[str, date | None](inicio=None, fim=None))
    prioridade: int = 100
    controverso: bool = False
    nota_controversia: str | None = None
    status_revisao: str = "pendente_revisao"
    revisado_por: str | None = None
    origem: str | None = None


def regra_para_declarativa(r: Any) -> RegraDeclarativa:
    return RegraDeclarativa(
        id=r.slug,
        versao=r.versao,
        anexo=r.anexo,
        item=r.item,
        titulo_anexo=r.titulo_anexo,
        descricao_legal=r.descricao_legal,
        dispositivo_legal=r.dispositivo_legal,
        tipo_tratamento=r.tipo_tratamento,
        abrangencia=Abrangencia(tipo_codigo=r.tipo_codigo, **(r.abrangencia or {})),
        excecoes=[Excecao(**e) for e in r.excecoes or []],
        condicoes=[Condicao(**c) for c in r.condicoes or []],
        cst_ibs_cbs=r.cst_ibs_cbs,
        cclasstrib=r.cclasstrib,
        vigencia={"inicio": r.vigencia_inicio, "fim": r.vigencia_fim},
        prioridade=r.prioridade,
        controverso=r.controverso,
        nota_controversia=r.nota_controversia,
        status_revisao=r.status,
        revisado_por=r.revisado_por_email,
        origem=r.origem,
    )


def para_yaml(regras: list[RegraDeclarativa]) -> str:
    docs = [r.model_dump(mode="json", exclude_none=True) for r in regras]
    return yaml.safe_dump_all(docs, allow_unicode=True, sort_keys=False, width=110)


def de_yaml(texto: str) -> list[RegraDeclarativa]:
    return [RegraDeclarativa.model_validate(d) for d in yaml.safe_load_all(texto) if d]
