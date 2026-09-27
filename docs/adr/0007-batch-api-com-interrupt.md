# ADR 0007 — Batch API integrada ao LangGraph via interrupt()

**Decisão.** Em modo lote, o nó de IA grava a requisição (`llm_calls`, status `na_fila`) e chama
`interrupt()`. A tarefa coletora envia os lotes, consulta o andamento, grava as respostas e só então
retoma os grafos com `Command(resume=...)`. O nó, ao ser reexecutado, encontra a resposta gravada.

**Consequências.** Nenhuma requisição é cobrada duas vezes (chave de idempotência única), e o mesmo
código de nó serve para tempo real e lote. Itens com falha definitiva no lote vão para análise humana.
