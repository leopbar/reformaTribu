"""Várias plataformas de IA: conversão das respostas, preços, lote e estimativa por agente."""

from __future__ import annotations

from decimal import Decimal

from app.ingest import estimate
from app.llm import catalogo, provedores
from app.llm.pricing import custo_chamada


def test_plataforma_de_cada_modelo() -> None:
    assert catalogo.provedor_de("claude-sonnet-5") == "anthropic"
    assert catalogo.provedor_de("gpt-5-mini") == "openai"
    assert catalogo.provedor_de("deepseek-v4-pro") == "deepseek"
    assert catalogo.provedor_de("deepseek-modelo-novo") == "deepseek"


def test_resposta_openai_vira_formato_unico() -> None:
    dados = {
        "id": "chatcmpl-1",
        "model": "gpt-5-mini",
        "choices": [{"message": {"content": '{"a": 1}'}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 200, "prompt_tokens_details": {"cached_tokens": 800}},
    }
    m = provedores.normalizar_compativel(dados, "openai")
    assert m["stop_reason"] == "end_turn"
    assert m["content"][0]["text"] == '{"a": 1}'
    assert m["usage"] == {
        "input_tokens": 200,
        "output_tokens": 200,
        "cache_read_input_tokens": 800,
        "cache_creation_input_tokens": 0,
    }


def test_resposta_deepseek_cortada_e_cache() -> None:
    dados = {
        "choices": [{"message": {"content": "{"}, "finish_reason": "length"}],
        "usage": {"prompt_tokens": 500, "completion_tokens": 10, "prompt_cache_hit_tokens": 300},
    }
    m = provedores.normalizar_compativel(dados, "deepseek")
    assert m["stop_reason"] == "max_tokens"
    assert m["usage"]["cache_read_input_tokens"] == 300
    assert m["usage"]["input_tokens"] == 200


def test_lote_so_da_desconto_onde_existe() -> None:
    assert custo_chamada("claude-sonnet-5", 1_000_000, 0, 0, 0, lote=True) == Decimal("1.000000")
    # OpenAI e DeepSeek: sem lote neste sistema, preço cheio.
    assert custo_chamada("gpt-5", 1_000_000, 0, 0, 0, lote=True) == Decimal("1.250000")
    assert custo_chamada("deepseek-v4-pro", 1_000_000, 0, 0, 0, lote=True) == Decimal("1.320000")


def test_cache_automatico_nao_cobra_escrita_extra() -> None:
    # Anthropic: escrever no cache custa 1,25x; OpenAI: o cache é automático (1x).
    assert custo_chamada("claude-sonnet-5", 0, 0, 1_000_000, 0) == Decimal("2.500000")
    assert custo_chamada("gpt-5-mini", 0, 0, 1_000_000, 0) == Decimal("0.250000")


def test_estimativa_acompanha_o_modelo_de_cada_agente() -> None:
    previsao = {"itens_com_ia": 100, "familias_novas": 40}
    caro = estimate.estimar(previsao, 0.4, lote=False, modelos={"jurista": "claude-opus-5-5"})
    barato = estimate.estimar(previsao, 0.4, lote=False, modelos={"jurista": "deepseek-v4-pro"})
    assert caro["custo_usd_estimado"] > barato["custo_usd_estimado"]
    jur = next(a for a in barato["agentes"] if a["agente"] == "jurista")
    assert jur["modelo"] == "deepseek-v4-pro" and jur["chamadas"] == 40
    lote = estimate.estimar(previsao, 0.4, lote=True, modelos={"jurista": "deepseek-v4-pro"})
    assert "DeepSeek V4-Pro" in lote["sem_lote"]
    assert next(a for a in lote["agentes"] if a["agente"] == "identificador")["lote"] is True


def test_recomendacoes_apontam_para_modelos_do_catalogo() -> None:
    conhecidos = {m.modelo for m in catalogo.MODELOS_PADRAO}
    for agente, ranking in catalogo.RECOMENDACOES.items():
        assert agente in catalogo.AGENTES
        assert ranking and all(m in conhecidos for m, _ in ranking)
        assert catalogo.AGENTES[agente]["padrao"] in conhecidos
