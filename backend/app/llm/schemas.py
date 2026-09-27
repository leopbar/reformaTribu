"""Esquemas JSON das saídas estruturadas e modelos Pydantic de validação."""

from __future__ import annotations

import unicodedata
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

_ATRIBUTO_OUTRO = {
    "type": "object",
    "properties": {
        "atributo": {"type": "string"},
        "valor": {"type": "string"},
        "evidencia": {"type": "string"},
    },
    "required": ["atributo", "valor", "evidencia"],
    "additionalProperties": False,
}

_PROPRIEDADES_JULGAMENTO: dict[str, Any] = {
    "ncm_atual_coerente": {"anyOf": [{"type": "boolean"}, {"type": "null"}]},
    "codigo_sugerido": {"anyOf": [{"type": "string"}, {"type": "null"}]},
    "codigo_escolhido_da_lista": {"type": "boolean"},
    "nenhum_candidato_serve": {"type": "boolean"},
    "tipo_item": {"type": "string", "enum": ["produto", "servico"]},
    "confianca": {"type": "number"},
    "descricao_suficiente": {"type": "boolean"},
    "atributos_extraidos": {
        "type": "object",
        "properties": {
            "forma_apresentacao": {"type": "string"},
            "adicao_acucar": {"type": "string", "enum": ["sim", "nao", "desconhecido"]},
            "outros": {"type": "array", "items": _ATRIBUTO_OUTRO},
        },
        "required": ["forma_apresentacao", "adicao_acucar", "outros"],
        "additionalProperties": False,
    },
    "justificativa": {"type": "string"},
    "sinais_de_duvida": {"type": "array", "items": {"type": "string"}},
}

SCHEMA_JULGAMENTO: dict[str, Any] = {
    "type": "object",
    "properties": _PROPRIEDADES_JULGAMENTO,
    "required": list(_PROPRIEDADES_JULGAMENTO),
    "additionalProperties": False,
}

SCHEMA_ESCALONAMENTO: dict[str, Any] = {
    "type": "object",
    "properties": {**_PROPRIEDADES_JULGAMENTO, "concorda_com_analise_anterior": {"type": "boolean"}},
    "required": [*_PROPRIEDADES_JULGAMENTO, "concorda_com_analise_anterior"],
    "additionalProperties": False,
}

SCHEMA_CONDICOES: dict[str, Any] = {
    "type": "object",
    "properties": {
        "condicoes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "atributo": {"type": "string"},
                    "atributo_novo": {"type": "boolean"},
                    "fonte": {"type": "string", "enum": ["item", "empresa", "operacao"]},
                    "deve_ser": {"type": "string"},
                    "pergunta": {"type": "string"},
                    "trecho_legal": {"type": "string"},
                },
                "required": ["atributo", "atributo_novo", "fonte", "deve_ser", "pergunta", "trecho_legal"],
                "additionalProperties": False,
            },
        },
        "excecoes_textuais": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"descricao": {"type": "string"}, "trecho_legal": {"type": "string"}},
                "required": ["descricao", "trecho_legal"],
                "additionalProperties": False,
            },
        },
        "observacoes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["condicoes", "excecoes_textuais", "observacoes"],
    "additionalProperties": False,
}

SCHEMA_ABREVIACOES: dict[str, Any] = {
    "type": "object",
    "properties": {
        "descricao_expandida": {"type": "string"},
        "expansoes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"abreviacao": {"type": "string"}, "expansao": {"type": "string"}},
                "required": ["abreviacao", "expansao"],
                "additionalProperties": False,
            },
        },
        "ambiguas": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["descricao_expandida", "expansoes", "ambiguas"],
    "additionalProperties": False,
}


# ------------------------------------------------------------------ validação (Pydantic) --
class AtributoOutro(BaseModel):
    atributo: str
    valor: str
    evidencia: str = ""


class AtributosExtraidos(BaseModel):
    forma_apresentacao: str = "desconhecido"
    adicao_acucar: Literal["sim", "nao", "desconhecido"] = "desconhecido"
    outros: list[AtributoOutro] = Field(default_factory=list)

    def como_dict(self) -> dict[str, str]:
        """Valores normalizados (minúsculas, sem acentos) para comparar pareceres e regras."""

        def norm(v: str) -> str:
            t = unicodedata.normalize("NFKD", v.strip().lower()).encode("ascii", "ignore").decode()
            return t or "desconhecido"

        d = {"forma_apresentacao": norm(self.forma_apresentacao), "adicao_acucar": self.adicao_acucar}
        for o in self.outros:
            chave = norm(o.atributo).replace(" ", "_")
            if chave != "desconhecido":
                d[chave] = norm(o.valor)
        return d


class Julgamento(BaseModel):
    ncm_atual_coerente: bool | None
    codigo_sugerido: str | None
    codigo_escolhido_da_lista: bool
    nenhum_candidato_serve: bool
    tipo_item: Literal["produto", "servico"]
    confianca: float
    descricao_suficiente: bool
    atributos_extraidos: AtributosExtraidos
    justificativa: str
    sinais_de_duvida: list[str] = Field(default_factory=list)

    @field_validator("confianca")
    @classmethod
    def _limitar(cls, v: float) -> float:
        return max(0.0, min(1.0, float(v)))

    @field_validator("codigo_sugerido")
    @classmethod
    def _digitos(cls, v: str | None) -> str | None:
        if v is None:
            return None
        d = "".join(c for c in v if c.isdigit())
        return d or None


class Escalonamento(Julgamento):
    concorda_com_analise_anterior: bool


class CondicaoExtraida(BaseModel):
    atributo: str
    atributo_novo: bool
    fonte: Literal["item", "empresa", "operacao"]
    deve_ser: str
    pergunta: str
    trecho_legal: str


class ExcecaoTextual(BaseModel):
    descricao: str
    trecho_legal: str


class ExtracaoCondicoes(BaseModel):
    condicoes: list[CondicaoExtraida]
    excecoes_textuais: list[ExcecaoTextual]
    observacoes: list[str]


class ExpansaoAbreviacoes(BaseModel):
    descricao_expandida: str
    expansoes: list[dict[str, str]]
    ambiguas: list[str]
