# ADR 0024 — Execução em pacotes, paralelismo e recuperação de itens travados

**Status:** aceito, com melhorias pendentes · 2026-09-30

## Contexto

O usuário percebeu que a classificação e a reanálise demoram e que os itens aparecem "espalhados" pelo
fluxo, e não numa fila de um por um. Também houve um travamento real: a reanálise parou porque o worker
foi reiniciado durante o processamento.

## Como funciona hoje (decisão vigente)

- O **Distribuidor** separa os itens em **pacotes de 10** (`TAMANHO_BLOCO`) e os põe na fila do Celery.
- O worker tem **4 processos** (`-c 4`). Cada um pega um pacote e leva **um item por vez** por todo o
  grafo. Por isso até 4 itens avançam ao mesmo tempo, cada um numa caixa diferente. Os itens "no
  Distribuidor" são os que esperam uma mesa livre.
- O tempo é dominado pela **espera das respostas de IA**. Tempos medidos por chamada (média / pior caso):

  | Agente | Modelo | Média | Pior caso |
  |---|---|---|---|
  | Segundo parecer | GPT-5 | 219 s | 346 s (média de 2 tentativas: estoura o limite de 120 s) |
  | Jurista | DeepSeek V4-Pro | 47 s | 87 s |
  | Navegador | GPT-5 mini | 9 s | 16 s |
  | Identificador | DeepSeek Flash | 8 s | 38 s |
  | Identificador | Claude Haiku | 2 s | 6 s |

- **Itens da mesma família** chegam juntos ao Jurista: um espera o outro, com uma trava no Redis, para
  reaproveitar a tese em vez de pagar duas vezes.
- **Recuperação:** a cada 5 minutos, `recuperar_travados` recoloca na fila os itens parados há mais de
  15 minutos. O grafo retoma do checkpoint. Uma chamada interrompida é refeita.
- **Regra operacional:** não reiniciar o worker com itens em processamento. Um reinício durante uma
  reanálise mata o pacote em andamento (Celery envia SIGKILL após o *warm shutdown*). Antes de reiniciar,
  conferir que não há itens `processando`, nem `pendente` em auditorias em processamento. Se acontecer,
  recolocar os itens na fila com `recuperar_travados(org, minutos=0)`.

## Melhorias propostas (não implementadas)

- **Pacotes menores** (2 a 3 itens) para usar as 4 mesas em reanálises pequenas. Hoje, 17 itens viram 2
  pacotes e só 2 mesas trabalham.
- **Mais processos** (ex.: 8). O trabalho é quase todo espera de rede.
- **Limite de espera maior** para modelos lentos (GPT-5), para não repetir a pergunta a cada 120 s.
- Trocar o modelo do Segundo parecer para um mais rápido (Claude Sonnet: cerca de 15 s) ou usar esforço
  "Baixo".

## Onde está no código

- `backend/app/audits/processing.py`: `TAMANHO_BLOCO`, `enfileirar_itens`, `processar_itens`,
  `recuperar_travados`.
- `compose.yaml`: `-c 4` no worker.
- `backend/app/worker/celery_app.py`: agenda da recuperação.
- `backend/app/config.py`: `LLM_TIMEOUT_SECONDS`, `LLM_MAX_RETRIES`.
