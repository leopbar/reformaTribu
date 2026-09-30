"""Catálogo de IA da plataforma: plataformas (com chave), modelos (com preço) e o modelo de cada agente.

- O superadministrador cadastra as chaves e escolhe o modelo de cada agente na tela "Modelos de IA".
- As chaves ficam cifradas no banco (pgcrypto, com o segredo `LLM_KEYS_SECRET` do servidor) e só são
  decifradas no momento da chamada. A tela nunca devolve a chave, só os últimos caracteres.
- O ranking de recomendações é definido aqui (com o motivo de cada posição), a partir dos benchmarks
  públicos e do piloto de supermercado; deve ser revisto com os resultados das avaliações (evals).
- Leituras vêm do banco com cache curto; se as tabelas ainda estiverem vazias, valem os padrões abaixo.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import text

from app.config import get_settings

# ------------------------------------------------------------------------------ plataformas --
PROVEDORES: dict[str, dict[str, Any]] = {
    "anthropic": {
        "nome": "Anthropic (Claude)",
        "base_url": "https://api.anthropic.com",
        "lote": "Message Batches API: 50% de desconto, resultado em até 24 h.",
        "site": "https://console.anthropic.com",
    },
    "openai": {
        "nome": "OpenAI (GPT)",
        "base_url": "https://api.openai.com/v1",
        "lote": "Ainda sem lote neste sistema: as chamadas saem em tempo real, com preço cheio.",
        "site": "https://platform.openai.com",
    },
    "deepseek": {
        "nome": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "lote": "A DeepSeek não tem lote; o preço cai 50% fora do horário de pico (estimativa usa o pico).",
        "site": "https://platform.deepseek.com",
    },
}


@dataclass(frozen=True)
class ModeloPadrao:
    modelo: str
    provedor: str
    nome: str
    entrada: str  # US$ por milhão de tokens
    saida: str
    cache_leitura: str
    mult_cache_escrita: str = "1"
    suporta_lote: bool = False
    suporta_esforco: bool = False
    ativo: bool = True
    notas: str = ""


# Preços consultados em 29/09/2026 (anthropic.com/pricing, developers.openai.com/api/docs/pricing,
# api-docs.deepseek.com/quick_start/pricing). DeepSeek: preço de pico (fora do pico é metade).
MODELOS_PADRAO: tuple[ModeloPadrao, ...] = (
    ModeloPadrao("claude-haiku-4-5-20251001", "anthropic", "Claude Haiku 4.5", "1.00", "5.00", "0.10", "1.25", True),
    ModeloPadrao("claude-sonnet-5", "anthropic", "Claude Sonnet 5", "2.00", "10.00", "0.20", "1.25", True, True),
    ModeloPadrao("claude-opus-5-5", "anthropic", "Claude Opus 5.5", "4.00", "20.00", "0.20", "1.25", True, True),
    ModeloPadrao(
        "claude-fable-5-1", "anthropic", "Claude Fable 5.1", "10.00", "50.00", "0.25", "1.25", True, True, ativo=False
    ),
    ModeloPadrao("gpt-5", "openai", "GPT-5", "1.25", "10.00", "0.125", suporta_esforco=True),
    ModeloPadrao("gpt-5-mini", "openai", "GPT-5 mini", "0.25", "2.00", "0.025", suporta_esforco=True),
    ModeloPadrao("gpt-5-nano", "openai", "GPT-5 nano", "0.05", "0.40", "0.005", suporta_esforco=True),
    ModeloPadrao("gpt-5.6-sol", "openai", "GPT-5.6 Sol", "4.00", "20.00", "0.40", suporta_esforco=True, ativo=False),
    ModeloPadrao("gpt-4.1", "openai", "GPT-4.1", "2.00", "8.00", "0.50", ativo=False),
    ModeloPadrao("gpt-4.1-mini", "openai", "GPT-4.1 mini", "0.40", "1.60", "0.10"),
    ModeloPadrao("gpt-4.1-nano", "openai", "GPT-4.1 nano", "0.10", "0.40", "0.025"),
    ModeloPadrao("deepseek-flash", "deepseek", "DeepSeek Flash", "0.30", "1.20", "0.006"),
    ModeloPadrao("deepseek-v4-pro", "deepseek", "DeepSeek V4-Pro", "1.32", "3.96", "0.044"),
)

# --------------------------------------------------------------------------------- agentes --
AGENTES: dict[str, dict[str, Any]] = {
    "identificador": {
        "nome": "Identificador",
        "funcao": "Escolhe o NCM/NBS certo entre as alternativas oficiais (uma chamada por item).",
        "exige": "Volume alto, saída estruturada, raciocínio moderado.",
        "no": "julgar_coerencia",
        "padrao": "claude-haiku-4-5-20251001",
        "esforco": "medium",
    },
    "segundo_parecer": {
        "nome": "Segundo parecer",
        "funcao": "Revisa a identificação quando toca um alarme; o NCM final é o dele.",
        "exige": "Raciocínio mais forte que o Identificador; poucas chamadas.",
        "no": "escalar",
        "padrao": "claude-sonnet-5",
        "esforco": "medium",
    },
    "navegador": {
        "nome": "Navegador da NCM",
        "funcao": "Para itens sem NCM (ou quando nenhuma alternativa serve), desce pela tabela oficial: "
        "capítulo → posição → código.",
        "exige": "Conhecimento de classificação fiscal; poucas chamadas curtas por item sem código.",
        "no": "navegar_arvore",
        "padrao": "claude-haiku-4-5-20251001",
        "esforco": "medium",
    },
    "jurista": {
        "nome": "Jurista",
        "funcao": "Estuda a lei, a correlação oficial e a tabela cClassTrib e escreve as hipóteses da família.",
        "exige": "O melhor raciocínio jurídico em português; uma chamada por família de NCM.",
        "no": "investigar_enquadramento",
        "padrao": "claude-sonnet-5",
        "esforco": "medium",
    },
    "leitor_fatos": {
        "nome": "Leitor de fatos",
        "funcao": "Procura na descrição os fatos que o parecer pede (separa fato de palpite).",
        "exige": "Tarefa simples de leitura; modelo barato basta.",
        "no": "extrair_fatos",
        "padrao": "claude-haiku-4-5-20251001",
        "esforco": "low",
    },
    "abreviacoes": {
        "nome": "Arrumador (abreviações)",
        "funcao": "Decifra abreviações desconhecidas da descrição (só se ativado nas Configurações).",
        "exige": "Tarefa simples; o mais barato que acerte português.",
        "no": "expandir_abreviacoes",
        "padrao": "claude-haiku-4-5-20251001",
        "esforco": "low",
    },
}
NO_AGENTE = {a["no"]: k for k, a in AGENTES.items()}

# Ranking recomendado por agente (do melhor para o pior no equilíbrio qualidade × custo), com o motivo.
RECOMENDACOES: dict[str, list[tuple[str, str]]] = {
    "identificador": [
        ("claude-haiku-4-5-20251001", "Validado no piloto: acerta o NCM com bom custo por item."),
        ("gpt-5-mini", "Bom raciocínio e preço baixo; gasta tokens de raciocínio (a saída pesa no custo)."),
        ("gpt-4.1-mini", "Barato e rápido, sem raciocínio estendido; bom para descrições claras."),
        ("deepseek-flash", "O mais barato; ainda não validado no nosso conjunto de itens."),
        ("claude-sonnet-5", "Mais preciso em descrições ruins, mas o dobro do preço do Haiku."),
    ],
    "segundo_parecer": [
        ("claude-sonnet-5", "Validado no piloto; corrige bem NCM trocado (ex.: feijão preto × carioca)."),
        ("gpt-5", "Raciocínio forte e preço de entrada menor; saída tão cara quanto o Sonnet."),
        ("deepseek-v4-pro", "Bem mais barato; raciocínio mais fraco nos benchmarks."),
        ("claude-opus-5-5", "Máximo rigor para casos difíceis; o dobro do preço do Sonnet."),
    ],
    "navegador": [
        ("claude-haiku-4-5-20251001", "Conhece bem a nomenclatura e o varejo brasileiro; barato para 2 a 3 passos."),
        ("claude-sonnet-5", "Mais preciso em itens ambíguos (pratos prontos, kits); o dobro do preço."),
        ("gpt-5-mini", "Bom raciocínio a preço baixo; ainda não validado neste passo."),
        ("deepseek-flash", "O mais barato; não validado com a NCM."),
    ],
    "jurista": [
        ("claude-sonnet-5", "Melhor equilíbrio para ler lei em português e citar o trecho; validado no piloto."),
        ("claude-opus-5-5", "Máximo rigor jurídico; o dobro do preço. Vale para bases com muitos conflitos."),
        ("gpt-5", "Raciocínio forte; não validado com a LC 214 no nosso conjunto."),
        ("deepseek-v4-pro", "Cerca de 60% mais barato; mais fraco em raciocínio longo e pode ficar lento."),
    ],
    "leitor_fatos": [
        ("claude-haiku-4-5-20251001", "Validado no piloto; distingue bem fato escrito de palpite."),
        ("gpt-4.1-mini", "Barato e obediente ao formato."),
        ("deepseek-flash", "O mais barato; tarefa simples, risco baixo."),
        ("gpt-5-nano", "Muito barato; qualidade menor em português."),
    ],
    "abreviacoes": [
        ("claude-haiku-4-5-20251001", "Conhece bem abreviações do varejo brasileiro."),
        ("gpt-4.1-nano", "Muito barato para uma tarefa curta."),
        ("deepseek-flash", "O mais barato."),
    ],
}

ESFORCOS = ("low", "medium", "high")


# ----------------------------------------------------------------------------- leitura (cache) --
@dataclass(frozen=True)
class InfoModelo:
    modelo: str
    provedor: str
    nome: str
    entrada: Decimal
    saida: Decimal
    cache_leitura: Decimal
    mult_cache_escrita: Decimal
    suporta_lote: bool
    suporta_esforco: bool
    ativo: bool


_CACHE: dict[str, tuple[float, Any]] = {}
_TTL_S = 30.0


def limpar_cache() -> None:
    _CACHE.clear()


def _cache(nome: str, carregar: Any) -> Any:
    agora = time.monotonic()
    atual = _CACHE.get(nome)
    if atual is not None and agora - atual[0] < _TTL_S:
        return atual[1]
    valor = carregar()
    _CACHE[nome] = (agora, valor)
    return valor


def _conexao() -> Any:
    from app.db.session import sync_engine

    return sync_engine().connect()


def _padroes() -> dict[str, InfoModelo]:
    return {
        m.modelo: InfoModelo(
            m.modelo,
            m.provedor,
            m.nome,
            Decimal(m.entrada),
            Decimal(m.saida),
            Decimal(m.cache_leitura),
            Decimal(m.mult_cache_escrita),
            m.suporta_lote,
            m.suporta_esforco,
            m.ativo,
        )
        for m in MODELOS_PADRAO
    }


def modelos() -> dict[str, InfoModelo]:
    """Catálogo completo (ativos e inativos)."""

    def carregar() -> dict[str, InfoModelo]:
        try:
            with _conexao() as c:
                rows = c.execute(text("SELECT * FROM llm_modelos")).mappings().all()
        except Exception:
            rows = []
        if not rows:
            return _padroes()
        return {
            r["modelo"]: InfoModelo(
                r["modelo"],
                r["provedor"],
                r["nome"],
                Decimal(r["preco_entrada"]),
                Decimal(r["preco_saida"]),
                Decimal(r["preco_cache_leitura"]),
                Decimal(r["mult_cache_escrita"]),
                bool(r["suporta_lote"]),
                bool(r["suporta_esforco"]),
                bool(r["ativo"]),
            )
            for r in rows
        }

    return _cache("modelos", carregar)  # type: ignore[no-any-return]


def provedor_de(modelo: str) -> str:
    info = modelos().get(modelo)
    if info is not None:
        return info.provedor
    if modelo.startswith("claude"):
        return "anthropic"
    if modelo.startswith("deepseek"):
        return "deepseek"
    return "openai"


def info_modelo(modelo: str) -> InfoModelo | None:
    return modelos().get(modelo)


def suporta_lote(modelo: str) -> bool:
    info = info_modelo(modelo)
    return bool(info and info.suporta_lote) if info else provedor_de(modelo) == "anthropic"


def suporta_esforco(modelo: str) -> bool:
    info = info_modelo(modelo)
    if info is not None:
        return info.suporta_esforco
    return "haiku" not in modelo and provedor_de(modelo) == "anthropic"


def agentes_configurados() -> dict[str, dict[str, str]]:
    """Modelo e esforço de cada agente (tela "Modelos de IA"), com os padrões para o que faltar."""

    def carregar() -> dict[str, dict[str, str]]:
        try:
            with _conexao() as c:
                rows = c.execute(text("SELECT agente, modelo, esforco FROM llm_agentes")).mappings().all()
        except Exception:
            rows = []
        salvos = {r["agente"]: {"modelo": r["modelo"], "esforco": r["esforco"]} for r in rows}
        return {k: salvos.get(k) or {"modelo": a["padrao"], "esforco": a["esforco"]} for k, a in AGENTES.items()}

    return _cache("agentes", carregar)  # type: ignore[no-any-return]


# ------------------------------------------------------------------------------------ chaves --
def segredo_chaves() -> str:
    """Segredo do servidor que cifra as chaves de API (derivado do JWT_SECRET se não definido)."""
    s = get_settings()
    if s.llm_keys_secret is not None and s.llm_keys_secret.get_secret_value():
        return s.llm_keys_secret.get_secret_value()
    return hashlib.sha256(b"chaves-llm:" + s.jwt_secret.get_secret_value().encode()).hexdigest()


def _chave_env(provedor: str) -> str | None:
    s = get_settings()
    segredo = {"anthropic": s.anthropic_api_key, "openai": s.openai_api_key, "deepseek": s.deepseek_api_key}.get(
        provedor
    )
    return segredo.get_secret_value() if segredo is not None and segredo.get_secret_value() else None


def credencial(provedor: str) -> tuple[str | None, str]:
    """(chave, base_url) da plataforma: a cadastrada na tela vale mais que a do arquivo .env."""

    def carregar() -> tuple[str | None, str]:
        base = PROVEDORES.get(provedor, {}).get("base_url", "")
        try:
            with _conexao() as c:
                r = (
                    c.execute(
                        text(
                            "SELECT ativo, base_url, CASE WHEN chave_cifrada IS NULL THEN NULL "
                            "ELSE pgp_sym_decrypt(chave_cifrada, :s) END AS chave "
                            "FROM llm_provedores WHERE provedor = :p"
                        ),
                        {"s": segredo_chaves(), "p": provedor},
                    )
                    .mappings()
                    .first()
                )
        except Exception:
            r = None
        if r is not None:
            if not r["ativo"]:
                return None, r["base_url"] or base
            if r["chave"]:
                return str(r["chave"]), r["base_url"] or base
            return _chave_env(provedor), r["base_url"] or base
        return _chave_env(provedor), base

    return _cache(f"cred:{provedor}", carregar)  # type: ignore[no-any-return]
