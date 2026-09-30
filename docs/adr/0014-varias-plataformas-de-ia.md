# ADR 0014 — Várias plataformas de IA, com modelo escolhido por agente

**Contexto.** O sistema chamava só a API da Anthropic, com os modelos definidos no `.env` ou nas
configurações de cada organização. O custo por planilha pesava, e havia modelos de outras plataformas
(OpenAI, DeepSeek) bem mais baratos para tarefas simples. Não havia como comparar nem trocar sem mexer
no servidor.

**Decisão.**

- Catálogo de IA **da plataforma** (sem `org_id`), mantido pelo superadministrador:
  - `llm_provedores`: plataformas e chaves de API;
  - `llm_modelos`: modelos e preços por milhão de tokens;
  - `llm_agentes`: o modelo e o esforço de cada agente (Identificador, Segundo parecer, Jurista,
    Leitor de fatos e Abreviações).
- As organizações só veem quais modelos estão em uso. A escolha deixou de ser por organização.
- As chaves ficam cifradas no banco (`pgp_sym_encrypt`, com o segredo `LLM_KEYS_SECRET`) e nunca voltam
  para a tela; aparece só o final. As variáveis `*_API_KEY` do `.env` viram reserva.
- Um conector por plataforma (`app/llm/provedores.py`) converte a resposta para o formato da Messages
  API. Registro, custo, idempotência e validação continuam únicos no gateway.
  - OpenAI: `response_format` json_schema (não estrito, porque os esquemas têm campos opcionais).
  - DeepSeek: modo JSON, com o esquema escrito no bloco de sistema.
  - Toda resposta passa pela validação Pydantic.
- Lote só para modelos com Batch API implementada (Anthropic). Os demais saem em tempo real com preço
  cheio, e a estimativa mostra isso.
- Recomendações: um ranking por agente, definido em `app/llm/catalogo.py` com o motivo de cada posição.
  Deve ser revisto com os resultados das avaliações.
- Os modelos ficam **congelados na auditoria** ao iniciar (`configuracao.modelos`). Trocar o modelo não
  refaz pareceres já guardados. O botão "Refazer com o modelo atual" substitui a tese: a antiga fica no
  histórico com a chave sufixada, e a chave de idempotência da chamada é liberada. Em seguida os itens da
  auditoria são reprocessados.
- A estimativa de custo é recalculada, antes de iniciar, com o modelo atual de cada agente, e mostra o
  custo por agente.

**Consequências.** Trocar para um modelo mais barato reduz o custo imediatamente, mas a qualidade muda,
principalmente no Jurista. A recomendação é testar numa planilha pequena e comparar na aba "Caminho
pelos agentes". Os preços do catálogo precisam ser mantidos pelo superadministrador quando as
plataformas mudarem a tabela.

**Atualizações.** Agente "Navegador da NCM" acrescentado ao catálogo (ADR 0017). Reanálise de auditoria
concluída passa a usar os modelos escolhidos hoje (ADR 0021). Modo estrito na OpenAI e mensagens de falha
de plataforma (ADR 0023). Tempos medidos por modelo e impacto no prazo (ADR 0024).
