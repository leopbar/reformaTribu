"""Carregamento dos prompts versionados (arquivos em backend/prompts/<nome>/<versao>.md)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"

# Versão ativa de cada prompt. Mudar aqui exige rodar `make eval` (ver docs/avaliacao.md).
VERSOES_ATIVAS: dict[str, str] = {
    "julgar_coerencia": "v2",
    "escalar": "v2",
    "extrair_condicoes": "v1",
    "expandir_abreviacoes": "v1",
    "investigar_enquadramento": "v3",
    "extrair_fatos": "v2",
    "navegar_arvore": "v2",
}


@dataclass(frozen=True)
class Prompt:
    nome: str
    versao: str
    texto: str
    sha: str

    @property
    def rotulo(self) -> str:
        """Identificador gravado em cada chamada: nome@versao#hash."""
        return f"{self.nome}@{self.versao}#{self.sha}"


@lru_cache
def carregar(nome: str, versao: str | None = None) -> Prompt:
    v = versao or VERSOES_ATIVAS[nome]
    caminho = PROMPTS_DIR / nome / f"{v}.md"
    texto = caminho.read_text(encoding="utf-8").strip()
    return Prompt(nome=nome, versao=v, texto=texto, sha=hashlib.sha256(texto.encode()).hexdigest()[:10])
