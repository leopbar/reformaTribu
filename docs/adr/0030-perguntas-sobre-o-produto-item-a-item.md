# ADR 0030 — Perguntas sobre o produto respondidas item a item; respostas corrigíveis; medicamento em todas as posições

**Status:** aceito · 2026-10-02

## Contexto

Ao revisar a auditoria "erp_farmacia_input_35_itens", oito remédios comuns (paracetamol, dipirona,
ibuprofeno, loratadina, omeprazol, metformina, fluoxetina, salbutamol) estavam classificados como
**dispositivo médico do Anexo IV** (cClassTrib 200030) em vez de medicamento (200032). A pergunta "o item é
um dispositivo do Anexo IV (substituto de enxerto ósseo; concentrado para diálise)?" foi feita para a
categoria "Medicamentos" inteira, e o botão principal da tela era "Sim para os 12": um clique gravou a mesma
resposta em todos, com a lista de itens escondida.

A investigação em todas as auditorias da organização achou o mesmo padrão em outras perguntas sobre o
produto respondidas uma vez para a categoria:

| Auditoria | Pergunta respondida para todos | Itens em que a resposta não serve |
|---|---|---|
| Farmácia | "é dispositivo do Anexo IV?" = sim | 10 remédios |
| Supermercado (50 itens) | "a bebida tem adição de açúcar?" = sim | águas, cerveja, vinho, refrigerante zero, suco de laranja integral |
| Supermercado (50 itens) | "o suco contém conservantes da posição 20.09?" = sim | águas, cerveja, vinho, refrigerantes, energético |
| Restaurante | "o suco tem adição de açúcar?" = não | refrigerante de cola, limonada suíça |
| Restaurante | "a bebida é preparada no estabelecimento?" = não | limonada suíça, suco natural, café espresso |

Na maioria, a resposta errada não mudou o imposto (o fato não era usado pela tese do item, ou outro fato
mais específico prevaleceu). Mas dois problemas de sistema ficaram claros:

1. **Uma pergunta sobre o produto não pode valer para a categoria num clique.** Cada produto tem a sua
   resposta (açúcar, conservante, estar numa lista da lei); a categoria do ERP só junta itens parecidos.
2. **Não havia como corrigir uma resposta.** A tela mostrava as perguntas respondidas só para leitura, e a
   lista de itens da pergunta se esvazia quando eles não precisam mais dela. Quem respondeu errado não tinha
   como consertar.

A revisão item a item da farmácia achou mais dois erros de sistema:

3. **Medicamento fora de 30.03/30.04.** O anticoncepcional (NCM 3006.60.00) saiu com tributação integral: a
   ligação da lei "medicamento registrado na Anvisa" (ADR 0027) só alcançava as posições 30.03 e 30.04, e o
   Jurista nem recebeu as hipóteses 200032 e 200009. A própria lista de medicamentos da lei (Anexo XIV) usa
   também 30.02 (imunológicos e soros) e 3006.30 (contrastes); os anticoncepcionais hormonais ficam em
   3006.60.
4. **A mesma pergunta com cinco nomes.** Cada tese inventava a chave do fato da alíquota zero do art. 146
   ("medicamento_lista_art146", "consta_lista_aliquota_zero", "destinacao_art146"…). O operador respondeu a
   mesma coisa cinco vezes, com respostas contraditórias para a categoria ("sim" numa, "não" em outra).

## Decisão

1. **Pergunta sobre o produto com vários itens é respondida item a item** (`pendencias.responder`). Uma
   resposta única (`valor`) só vale para pergunta da empresa (dossiê) ou com um item só; com vários itens, o
   servidor exige `respostas_itens`. A tela (aba Perguntas) mostra a lista sempre aberta, um par de botões
   por item e o atalho "Marcar todos", que preenche a lista à vista antes de enviar. Itens sem resposta
   continuam na pergunta.
2. **Respostas corrigíveis.** Uma pergunta respondida mostra os itens que receberam a resposta (pelo
   histórico de fatos, `CompanyFact.pendencia_id`) e a resposta atual de cada um. "Corrigir respostas" envia
   só os itens que mudaram; o fato anterior fica no histórico e os itens são reavaliados sem IA. Corrigir
   também é item a item.
3. **Medicamento em todas as posições em que a lei o reconhece** (`natureza._MEDICAMENTOS`): 30.02, 30.03,
   30.04, 3006.30 e 3006.60. A condição "registrado na Anvisa" continua sendo verificada (presunção de
   regularidade na farmácia, pergunta quando necessário).
4. **Chave fixa por natureza.** Cada ligação da lei (`natureza.Ligacao.fato`) tem a chave do fato que a
   condição pede ("medicamento_aliquota_zero_art146", "medicamento_registrado_anvisa",
   "soro_ou_vacina_registrado_anvisa", "produto_in_natura"…). Ela vai no pacote do Jurista
   (`correlacoes_oficiais[].fato_da_condicao`), e a instrução v5 do Jurista manda usá-la em toda condição ou
   exceção daquela natureza. Vale para as teses novas; as antigas mantêm as chaves que já têm.
