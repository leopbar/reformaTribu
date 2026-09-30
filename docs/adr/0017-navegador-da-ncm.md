# ADR 0017 — Navegador da NCM: busca guiada pela árvore oficial

**Status:** aceito · 2026-09-29 (revisto em 2026-09-30)

## Contexto

O Identificador só pode escolher o NCM entre as alternativas que o Pesquisador separa: é uma "prova de
múltipla escolha", o que impede códigos inventados. A busca que monta essa prova (palavras e significado,
com embeddings locais) é fraca. Para itens **sem NCM no ERP**, ela não tem nem o código do ERP nem os
"irmãos" para acrescentar. Resultado: bolo, frango assado, sushi, salada e limpa para-brisa terminavam
**sem NCM, sem CST e sem cClassTrib**, e o contador tinha de pesquisar do zero. Em alguns casos o próprio
Segundo parecer escrevia a pista ("bolo é da posição 1905"), e ela era descartada.

## Decisão

Um novo agente de IA, o **Navegador da NCM** (nó `navegar_arvore`, prompt `navegar_arvore`), entra quando
o item fica sem código:

- o ERP não trouxe código válido e a busca não achou alternativas;
- a IA disse que nenhuma alternativa serve;
- a resposta do Identificador foi descartada;
- **ou a chamada do Identificador falhou** (ex.: resposta cortada). Nesse caso a busca guiada serve de
  reserva, em vez de o item parar.

Ele **desce pela tabela oficial** usando `codigo_pai`:

1. capítulo (raízes);
2. posição, e subposições quantas a tabela tiver;
3. código final.

Com até 60 códigos finais sob o nível atual, pergunta direto entre eles. A descida permite até 7 níveis a
partir do capítulo (antes eram 4, e a areia higiênica parou em 3824.9 sem chegar ao código).

Regras de funcionamento:

- **Segundo capítulo:** se no capítulo escolhido nenhum código servir, tenta o capítulo alternativo que
  o próprio Navegador indicou (ex.: sushi: 21 → 16).
- Cada passo só oferece códigos oficiais. A resposta é validada contra a lista, e a IA **não pode
  inventar código**.
- **Instruções v2 (2026-09-30):**
  - na dúvida, escolher a opção **mais provável com certeza baixa** e listar até 2 alternativas;
  - falta de detalhe (matéria-prima, composição) é motivo para certeza baixa, não para desistir;
  - palavras de embalagem ("BANDEJA", "POTE", "KIT", "FATIA") indicam como o produto é vendido;
  - "nenhuma" só quando o item claramente não pertence àquela parte da tabela.

  A v1 desistia na dúvida, e o resultado variava entre execuções (o sushi teve código numa rodada e não
  teve na seguinte).
- **O código encontrado é uma sugestão.** A identidade fica `via_arvore` e o item segue para o Jurista,
  recebendo CST e cClassTrib. O item vai **sempre** para o contador confirmar o NCM. No detalhe aparecem
  o caminho percorrido e as alternativas com o botão **"Usar este"**. Os códigos da posição encontrada
  viram candidatos na revisão.
- **NCM do ERP como referência (2026-09-30):** se nem a prova nem o Navegador acham código melhor e o ERP
  trouxe um código que existe, está completo e vale na data, esse código fica como referência. A
  situação é `nao_confirmado` (`erp_mantido`). O Jurista estuda a lei com ele e o item vai ao contador
  com o aviso *"provavelmente não descreve o item"*. O item nunca fica vazio quando o ERP tinha código.
- O Navegador tem **modelo próprio** em "Modelos de IA". O padrão é o Claude Haiku, e as recomendações
  incluem GPT-5 mini e DeepSeek Flash. Auditorias antigas, sem modelo congelado para ele, usam o modelo
  escolhido hoje.

## Consequências

- Itens sem NCM passam a chegar ao contador com NCM, CST e cClassTrib sugeridos e alternativas prontas.
- Custo: 2 a 5 chamadas curtas por item sem código.
- A falha do Navegador (ex.: plataforma sem créditos) fica gravada no item e aparece no caminho dos
  agentes.

## Onde está no código

- `backend/app/pipeline/arvore.py`: `navegar_arvore`, `descer`, `precisa_navegar`.
- `backend/app/pipeline/graph.py`: arestas `_apos_candidatos`, `_apos_julgamento`, `_apos_escalonamento`
  e `_apos_arvore`.
- `backend/app/pipeline/analista.py`: `codigo_escolhido`, `codigo_erp_valido`.
- `backend/app/analise/identidade.py`: identidade `via_arvore` e `nao_confirmado`.
- `backend/app/analise/avaliacao.py`: dimensões de identificação e código para esses casos.
- `backend/prompts/navegar_arvore/v1.md` e `v2.md`.
- `frontend/src/features/auditorias/DetalheItem.tsx`: aviso, alternativas e "Usar este".

## Verificação

- Testes de pipeline:
  - `test_item_sem_ncm_recebe_sugestao_pela_arvore_oficial`;
  - `test_navegador_tenta_o_capitulo_alternativo`;
  - o teste completo do analista (produto sem código melhor → NCM do ERP mantido como referência).
- Dados reais:
  - limpa para-brisa → 3402.50.00 (95%);
  - bolo → 1905.90.90;
  - frango assado → 1602.32.20;
  - salada → 2005.99.00;
  - sushi → 1604.20.90 (pelo segundo capítulo).
