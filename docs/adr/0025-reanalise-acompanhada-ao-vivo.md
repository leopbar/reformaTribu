# ADR 0025 — Reanálise acompanhada ao vivo

**Status:** aceito · 2026-09-30

## Contexto

Pontos relatados pelo usuário ao clicar em **Reanalisar** no detalhe de um item:

1. O botão voltava a ficar ativo logo depois do clique, e era possível pedir a reanálise de novo.
2. Nada mostrava que o item estava sendo processado. **Aprovar**, **Corrigir** e **Rejeitar** continuavam
   ativos sobre o resultado da análise anterior.
3. A lista de itens só mostrava o status novo depois de recarregar a página (F5).
4. A aba "Caminho pelos agentes" continuava mostrando o caminho antigo. O backend já montava o caminho
   ao vivo a partir do checkpoint do grafo (ADR 0016), mas a tela não sabia que a reanálise tinha
   começado.

## Decisão

- **Status na hora.** A resposta de `POST /itens/{id}/reprocessar` já traz o status novo ("pendente").
  O frontend grava esse status direto no cache do detalhe e da lista, sem esperar nova consulta. A
  lista mostra **"Na fila"** no mesmo instante.
- **Consulta enquanto houver trabalho.** Não há evento novo no backend. As telas consultam de novo só
  enquanto houver item com status `pendente` ou `processando`, e param sozinhas quando tudo termina:
  - detalhe do item (dossiê): a cada 2,5 s;
  - lista de itens: a cada 4 s;
  - caminho pelos agentes: a cada 2 s (já existia).

  O SSE da auditoria (ADR 0009) continua valendo, mas agrupa atualizações a cada 5 s e pode perder o
  último evento. A consulta periódica garante o estado final.
- **Faixa em vez de pop-up.** Enquanto o item está em andamento, uma faixa no topo do detalhe mostra:
  - "Reanálise na fila…" ou "Reanalisando o item…";
  - que o conteúdo abaixo é da análise anterior;
  - o botão **Acompanhar**, que abre a aba "Caminho pelos agentes".

  O conteúdo da aba Decisão fica esmaecido, mas continua legível e navegável.
- **Ações bloqueadas.** Durante a reanálise ficam bloqueados:
  - Aprovar, Corrigir, Rejeitar, Desfazer e Reanalisar (que passa a mostrar "Reanalisando…");
  - as respostas às perguntas e os botões "Usar este" e "Usar";
  - os atalhos A, E, R e U.

  O bloqueio vale para qualquer origem da reanálise: botão Reanalisar, "Corrigir e reanalisar",
  resposta a pergunta ou reanálise em lote.
- **Fim da reanálise.** Quando o status sai de "em andamento", a tela:
  - recarrega o item, o caminho, a lista, a auditoria e as pendências;
  - reabilita as ações;
  - avisa "Reanálise concluída" (ou avisa se terminou com erro).

  O aviso guarda o id do item, porque na fila de revisão o mesmo componente passa de um item para outro.
- **Caminho na fila.** Antes de um agente pegar o item, o caminho mostra "Na fila: aguardando um agente
  livre para começar", em vez de dizer que o item já está com o Arrumador.

## Alternativas consideradas

- **Pop-up bloqueante:** descartado a pedido do usuário. Esconderia o caminho ao vivo e impediria
  navegar por outros itens.
- **Evento SSE por item com a etapa atual:** mais imediato, mas exigiria canal novo e reconexão por item.
  A consulta periódica, limitada aos itens em andamento, custa pouco e reaproveita os endpoints atuais.

## Consequências

- O usuário vê a reanálise acontecer de ponta a ponta: status na lista, faixa no detalhe e agentes no
  caminho.
- Não há mais pedidos duplicados, nem decisões tomadas sobre um resultado que está sendo refeito.
- Durante o processamento de uma auditoria inteira, a lista de itens é consultada a cada 4 s. O volume
  é o mesmo que o SSE já provocava.

## Onde está no código

- `frontend/src/features/auditorias/comum.ts`: `emAndamento` e consulta periódica em
  `useDossieItem` e `useItens`.
- `frontend/src/features/auditorias/DetalheItem.tsx`:
  - `aplicarStatus` (status otimista), `useFimAnalise`;
  - faixa de reanálise e bloqueio das ações (`bloqueado`).
- `frontend/src/features/auditorias/FluxoAgentes.tsx`: `CaminhoItem`, com o texto "Na fila".
