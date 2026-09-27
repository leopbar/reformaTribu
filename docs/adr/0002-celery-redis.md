# ADR 0002 — Celery + Redis para tarefas em segundo plano

**Status:** aceito

**Decisão.** Celery com Redis como broker, filas separadas (`ingest`, `pipeline`, `llm`, `reference`,
`export`), `acks_late` e `worker_prefetch_multiplier=1`; beat para tarefas periódicas; Flower para
monitoramento.

**Alternativas.** arq e Dramatiq exigiriam montar agendamento e monitoramento à parte.

**Consequências.** Reentrega automática de tarefas interrompidas combina com o checkpoint do LangGraph
e a idempotência das chamadas de IA.