5. **Catálogo de fatos padronizados** (`app/analise/fatos_padrao.py`). Reanalisados, o anticoncepcional e a
   sinvastatina receberam de três a cinco perguntas cada: "registrado na Anvisa?", "o fabricante cumpre a
   CMED?", "é dispositivo médico?", "o dispositivo está regularizado?", "o comprador é órgão público?". A lei
   presume as de registro e CMED para o que se vende no varejo; o ERP já dizia "Medicamento sob prescrição"
   (remédio não é dispositivo); e a venda ao consumidor nunca é compra pública. O catálogo dá a cada condição
   que se repete uma chave, um sentido e uma pergunta fixos, e diz quando o valor vem sem perguntar:
   `presumido` (presunção legal na venda ao consumidor), `pelo_erp` (o tipo do item no ERP decide; "Medicamentos
   e correlatos" não decide) e `pelo_dossie` (a farmácia que não manipula não vende manipulado). Na avaliação,
   esses valores entram como fatos implícitos, com origem ("cadastro" ou "erp") e explicação à mostra; uma
   resposta de pessoa em contrário prevalece. O catálogo vai ao Jurista como instrução, fora do material da
   tese (`investigacao.conteudo` → `fatos_padronizados`), para não refazer as teses existentes; a instrução v5
   manda reusar as chaves e não perguntar o que é presumido. A pergunta de um fato do catálogo tem sempre o
   mesmo texto, em qualquer tese.
6. **Hipótese de outro cenário fora da avaliação.** O cClassTrib cujo nome oficial indica outro cenário
   (compra pela administração pública, exportação, produtor rural…; ADR 0026 e 0029) já não disputava os
   conflitos, mas a hipótese continuava na escolha e pedia fatos que nunca valem na venda ao consumidor.
   Agora ela sai antes da escolha (`avaliacao.avaliar`).
7. **Produto citado na lei com outro NCM, mas com o mesmo imposto.** A regra da ADR 0019 manda ao contador o
   item cujo produto a lei cita pelo nome com outro código ("com o código da lei o imposto pode mudar"). A
   sinvastatina, já com alíquota zero (resposta "sim" ao art. 146), continuava com o contador porque a lei a
   cita em 3004.90.59 (Anexo XIV) e o cadastro tem 3004.90.99. Agora o sistema sabe o tratamento de cada
   anexo (`cclasstrib_codes.nro_anexo`; o Anexo XIV, "medicamentos submetidos à redução a zero", corresponde
   ao 200009, que a tabela não numera: `natureza.ANEXOS_SEM_CORRELACAO`). Se o item já tem esse tratamento,
   o NCM da lei vai para "Ajustes de cadastro"; se não tem (losartana com "não"), segue para o contador.
8. **Pergunta sem texto.** Quando a tese pede um fato sem formular a pergunta, o texto passa a ser a condição
   da lei (fatos de chave fixa) ou "O item atende a esta condição: …?", em vez de "Qual é o valor de …?".

## Consequências

- O operador clica um pouco mais ("Marcar todos" + "Enviar" em vez de um clique), mas sempre vê a que itens
  está respondendo. Numa planilha grande, o Leitor de fatos continua respondendo sozinho o que a descrição
  diz, e "Confirmar as suposições" aceita de uma vez as suposições da IA conferidas.
- As respostas erradas já gravadas não são trocadas pelo sistema: cada uma é uma decisão de pessoa. A lista
  delas está no andamento e no relatório da revisão; corrige-se pela aba Perguntas → "Ver perguntas
  respondidas" → "Corrigir respostas".
- Famílias de medicamento em 30.02 e 3006 e famílias com ligação da lei recebem tese nova na próxima análise
  (o material do Jurista mudou): custo de IA uma vez por família.
- Os oito remédios marcados como dispositivo médico foram corrigidos a pedido do usuário em 02/10/2026
  (fato "não" item a item, reavaliados: 200032).

## Revisão da farmácia (02/10/2026), item a item

Pela redação atual do art. 146 (LC 227/2026), a alíquota zero vale para medicamentos cujo registro sanitário
os destina a doenças raras ou negligenciadas, oncologia, diabetes, HIV/IST, doenças cardiovasculares ou ao
Programa Farmácia Popular; soros e vacinas também (§ 1º, III).

| Item | Hoje | Avaliação | Quem resolve |
|---|---|---|---|
| Paracetamol, dipirona, ibuprofeno, loratadina, omeprazol, fluoxetina, levotiroxina, amoxicilina | 200032 | certo | — |
| Insulinas (NPH e glargina), tamoxifeno, enalapril, dolutegravir | 200009 | certo (dolutegravir: a lei usa o NCM 3004.90.79) | contador confirma o NCM do dolutegravir |
| Vacina influenza | 200053 | certo | — |
| Metformina | 200032 | resposta "não" ao art. 146 está errada: diabetes → 200009 | operador corrige a resposta |
| Losartana | 200032 | "não" errado: cardiovascular (e Anexo XIV) → 200009, NCM 3004.90.69 | operador corrige; contador confirma o NCM |
| Sinvastatina | 200009 | reanalisada: das cinco perguntas novas sobrou uma (art. 146), respondida "sim"; o NCM 3004.90.59 da lei foi para "Ajustes de cadastro" | aceitar o ajuste de cadastro |
| Soro fisiológico | 200030 | "dispositivo = sim" errado → 200032 (ou zero, se o contador entender que é "soro") | operador corrige; contador decide |
| Salbutamol | 200032 | depende da leitura do art. 146, VII (Farmácia Popular) | contador decide |
| Anticoncepcional | 200009 | erro de sistema (3006.60 fora das posições de medicamento), corrigido e reanalisado: ficou uma pergunta (art. 146), respondida "sim" pelo operador (Farmácia Popular, inciso VII) | contador confirma |
| Higiene e perfumaria (15 itens) | — | coerentes com o Anexo VIII e o art. 147 | — |
