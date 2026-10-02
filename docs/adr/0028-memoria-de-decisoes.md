# ADR 0028 — Memória de decisões: o sistema aprende com as classificações aprovadas

**Status:** aceito · 2026-09-30

## Contexto

A tela "Regras legais" listava cerca de 840 regras pendentes, geradas da LC 214/2025 e das tabelas
oficiais, para o superadministrador aprovar uma a uma. O usuário achou a tela complexa demais. No Anexo I,
item 20 (peixes), por exemplo, ele não conseguiu entender o que fazer. Desde a ADR 0013 a aprovação dessas
regras é opcional: o analista raciocina a partir da lei. Mesmo assim:

- **Uma regra cobre muitos produtos.** O item 20 cobre 119 códigos, com exceções. Aprovar uma regra porque
  um item dela foi aprovado generalizaria uma conferência para 119 códigos.
- **A IA confirmaria a si mesma.** A IA sugere, a pessoa aprova, a regra é aprovada e a regra aumenta a
  confiança da IA. Um erro aprovado por descuido ficaria cada vez mais "confiável".
- **Faltava aproveitar o trabalho já feito.** A memória existente (`approved_memory`) só reaproveita o
  **mesmo produto** na **mesma empresa**, e só para o NCM. Uma classificação aprovada num supermercado não
  ajudava o arroz do supermercado seguinte.

## Decisão

- **Memória de decisões** (`decision_memory`, migração 0006, `app/analise/decisoes.py`). Cada aprovação
  feita por **uma pessoa** grava:
  - o NCM/NBS, o cenário e o ramo (`segmento`) da empresa;
  - o cClassTrib, o CST e o Imposto Seletivo escolhidos;
  - os fatos que decidiram (por exemplo, "sal iodado = sim");
  - os dispositivos citados.

  A migração preencheu a tabela com os itens que já tinham sido aprovados por pessoas.
- **O que conta:**
  - **Só decisões de pessoas.** A aprovação automática nunca grava.
  - **Cada auditoria conta no máximo uma vez por resultado.** Aprovar 50 itens iguais em lote não confirma
    sozinho.
  - **Uma correção pesa 2.** É o enquadramento definido pela pessoa (`hipotese = "manual"`).
  - **A decisão só vale para itens decididos pelos mesmos fatos.**
  - **Desfazer** a aprovação (individual ou em lote) desativa a decisão.
  - **Regimes da operação não gravam** (hipóteses `OP-`, ADR 0026), porque não dependem do código do
    produto.
- **Alcance:** a decisão vale dentro da **organização**, entre empresas do **mesmo ramo** (mercado com
  mercado, farmácia com farmácia). Uma empresa sem ramo só aproveita as próprias decisões. Decisões
  **nunca** passam de uma organização para outra (RLS).
- **Efeito na avaliação** (`avaliacao._pesar_decisoes`), só quando o analista chegou a um enquadramento
  pelo produto:

  | Decisões | Mesmo resultado da análise | Outro resultado |
  |---|---|---|
  | 1 | nota "decidido igual por pessoas 1 vez" na dimensão Fonte | conflito (atenção): revisão do contador |
  | 2 | também dispensa os avisos jurídicos leves (Fonte e Conflito em atenção) | conflito (atenção) |
  | 3+ (confirmado) | também resolve o conflito normativo daquele código, inclusive a divergência lei × tabela | conflito grave: especialista |

  Quando as decisões das pessoas divergem entre si, nada é reforçado e o item vai para revisão. A memória
  não responde perguntas sobre fatos do item nem dúvidas de identificação (qual é o NCM): essas continuam
  com uma pessoa.
- **A IA não vê a memória.** Ela entra só depois da análise, na comparação. Assim:
  - a comparação continua independente: se a IA visse a resposta antes, tenderia a copiá-la;
  - o pacote de evidências não muda, e as teses já pagas continuam sendo reaproveitadas (ADR 0015).
- **Nenhuma regra é aprovada automaticamente.** A tela "Regras legais" virou um **resumo**
  (`GET /api/regras/resumo`, `app/rules/uso.py`), calculado a cada consulta, por organização:
  - **Precisa de um olhar:** só as divergências que tocam códigos presentes nos itens da organização, em
    texto simples, com quantas decisões faltam por código. As outras aparecem apenas como contagem.
  - **Confirmadas pelo uso** e **em confirmação.** Uma decisão conta para a regra que ela citou ("Anexo I,
    item 2"). Sem citação de anexo, conta só quando uma única regra dá aquele cClassTrib ao código.
  - **Divergências resolvidas pelo uso.**

  O superadministrador escolhe a organização na própria tela. O resumo traz só agregados (códigos,
  cClassTrib e contagens), sem produtos nem empresas. A lista antiga, com aprovação, edição e YAML,
  continua em "Detalhes técnicos" (`/referencia/regras/detalhes`), sem ser necessária.

## Consequências

- O trabalho de revisão das auditorias passa a reduzir as revisões seguintes. Um NCM aprovado três vezes
  no mesmo ramo, com o mesmo resultado, sai aprovado sozinho quando a análise concorda.
- Uma divergência lei × tabela (por exemplo, o item 20) deixa de travar para sempre os itens de um código:
  três decisões iguais a resolvem para aquele código e ramo.
- Uma decisão errada repetida três vezes também se consolida. A proteção é:
  - a análise da IA continua independente;
  - qualquer discordância da IA manda o item para revisão (com 3 decisões contra, para o especialista);
  - desfazer a aprovação tira a decisão da memória.
- As regras aprovadas manualmente (precedentes) continuam valendo como antes.
