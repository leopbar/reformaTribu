# ADR 0020 — Checagem cruzada com os anexos da lei

**Status:** aceito · 2026-09-30

## Contexto

O sistema aprovou sozinho a **água sanitária** com tributação integral, usando o NCM do ERP 2828.90.11
(hipoclorito de sódio). A LC 214, no Anexo VIII, item 5, diz *"Água sanitária classificada no código
**3808.94.19**"*, com redução de 60% (cClassTrib 200035).

O erro teve três causas:

- o Identificador confirmou o código do ERP, porque ele descreve quimicamente o produto;
- o Jurista só procura a lei **pelo código**;
- o código certo, em outro capítulo, **nunca entrou na prova** de alternativas.

Não era possível corrigir sozinho: a IA só escolhe entre as alternativas.

## Decisão

**1. Nome do produto nos anexos.** Para cada item de anexo com códigos citados (839 na LC 214), o nome
do produto é extraído do começo do texto, até expressões como "classificad…", "do código", "códigos",
vírgula ou parênteses. A comparação é feita sem acentos e em minúsculas.

- Nomes com **2 ou mais palavras** ("água sanitária", "papel higiênico") casam em qualquer posição da
  descrição.
- Nomes com **1 palavra** ("arroz", "ovos") só casam como **primeira palavra** da descrição **e** no
  **mesmo capítulo** da NCM do código da lei. Isso evita "OVOS DE PÁSCOA" (cap. 18) × "ovos" (cap. 04),
  "FARINHA LÁCTEA" × "farinha", "MANTEIGA DE AMENDOIM" × "manteiga", "CEREAIS MATINAIS" × "cereais" e
  "VEÍCULOS DE BRINQUEDO" × "veículos".
- Se a lei **também** nomeia o produto no próprio código do item, não há alerta.

**2. Aviso ao contador.** Quando a lei nomeia o produto com outro código, a nota "NCM/NBS" vira atenção,
com o motivo `PRODUTO_CITADO_NA_LEI`: *"A lei cita 'água sanitária' no código 3808.94.19 (Anexo VIII,
item 5); o item está em 2828.90.11. Confira o NCM…"*. O item não é aprovado sozinho.

**3. Código da lei na prova.** O Pesquisador acrescenta às alternativas os códigos que a lei indica, com a
nota `citado_na_lei` ("LC 214/2025, Anexo VIII, item 5 ('água sanitária')").

- Para itens **sem** código no ERP, entram só nomes de 2 ou mais palavras.
- Serviços ficam de fora.
- O atalho "confirmado sem IA" é desligado nesses casos.
- As instruções v2 do Identificador e do Segundo parecer dizem que isso é **indicação oficial de
  classificação, não critério tributário**: escolher só se a descrição oficial do código descrever o
  item.

**4. Troca motivada pela lei sempre é confirmada.** Se a IA escolher o código citado na lei, a identidade
recebe `corrigido_pela_lei` e a nota vira atenção (*"NCM corrigido de … para …, o código que a lei
atribui ao produto… Confirme a correção"*), mesmo com os dois pareceres de acordo.

## Consequências

- A água sanitária foi corrigida para 3808.94.19, com redução de 60%, pelo próprio sistema.
- Verificado em **610 descrições reais**: a prova muda só em 7 produtos (água sanitária, 3 itens de
  losartana e 3 de sinvastatina). Os demais continuam com a mesma prova e, portanto, as mesmas respostas
  reaproveitadas, sem custo novo.
- Limite conhecido: só pega produtos que a lei nomeia **com as mesmas palavras** da descrição. Sinônimos
  e abreviações ("AG SANIT") não casam.

## Onde está no código

- `backend/app/analise/anexos.py`: `nome_do_produto`, `_cita`, `produtos_citados_com_outro_codigo`,
  `codigos_da_lei_para_a_prova`.
- `backend/app/pipeline/nodes.py`: `recuperar_candidatos` e `_confirmacao_sem_ia`.
- `backend/app/analise/aplicacao.py`: `_produtos_na_lei`.
- `backend/app/analise/avaliacao.py` e `backend/app/analise/identidade.py`: `corrigido_pela_lei`.
- `backend/app/pipeline/reasons.py`: `PRODUTO_CITADO_NA_LEI`.

## Verificação

- `test_nome_do_produto_no_anexo`.
- `test_produto_citado_na_lei_com_outro_codigo_vai_ao_contador`.
- `test_codigo_citado_na_lei_entra_na_prova_e_a_troca_vai_ao_contador`.
