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
    "codigos_alternativos": {"type": "array", "items": {"type": "string"}},
    # ADR 0029: a dúvida aponta as palavras da descrição que a criam ("" = informação que falta).
    "duvidas": {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {"duvida": {"type": "string"}, "trecho": {"type": "string"}},
            "required": ["duvida", "trecho"],
            "additionalProperties": False,
        },
    },
    # ADR 0029: opções em linguagem de loja para a pergunta "o que é este item?".
    "opcoes_para_o_operador": {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {"codigo": {"type": "string"}, "rotulo": {"type": "string"}},
            "required": ["codigo", "rotulo"],
            "additionalProperties": False,
        },
    },
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


class DuvidaIdentificacao(BaseModel):
    duvida: str
    trecho: str = ""


class OpcaoOperador(BaseModel):
    codigo: str
    rotulo: str

    @field_validator("codigo")
    @classmethod
    def _digitos(cls, v: str) -> str:
        return "".join(c for c in v if c.isdigit())


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
    # Outros códigos da lista que a dúvida poderia justificar (vazio nas análises antigas).
    codigos_alternativos: list[str] = Field(default_factory=list)
    # Instrução v3 (ADR 0029); vazios nas análises antigas.
    duvidas: list[DuvidaIdentificacao] = Field(default_factory=list)
    opcoes_para_o_operador: list[OpcaoOperador] = Field(default_factory=list)

    @field_validator("codigos_alternativos")
    @classmethod
    def _so_digitos(cls, v: list[str]) -> list[str]:
        return [d for d in ("".join(c for c in x if c.isdigit()) for x in v) if d][:3]

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


# ------------------------------------------------------------ analista fiscal (investigação) --
_FUNDAMENTO = {
    "type": "object",
    "properties": {"ref": {"type": "string"}, "trecho": {"type": "string"}},
    "required": ["ref", "trecho"],
    "additionalProperties": False,
}
_CONDICAO = {
    "type": "object",
    "properties": {
        "fato": {"type": "string"},
        "valor_exigido": {"type": "string"},
        "explicacao": {"type": "string"},
    },
    "required": ["fato", "valor_exigido", "explicacao"],
    "additionalProperties": False,
}
_EXCECAO = {
    "type": "object",
    "properties": {
        "descricao": {"type": "string"},
        "fato": {"type": "string"},
        "valor_que_exclui": {"type": "string"},
    },
    "required": ["descricao", "fato", "valor_que_exclui"],
    "additionalProperties": False,
}
_HIPOTESE = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "titulo": {"type": "string"},
        "tipo": {"type": "string", "enum": ["beneficio", "regime_especifico", "regra_geral", "nao_incidencia"]},
        "cclasstrib": {"type": "string"},
        "condicoes": {"type": "array", "items": _CONDICAO},
        "excecoes": {"type": "array", "items": _EXCECAO},
        "fundamentos": {"type": "array", "items": _FUNDAMENTO},
        "explicacao": {"type": "string"},
    },
    "required": ["id", "titulo", "tipo", "cclasstrib", "condicoes", "excecoes", "fundamentos", "explicacao"],
    "additionalProperties": False,
}
_FATO_NECESSARIO = {
    "type": "object",
    "properties": {
        "fato": {"type": "string"},
        "escopo": {"type": "string", "enum": ["empresa", "item"]},
        "pergunta": {"type": "string"},
        "opcoes": {"type": "array", "items": {"type": "string"}},
        "como_identificar_na_descricao": {"type": "string"},
    },
    "required": ["fato", "escopo", "pergunta", "opcoes", "como_identificar_na_descricao"],
    "additionalProperties": False,
}
SCHEMA_INVESTIGACAO: dict[str, Any] = {
    "type": "object",
    "properties": {
        "entendimento": {"type": "string"},
        "hipoteses": {"type": "array", "items": _HIPOTESE},
        "fatos_necessarios": {"type": "array", "items": _FATO_NECESSARIO},
        "imposto_seletivo": {
            "type": "object",
            "properties": {
                "situacao": {"type": "string", "enum": ["nao_sujeito", "sujeito", "depende"]},
                "condicoes": {"type": "array", "items": _CONDICAO},
                "fundamentos": {"type": "array", "items": _FUNDAMENTO},
                "explicacao": {"type": "string"},
            },
            "required": ["situacao", "condicoes", "fundamentos", "explicacao"],
            "additionalProperties": False,
        },
        "conflitos": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "descricao": {"type": "string"},
                    "refs": {"type": "array", "items": {"type": "string"}},
                    "muda_resultado": {"type": "boolean"},
                    "cclasstrib_em_jogo": {"type": "array", "items": {"type": "string"}},
                    "fato_que_decide": {"type": "string"},
                    "valor_para_o_outro_enquadramento": {"type": "string"},
                },
                "required": [
                    "descricao",
                    "refs",
                    "muda_resultado",
                    "cclasstrib_em_jogo",
                    "fato_que_decide",
                    "valor_para_o_outro_enquadramento",
                ],
                "additionalProperties": False,
            },
        },
        "observacoes": {"type": "string"},
    },
    "required": ["entendimento", "hipoteses", "fatos_necessarios", "imposto_seletivo", "conflitos", "observacoes"],
    "additionalProperties": False,
}


