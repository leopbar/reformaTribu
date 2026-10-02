# ADR 0029 — Menos revisão humana: só vai para uma pessoa o que muda o imposto

**Status:** aceito · 2026-10-01

## Contexto

Na auditoria "erp_supermercado_input_50_itens", 24 dos 50 itens (48%) passaram por uma pessoa: 17 ainda
pendentes e 7 já aprovados. Em todos os 7 aprovados, a pessoa confirmou exatamente a sugestão do sistema.
Numa tabela de 50 mil itens, esse ritmo daria cerca de 24 mil revisões. A análise item a item mostrou que
quase nenhuma dessas revisões era uma dúvida real sobre o imposto:

| Causa | Itens | O que acontecia |
|---|---|---|
| Falha da plataforma de IA | 3 | Os créditos da OpenAI acabaram no meio da reanálise; o plano B (Navegador) trocou um NCM do ERP que estava certo (biscoito doce) |
| Imposto Seletivo | 4 | Toda bebida sujeita ao IS ia ao contador, mas quem só revende não recolhe o IS (incide uma vez, na fabricação ou importação) |
| Dúvida "imaginária" com o NCM do ERP certo | 5 | O primeiro parecer errou feio (açúcar → "em bruto", café → "cascas", leite → "creme"); o segundo voltou ao NCM do ERP, mas a discordância virou dúvida. Café: "corrigido de 0901.21.00 para 0901.21.00" |
| NCM discutível, imposto igual | 7 | Todas as opções de NCM davam o mesmo cClassTrib; a dúvida era de cadastro, não de imposto |
| Conflito que os fatos já resolvem | 2 | Óleo de soja (ração × consumo humano, com o dossiê dizendo "consumo humano = sim"); banana (conflito sobre banana seca, item fresco) |
| Dúvida real | 3 | Água sanitária (a lei cita outro NCM e o imposto muda), salada pronta, frango assado classificado como serviço |

A pesquisa (benchmarks de classificação aduaneira com LLM, como ATLAS e HSGraphAgent; SLIM-RAFT para NCM)
mostrou o mesmo padrão: gerar o código do zero é onde a IA mais erra (cerca de 40% de acerto em 10
dígitos); conferir um código existente, votar entre fontes independentes e escalar só a incerteza real
funciona melhor. Por decisão do usuário: nada de bases públicas sem licença clara nem de serviços de
terceiros (GTIN); só os dados da própria organização.

## Decisão

1. **Falha da plataforma não é dúvida** (`gateway.IAIndisponivel`, `processing.pausar_por_ia`). Sem
   resposta da plataforma (sem créditos, fora do ar, limite de uso, chave recusada), nenhum caminho de
   reserva roda e nenhum item vai para revisão: a auditoria fica **"Pausada (a IA não respondeu)"**
   (`pausada_ia`) e a tarefa periódica `auditoria.retomar_pausadas_ia` a retoma sozinha, com espera de
   10, 20, 40, 80 e no máximo 120 minutos. "Retomar" faz isso na hora, com os modelos escolhidos agora.
2. **Imposto Seletivo pelo papel da empresa.** Pergunta nova no dossiê: "a empresa fabrica ou importa
   produtos sujeitos ao IS?" (`fabrica_ou_importa_seletivo`, fora da chave da tese). Resposta "não": o
   item sai classificado com IS **na origem** (`is_situacao = "na_origem"`, cobrado na fabricação ou
   importação, não recolhido na revenda, LC 214/2025, arts. 409 e 412). Resposta "sim": como antes
   (contador, se a organização exigir). Sem resposta: uma pergunta para a empresa toda, e não uma
   revisão por item. Na memória de decisões, "na origem" conta como "sujeito" (é o mesmo produto).
