# ADR 0023 — Robustez das chamadas de IA entre plataformas

**Status:** aceito · 2026-09-30

## Contexto

Com várias plataformas (ADR 0014), apareceram falhas que não existiam com uma só:

- A conta da Anthropic ficou **sem créditos**. Os itens terminavam "sem código", sem explicação.
- O **GPT-5 nano** (Leitor de fatos) às vezes devolvia **o próprio esquema** em vez da resposta.
- O DeepSeek Flash às vezes devolvia resposta **cortada** por limite de tamanho.
- Um agente novo (Navegador) herdava de auditorias antigas o modelo de outro agente, de uma plataforma
  sem crédito.

## Decisão

- **Mensagens de falha legíveis.** Falta de créditos ("credit balance", "insufficient_quota") e chave
  recusada (401) viram mensagens em português. Elas ficam gravadas na chamada e no item (`erro`) e
  aparecem no detalhe e no caminho dos agentes.
- **Modo estrito na OpenAI** quando o esquema permite: todos os objetos fechados, com todos os campos
  obrigatórios (`esquema_estrito`). Isso obriga o modelo a seguir o formato.
- **JSON dentro de bloco de código** é aceito (o bloco é removido antes da validação).
- Toda resposta, de qualquer plataforma, é **validada com Pydantic**. Uma resposta fora do formato é
  registrada como falha e não usada.
- Falha do Identificador segue para a busca guiada (ADR 0017), em vez de parar o item.
- **Agentes novos** usam o modelo escolhido hoje quando a auditoria não tem modelo congelado para eles.
- **Verificação antes de iniciar:** o sistema confere se existe chave para todas as plataformas dos
  modelos escolhidos. Ele **não consegue** saber se há crédito: falta de crédito só aparece na primeira
  chamada.

## Consequências

- Falhas de plataforma ficam visíveis e têm uma ação clara: recarregar os créditos ou trocar o modelo, e
  depois reanalisar.
- Modelos pequenos continuam podendo errar o conteúdo. A recomendação por agente em "Modelos de IA"
  indica os validados.

## Onde está no código

- `backend/app/llm/provedores.py`: `esquema_estrito`, `normalizar_compativel`.
- `backend/app/llm/gateway.py`: `_mensagem_falha`, `_extrair_json`, `verificar_chaves`.
- `backend/app/pipeline/arvore.py` e `backend/app/pipeline/analista.py`: erro do Navegador gravado no
  item.
- `backend/app/pipeline/context.py`: modelo do Navegador sem herança.

## Verificação

- `backend/tests/test_ia.py`: conversão de respostas, lote, cache, estimativa e modo estrito.
