# ADR 0015 — Tese reaproveitada pelo conteúdo do material jurídico

**Status:** aceito · 2026-09-29

## Contexto

A tese de uma família (ADR 0013) é o parecer do Jurista para um NCM/NBS num cenário e numa data. É a
etapa mais cara, cerca de 70% do custo de uma planilha nova. Ela devia ser feita uma vez por família e
reaproveitada em todas as auditorias seguintes.

A primeira chave da tese incluía o **id do snapshot da base de referência** e a **versão do prompt**. Na
prática, isso quebrou o reaproveitamento:

- Cada nova coleta das tabelas oficiais (NCM, LC 214, cClassTrib) cria versões novas, e com elas um
  snapshot novo. Isso acontece mesmo quando o texto relevante para o código não mudou (o arquivo
  baixado muda por data de coleta e metadados).
- Qualquer melhoria nas instruções do Jurista mudaria a chave de todas as famílias.

No caso real, uma planilha de 10 itens com 5 famílias já estudadas refez os pareceres de arroz e leite,
porque a base tinha sido coletada de novo 50 minutos antes.

## Decisão

- A chave da tese passa a usar o **conteúdo do material que o Jurista lê**. Ela é formada por:
  - `impressao_evidencias` (hash do pacote de evidências);
  - tipo e código;
  - cenário;
  - data de referência;
  - dossiê da empresa.

  A chave **não** usa o snapshot, a versão do prompt nem o modelo.
- O pacote de evidências é montado **antes** da busca da tese. É uma operação determinística e sem custo
  de IA: correlações oficiais, itens de anexo, trechos por significado, lista fechada de cClassTrib,
  precedentes e alertas.
- Nos alertas de divergência, a impressão só considera os campos que o Jurista lê (`regra`, `descricao`,
  `gravidade`, `cclasstrib`). Campos de uso interno, como `codigos`, não mudam a chave.
- **Compatibilidade:** teses gravadas com a chave antiga continuam sendo encontradas. Quando a busca pela
  chave exata falha, o sistema recalcula a chave nova a partir do pacote e do dossiê que a própria tese
  guardou e compara.
- **Refazer com o modelo atual:** trocar o modelo do Jurista ou as instruções não refaz os pareceres
  guardados. Para refazer, há um botão na aba "Famílias investigadas", por família ou para todas as
  famílias da auditoria. O refazer:
  - marca a tese antiga como `substituida` e acrescenta um sufixo à chave dela (a coluna `chave` foi
    ampliada para 120 caracteres na migração 0004);
  - acrescenta o mesmo sufixo à chave de idempotência da chamada antiga, para a nova chamada não
    reaproveitar a resposta antiga;
  - atualiza o modelo do Jurista congelado na auditoria;
  - reprocessa os itens da auditoria que usavam a tese. Itens aprovados por pessoas são mantidos.

## Alternativas consideradas

- **Manter o snapshot na chave e evitar coletas desnecessárias.** Frágil: não controlamos o formato dos
  arquivos oficiais, e uma coleta legítima de outro código também invalidaria tudo.
- **Chave só por código + cenário + data.** Não refaria a tese quando a lei do código mudasse de fato,
  o que é arriscado.

## Consequências

- Nova coleta da base com o mesmo texto para o código: a tese é **reaproveitada**, sem custo.
- Mudança real na lei ou na tabela **daquele código**: a tese é **refeita** automaticamente.
- Melhorias de instruções só valem para famílias novas ou refeitas. É uma decisão consciente para
  controlar custo.

## Onde está no código

- `backend/app/analise/investigacao.py`: `impressao_evidencias`, `chave_familia`.
- `backend/app/pipeline/analista.py`: `investigar`, com a busca por chave e o fallback pelo pacote
  guardado.
- `backend/app/api/analise.py`: `_refazer`, `/teses/{id}/refazer` e `/auditorias/{id}/teses/refazer`.
- `frontend/src/features/auditorias/FamiliasPainel.tsx`: botões e diálogo de confirmação.

## Verificação

- Teste `test_impressao_da_tese_ignora_metadados_dos_alertas`.
- Conferido com dados reais: as teses de arroz e leite de 28/09 e 29/09 produzem a mesma chave nova.
