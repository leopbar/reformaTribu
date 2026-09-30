# ADR 0021 — Revisão humana: resultado × decisão, motivo da revisão e reanálise

**Status:** aceito · 2026-09-30

## Contexto

Pontos de confusão relatados pelo usuário na revisão:

1. Ao aprovar um item em "Revisão do contador", a coluna **Resultado** continuava "Revisão do contador".
2. Depois de responder perguntas, **nada parecia mudar**. Os contadores eram recalculados em segundo
   plano, e a tela recarregava antes.
3. O motivo de cada item estar em revisão ficava escondido no relatório de 10 notas.
4. Reanalisar exigia abrir item por item.
5. Reanalisar uma auditoria antiga usava os modelos da época (inclusive de uma plataforma sem créditos).
6. Uma reanálise sem código deixava na tela a sugestão da análise anterior.

## Decisão

- **Resultado × decisão.** O `status` continua sendo a conclusão do **analista** e fica como histórico
  de que o item precisou de uma pessoa. O `revisao_status` é a decisão da **pessoa**. Na lista:
  - item aprovado por pessoa aparece como **"Aprovado na revisão"**;
  - item rejeitado aparece como **"Rejeitado na revisão"**;
  - passando o mouse, aparece a conclusão original.

  Novo quadro **"Resolvidos"** (classificados mais os decididos por pessoas, com quantos faltam). Os
  quadros por resultado mostram também quantos já foram revisados.
- **Contadores na hora.** Responder perguntas, salvar o dossiê ou validar tese recalcula os contadores da
  auditoria **dentro da requisição**, depois do commit.
- **"Por que veio para você".** No topo do detalhe (e na fila de revisão), um quadro mostra só as notas
  não confirmadas, cada uma com o texto e **o que fazer**. Traz também o resumo das ações: Aprovar (A),
  Corrigir (E), Rejeitar (R).
- **Reanalisar em lote.** Botão na aba Itens. Reanalisa os itens da **lista filtrada**. Uma prévia mostra:
  - quantos itens serão reanalisados;
  - quantos ficam de fora (decididos por pessoas ou já em processamento);
  - o custo estimado.

  Sem filtro, um aviso destaca que todos os itens seriam reanalisados. Decisões de pessoas nunca são
  desfeitas.
- **Modelos da reanálise.** Reanalisar (individual ou em lote) numa auditoria **concluída** passa a usar
  os modelos escolhidos **hoje** em "Modelos de IA". Numa auditoria ainda em processamento, os modelos
  congelados no início continuam valendo.
- **Sem sugestão antiga.** Se a análise atual não tem código, `codigo_sugerido` fica vazio.
- **Reanálise sem mudança dá o mesmo resultado, sem custo.** As chamadas de IA têm chave de idempotência
  pelo conteúdo (mesma prova, mesmo modelo, mesmas instruções → mesma resposta guardada). Para obter um
  resultado diferente, algo precisa mudar: modelo, instruções ou dados do item.

## Consequências

- A lista reflete o estado real de cada item (resolvido ou pendente) sem apagar o histórico da análise.
- A revisão fica mais rápida: o motivo aparece em destaque, e é possível reanalisar grupos.
- A reanálise em lote gera custo proporcional aos itens com prova nova. A prévia mostra o valor antes.

## Onde está no código

- `frontend/src/features/auditorias/Resultado.tsx`: `ResultadoFinal`, quadro Resolvidos e
  `ReanaliseLote`.
- `frontend/src/features/auditorias/DetalheItem.tsx`: `PorQueVeio`, `O_QUE_CONFERIR`.
- `backend/app/api/review.py`: `reprocessar` e `reprocessar_lote` (com prévia via `confirmar=false`).
- `backend/app/api/analise.py`: `_atualizar_contadores`, síncrono.
- `backend/app/analise/aplicacao.py`: `codigo_sugerido` sem resto de análise anterior.