class Fundamento(BaseModel):
    ref: str
    trecho: str = ""


class CondicaoHipotese(BaseModel):
    fato: str
    valor_exigido: str
    explicacao: str = ""


class ExcecaoHipotese(BaseModel):
    descricao: str
    fato: str = ""
    valor_que_exclui: str = ""


class Hipotese(BaseModel):
    id: str
    titulo: str
    tipo: Literal["beneficio", "regime_especifico", "regra_geral", "nao_incidencia"]
    cclasstrib: str
    condicoes: list[CondicaoHipotese] = Field(default_factory=list)
    excecoes: list[ExcecaoHipotese] = Field(default_factory=list)
    fundamentos: list[Fundamento] = Field(default_factory=list)
    explicacao: str = ""

    @field_validator("cclasstrib")
    @classmethod
    def _digitos(cls, v: str) -> str:
        return "".join(c for c in v if c.isdigit())


class FatoNecessario(BaseModel):
    fato: str
    escopo: Literal["empresa", "item"]
    pergunta: str
    opcoes: list[str] = Field(default_factory=list)
    como_identificar_na_descricao: str = ""


class ImpostoSeletivo(BaseModel):
    situacao: Literal["nao_sujeito", "sujeito", "depende"]
    condicoes: list[CondicaoHipotese] = Field(default_factory=list)
    fundamentos: list[Fundamento] = Field(default_factory=list)
    explicacao: str = ""


class Conflito(BaseModel):
    descricao: str
    refs: list[str] = Field(default_factory=list)
    # Só um conflito que muda o cClassTrib aplicado trava o item (versões antigas não têm os campos).
    muda_resultado: bool = True
    cclasstrib_em_jogo: list[str] = Field(default_factory=list)
    # ADR 0029: o fato que decide entre as fontes e o valor que levaria ao outro cClassTrib ("" = nenhum).
    fato_que_decide: str = ""
    valor_para_o_outro_enquadramento: str = ""


class Investigacao(BaseModel):
    entendimento: str
    hipoteses: list[Hipotese]
    fatos_necessarios: list[FatoNecessario] = Field(default_factory=list)
    imposto_seletivo: ImpostoSeletivo
    conflitos: list[Conflito] = Field(default_factory=list)
    observacoes: str = ""


# ------------------------------------------------------------ analista fiscal (fatos do item) --
SCHEMA_FATOS_ITEM: dict[str, Any] = {
    "type": "object",
    "properties": {
        "fatos": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "fato": {"type": "string"},
                    "valor": {"type": "string"},
                    "base": {"type": "string", "enum": ["explicito", "inferencia", "sem_informacao"]},
                    "evidencia": {"type": "string"},
                },
                "required": ["fato", "valor", "base", "evidencia"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["fatos"],
    "additionalProperties": False,
}


class FatoExtraido(BaseModel):
    fato: str
    valor: str
    base: Literal["explicito", "inferencia", "sem_informacao"]
    evidencia: str = ""


class FatosItem(BaseModel):
    fatos: list[FatoExtraido]


# ------------------------------------------------------------ busca guiada pela árvore oficial --
SCHEMA_NAVEGACAO: dict[str, Any] = {
    "type": "object",
    "properties": {
        "escolha": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "alternativas": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "codigo": {"type": "string"},
                    "motivo": {"type": "string"},
                    "rotulo": {"type": "string"},
                },
                "required": ["codigo", "motivo", "rotulo"],
                "additionalProperties": False,
            },
        },
        "confianca": {"type": "number"},
        "justificativa": {"type": "string"},
        "rotulo": {"type": "string"},
    },
    "required": ["escolha", "alternativas", "confianca", "justificativa", "rotulo"],
    "additionalProperties": False,
}


class AlternativaArvore(BaseModel):
    codigo: str
    motivo: str = ""
    # O que o item é, em linguagem de loja, se esta opção estiver certa (instrução v4): vira opção da
    # pergunta "o que é este item?" ao operador.
    rotulo: str = ""


class NavegacaoArvore(BaseModel):
    escolha: str | None
    alternativas: list[AlternativaArvore] = Field(default_factory=list)
    confianca: float
    justificativa: str = ""
    rotulo: str = ""

    @field_validator("confianca")
    @classmethod
    def _limitar(cls, v: float) -> float:
        return max(0.0, min(1.0, float(v)))

    @field_validator("escolha")
    @classmethod
    def _digitos(cls, v: str | None) -> str | None:
        if v is None:
            return None
        d = "".join(c for c in v if c.isdigit())
        return d or None