3. **"O imposto muda?" decide a revisão** (`avaliacao._duvida_de_codigo`). Para cada item com dúvida de
   código, o tratamento (cClassTrib + IS) é calculado, sem IA, para todos os códigos em disputa: o do
   ERP, o de cada parecer e as alternativas (`identidade.codigos_em_disputa`). Dois códigos com a mesma
   **assinatura jurídica** (mesmas linhas da correlação oficial, mesmos itens dos anexos, mesmos
   benefícios pela natureza) têm o mesmo tratamento (`aplicacao.assinatura_juridica`).
   - Todos iguais → o IBS/CBS sai. Se o NCM do cadastro muda (ou não existia), ele vai para a lista
     **"Ajustes de cadastro"** (`ajuste_cadastro`, `ajuste_cadastro_status`): uma pessoa aceita a
     sugestão ou mantém o NCM do ERP, em lote. Até lá, a exportação mantém o NCM do ERP. A decisão vira
     memória da empresa.
   - Algum código leva (ou pode levar, quando o imposto dele só se sabe investigando) a outro imposto →
     a pergunta **"o que é este item?"** vai ao operador (`codigo_do_item`), com o código escolhido, o do
     ERP e os que mudam o imposto (os de mesmo imposto ficam fora), o efeito de cada um (ou os anexos da
     lei que o citam) e "Nenhuma destas". Basta certeza de 0,4: perguntar exige menos que liberar,
     porque "Nenhuma destas" leva ao contador. A resposta vira memória aprovada e o item é reanalisado
     com o código escolhido. Itens da mesma categoria com as mesmas opções recebem uma pergunta só.
   - Certeza baixa para liberar sozinho (abaixo de 0,5 com o NCM do ERP entre as opções; abaixo de 0,7
     sem ele), descrição vaga sem âncora, capítulo em dúvida sem código (ver a revisão de 02/10), certeza
     abaixo de 0,4 ou a lei citando o produto com outro código → continua com o contador.
   - Regimes decididos pela operação (bares e restaurantes, ADR 0026): o NCM vai para o cadastro, sem
     travar o enquadramento.
   - Guarda: código de serviço de alimentação (NBS 1.0301) numa empresa que informou não servir
     refeições vai ao contador com a explicação (é mercadoria e precisa de NCM).
4. **O NCM do ERP é um voto** (`identidade.consolidar`). Se o parecer que decide fica com o NCM do ERP,
   o código está **confirmado** (dois votos contra um), mesmo que o primeiro parecer discordasse ou que a
   marcação de coerência o contradiga (fim do "corrigido de A para A"); o código do primeiro parecer que
   perdeu de dois a um sai da disputa. Com o parecer a 0,85 ou mais, as dúvidas registradas viram
   "pontos observados". Instruções v3 do Identificador e do Segundo parecer: o código atual é o ponto de
   partida (conferir, não reclassificar do zero); leitura pelo produto comum ("café torrado" tem
   cafeína); cada dúvida aponta as palavras da descrição que a criam (`duvidas[].trecho`); dúvida sem
   palavra na descrição vira observação; opções em linguagem de loja para a pergunta ao operador
   (`opcoes_para_o_operador`).
5. **Itens parecidos aprovados por pessoas** (`nodes.parecidos_aprovados`), só da própria organização: a
   memória aprovada ganhou vetor da descrição (`approved_memory.embedding`, calculado aos poucos). Os
   códigos dos vizinhos entram na prova com a nota "aprovado por pessoa para …". Se uma pessoa aprovou o
   mesmo NCM do ERP para um item quase igual (semelhança ≥ 0,95) e nenhum item parecido (≥ 0,93) foi
   decidido com outro código, o NCM é confirmado sem IA. Os limites vêm de medições com o modelo local:
   mesmo NCM fica em 0,95–0,98; vizinhos de NCM diferente (leite UHT × em pó, mussarela × prato) em
   0,91–0,93.
6. **Conflito diz qual fato o decide** (instrução v4 do Jurista; `conflitos[].fato_que_decide` e
   `valor_para_o_outro_enquadramento`). Fato conhecido e diferente do que levaria ao outro cClassTrib →
   resolvido; desconhecido → pergunta; igual → especialista; sem fato (contradição das próprias fontes)
   → especialista. Além disso, sem IA: cClassTrib de outros cenários (diferimento, exportação,
   administração pública, produtor rural, Zona Franca, cooperativa) não disputam a venda ao consumidor;
   a restrição em palavras da lei ("sem adição de açúcar") que a hipótese escolhida transformou em
   condição confirmada pelos fatos não trava o item; referência a mais na regra geral não trava a fonte.
7. **Revisão por grupo e decisão que vale na hora para os iguais.** A fila de revisão abre **por
   grupo** (`GET /api/auditorias/{id}/revisao/grupos`): cada cartão junta itens com o mesmo código, o
   mesmo resultado sugerido, os mesmos motivos e a mesma dúvida; "Aprovar os N" aprova o grupo em lote.
   Aprovar um item aprova na hora, na mesma auditoria, os itens pendentes que pedem a mesma decisão
   (dúvida de identificação só junta itens com a mesma descrição); "Desfazer todos" desfaz o lote. A
   contagem da memória de decisões (ADR 0028) não muda: cada auditoria conta uma vez por resultado.
8. **Medição sem IA** (`app/evals/replay.py`). Refaz a identidade e a avaliação de todos os itens já
   analisados com as regras atuais, a partir das respostas da IA gravadas, sem gravar nada e sem custo,
   e compara com o que as pessoas decidiram (gabarito exportado com `--gabarito`, arquivo `*.local.csv`
   fora do Git). A métrica que não pode piorar: **falsos automáticos** (classificado sozinho com
   cClassTrib diferente do decidido por uma pessoa). **"Reaplicar regras (sem IA)"**
   (`POST /api/auditorias/{id}/reaplicar`) aplica o mesmo cálculo de verdade a uma auditoria concluída;
   decisões de pessoas ficam como estão; itens que esbarraram na falha da IA podem voltar para a fila.

## Resultado medido (sem IA, 135 itens de 5 auditorias reais, 27 decididos por pessoas)

| Resultado | Antes | Depois |
|---|---:|---:|
| Classificado sozinho | 75 | 103 |
| Pergunta ao operador | 0 | 14 |
| Revisão do contador | 52 | 5 |
| Revisão do especialista | 8 | 2 |
| Aguardando a IA (falha técnica) | 0 | 11 |

Itens que iriam para uma pessoa: **60 (44%) → 7 (5%)**, com **zero falsos automáticos**. Na auditoria de
50 itens: 24 → 4 (óleo de soja, que depende da tese nova do Jurista; frango assado; sushi; salada). Das
14 perguntas, 9 são a mesma pergunta do IS (uma por empresa) e 4 são efeito da medição (o Leitor de
fatos não roda nela; numa reanálise ele responde pela descrição).

## Consequências

- O contador passa a ver só o que muda o imposto. O NCM continua sendo conferido por uma pessoa, mas na
  lista "Ajustes de cadastro", em lote, sem travar a classificação.
- As instruções novas dos agentes só valem em análises novas: a identificação usa v3 numa reanálise
  (gera custo de IA). As teses guardadas são reaproveitadas pelo conteúdo (ADR 0015): para o Jurista v4
  valer numa família já estudada, use "Refazer pareceres" (também gera custo). Mudança de instrução pede
  `make eval` com um conjunto validado por contador.
- Risco aceito: uma revisão de NCM servia, sem querer, de segunda olhada na tese. Agora a tese vale
  sozinha quando todas as dimensões estão confirmadas, como já valia para os itens sem dúvida de NCM. A
  medição sem IA deve ser rodada a cada mudança de regra; um falso automático bloqueia a mudança.
- A ligação "empresa só revende → IS na origem" depende da resposta da empresa; uma empresa que importa
  bebidas responde "sim" e volta ao comportamento anterior.

## Revisão de 02/10/2026 (depois do primeiro uso real)

Com as regras aplicadas na auditoria de 50 itens, os pendentes de revisão caíram de 17 para 3 (frango
assado, sushi e salada). A revisão encontrou e corrigiu:

- **Pergunta da empresa respondida no item.** O botão do detalhe do item respondia "só este item" mesmo
  para "a empresa fabrica ou importa?": a resposta virou fato de 3 itens, e não da empresa. Agora uma
  pergunta de escopo empresa responde para a empresa (no item e no servidor) e fecha a mesma pergunta nas
  outras auditorias da empresa.
- **Tese de outro dossiê.** "Reaplicar regras" usava a tese mais recente do NCM na organização, que podia
  ser de outra empresa com outro dossiê (o refrigerante do supermercado com a tese do restaurante). Agora
  vale a tese com que o item foi analisado; se ela foi refeita, o item vai para reanálise. Só para
  atualizar um item aprovado por pessoa se aceita a tese atual do mesmo dossiê, e só quando o resultado é
  o que a pessoa aprovou. Conferido: no uso de 01/10 nenhum item recebeu tese de outro dossiê.
- **Imposto Seletivo fora do Anexo XVII.** O Jurista disse "depende de açúcar" para 2202.99.00
  (energético), mas o Anexo XVII só lista 2202.10.00. O IS só alcança os bens do anexo (art. 409, § 1º):
  NCM que o anexo não cita sai "não sujeito", sem pergunta. A exportação passa a mostrar "na origem" para
  empresa que só revende, também em itens aprovados antes da resposta.
- **Tipo do ERP em texto livre.** "Produção interna", "Revenda de bebida…", "Medicamento…" não eram
  entendidos (só "P", "S", "produto"): o item ficava "desconhecido", a busca incluía serviços e a IA
  chegou a dar ao frango assado um código de SERVIÇO (NBS 1.0301.22.00, "fast-food"). Agora esses textos
  dizem que o item é mercadoria e a busca fica na NCM. Numa reanálise, o campo do ERP prevalece sobre o
  "desconhecido" gravado pela análise anterior.
- **Navegador perdido em listas longas.** Reanalisado, o frango assado foi ao capítulo certo (16), mas o
  Navegador recebeu os 51 códigos do capítulo de uma vez, quase todos de peixe, e não reconheceu
  "aves da espécie *Gallus domesticus*… cozidas". Duas correções gerais: a instrução v3 do Navegador manda
  traduzir o nome de loja para o técnico da tabela (espécie pelo nome científico, assado = "cozido"), e a
  descida só pula direto para os códigos finais quando eles são até 25 (antes, 60); acima disso passa pela
  posição. Resultado: capítulo 16 → posição 16.02 → **1602.32.20**.
- **Dúvida entre capítulos.** A salada pronta (sem NCM no ERP) foi ao contador com 2005.99.00 (hortícolas
  preparados, imposto integral) e 60% de certeza. O Navegador tinha cogitado o capítulo 07 (verdura fresca,
  alíquota zero pelo Anexo XV), mas só devolvia alternativas da posição escolhida (purê, broto de bambu):
  "o imposto muda?" nunca via a opção que importava. Pior: numa nova reanálise a certeza deu 70% e o item
  teria saído sozinho com o imposto cheio. Correções gerais (Navegador v4):
  - quando a certeza no capítulo fica abaixo de 0,9, o Navegador desce também por cada capítulo
    alternativo, com a hipótese que o fez cogitá-lo ("se for só verdura fresca cortada"), e devolve o
    código achado como alternativa (`arvore.outros_capitulos`); na hipótese ele não pode desistir: se
    nenhum código nomeia o item, usa o residual ("Outros");
  - cada opção traz um rótulo em linguagem de loja; a pergunta entre capítulos usa os rótulos da escolha
    do capítulo, que mostram o que separa as opções ("hortaliças frescas cortadas, sem preparo" ×
    "salada preparada");
  - capítulo em dúvida em que nenhum código foi achado (`arvore.capitulos_em_aberto`) impede concluir
    que o imposto não muda: o item não sai sozinho;
  - a pergunta "o que é este item?" passa a valer com certeza média e com imposto ainda desconhecido
    (diz quais anexos citam o código), e mostra só as opções que mudam o imposto.

  Resultado: a salada virou a pergunta "salada preparada (2005.99.00) × hortaliças frescas cortadas
  (0709.99.90, Anexo XV)". Na medição sem IA, nenhum falso automático; o "sabonete líquido × em barra" e
  outras dúvidas da mesma natureza deixam o contador e vão ao operador. Custo: cerca de US$ 0,01 a mais
  por item navegado com dúvida de capítulo (de 4 a 6 chamadas do Navegador).
- **Título genérico da posição e limite de saída.** Numa nova reanálise, o frango assado ficou sem NCM:
  o Navegador escolheu o capítulo 16, mas descartou a posição 16.02 ("Outras preparações e conservas de
  carne…") porque "nenhuma menciona aves"; a palavra só aparece um nível abaixo ("De aves da posição
  01.05"). Com o modelo trocado para GPT-5 e esforço alto, ele acertou a posição, mas a resposta do código
  foi cortada: o raciocínio conta no limite de saída, e o Navegador pedia só 4.000 tokens. Correções
  gerais:
  - no nível "posição", cada opção mostra o que inclui (os nomes de até 8 subdivisões); a instrução v5
    do Navegador diz que títulos gerais abrangem o que não nomeiam ("carne" inclui a de aves) e que uma
    opção "Outras…" não se descarta por não citar o item;
  - nos modelos que raciocinam, o limite de saída de qualquer agente sobe com o esforço (médio: 12.000;
    alto: 20.000), já que só se paga o que é usado;
  - o caminho do item mostrava, no Navegador, o modelo da primeira busca e o custo de todas as buscas
    desde a primeira análise (parecia que a troca de modelo não valia); agora mostra só a última busca.

  Resultado: capítulo 16 → 16.02 (citando "de aves da posição 01.05") → **1602.32.20**, classificado
  com o IBS/CBS integral e o NCM na lista "Ajustes de cadastro" (GPT-5, esforço alto, US$ 0,12).
