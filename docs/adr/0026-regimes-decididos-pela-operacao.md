# ADR 0026 — Regimes decididos pela operação, e respostas que valem só para os itens listados

**Status:** aceito · 2026-09-30

## Contexto

Teste real num restaurante ("Atacadão do João", segmento restaurante, `fornece_refeicoes = sim`):

1. **Café espresso sem NCM ficou sem enquadramento.** Nem a prova de múltipla escolha nem o Navegador
   acharam o NCM (o certo, 2101.12.00, não estava entre os candidatos, e a busca guiada só tentava dois
   capítulos). Sem NCM não havia tese de família, e o item parava antes de qualquer análise jurídica.
   Só que o cClassTrib dele **não depende do NCM**: bebida não alcoólica preparada no estabelecimento
   por restaurante segue o regime específico (LC 214, art. 273, § 1º; 200047, redução de 40%).
2. **Cada família reinventava o regime do restaurante.** O 200047 era oferecido ao Jurista em toda tese
   de empresa com `fornece_refeicoes = sim`, e cada tese o tratava de um jeito:
   - água mineral e kombucha (compradas prontas) saíram **classificadas automaticamente** com 200047,
     contra o art. 273, § 2º, II. É o erro mais grave do sistema: um falso "classificado";
   - cerveja, pudim e marmita ficaram sem enquadramento;
   - o suco natural preparado na casa foi para o Anexo VII (60%), e não para o regime do restaurante.
3. **Uma resposta em grupo vazava para itens que a pessoa nunca viu.** A pergunta "a bebida foi
   preparada no local?" foi feita para a categoria "Bebidas" e respondida "não" (pensando na água). A
   resposta virou fato da categoria e passou a valer para o café espresso e o suco natural, que
   chegaram depois. O mesmo já tinha acontecido com o suco integral no supermercado ("tem
   conservantes?").
4. A mensagem "a identificação por IA não pôde ser concluída" parecia falha técnica. O motivo real era
   "nenhum código da tabela descreve o item": o segundo parecer tinha recusado o código do primeiro.

O usuário pediu que a correção valesse para qualquer ramo (farmácia, autopeças, roupas, material de
construção…), e não só para restaurante e supermercado.

## Decisão

### 1. Três eixos do enquadramento, e o que o sistema cobre em cada um

A tabela cClassTrib oficial mostra que o tratamento pode depender de três coisas diferentes:

| Eixo | Exemplos (cClassTrib) | Como o sistema decide |
|---|---|---|
| **Produto** (NCM/NBS num anexo ou na correlação oficial) | cesta básica 200003, Anexo VII 200034, higiene 200035, medicamento registrado 200032, hortícolas 200014 | Tese da família pelo Jurista (ADR 0013), como antes |
| **Operação ou estabelecimento** (quem vende e como o item é fornecido) | bares e restaurantes 200047; medicamento de farmácia de manipulação 200032 | **Novo:** catálogo declarativo `app/analise/operacao.py`, igual para todas as empresas e itens |
| **Comprador ou destino** | administração pública 200010, PcD/taxista 200015, produtor rural 200002, exportação, Zona Franca | **Fora do cadastro do item.** São outros cenários de operação (a venda comum ao consumidor é o único cenário da 1ª versão) |

### 2. Catálogo de regimes da operação

Cada regime declara:
- quando o dossiê o ativa (ex.: `fornece_refeicoes = sim` ou `segmento = restaurante`);
- quando ele é afastado para a empresa toda (ex.: CNAE 5620-1/01, refeição para empresa sob contrato,
  art. 273, § 2º, I);
- as condições e as exceções de item, como fatos (preparado no estabelecimento, servido como
  alimentação, bebida alcoólica, manipulado, é medicamento);
- os artigos que o fundamentam. O texto vem da base oficial do snapshot; sem o artigo vigente na base,
  a dimensão "fonte" falha;
- `independe_do_codigo`: o cClassTrib sai mesmo sem NCM;
- `exclusivo`: se o cClassTrib só existe pela operação (200047) ou também vale pelo produto (200032).
  As hipóteses do Jurista com um cClassTrib exclusivo são ignoradas, e ele deixa de recebê-lo como
  opção. O 200032 continua disponível para a tese do medicamento industrializado.

As hipóteses do catálogo têm o mesmo formato das do Jurista e são avaliadas **antes** delas:
- condições confirmadas: vale o regime, mesmo que o produto tenha benefício (o prato com arroz segue o
  regime do restaurante, não a cesta básica);
- exceção confirmada: valem as hipóteses do produto (cerveja → regra geral e Imposto Seletivo);
- falta um fato: nasce uma pergunta com o efeito de cada resposta.

Sem NCM, o item é revisto pelo contador (a nota fiscal exige o NCM), mas já sai com o cClassTrib. A nota
"NCM/NBS" diz: "ainda não definido; o cClassTrib não depende dele". O Imposto Seletivo fica "não
avaliado" até o NCM existir.

### 3. Fatos implícitos, com origem à mostra (não gravados)

- **Pelo código:** capítulo 22.03–22.08 → bebida alcoólica; 22.01, 22.02 e 22.09 → não alcoólica; fora
  do capítulo 22 (ou NBS) → não é bebida. O 22.06 (fermentados com e sem álcool, ex.: kombucha) não
  decide. As posições 30.03 e 30.04 indicam medicamento; o capítulo 33 e a posição 21.06 indicam que
  não é.
- **Pela lei, a partir do perfil:** num bar ou restaurante, o que ele prepara é fornecimento de
  alimentação (art. 273, caput). Numa padaria ou num supermercado com lanchonete, isso **não** é
  presumido: pão feito na casa pode ser mercadoria (por quilo) ou lanche servido, e a pessoa decide.

Um fato informado por pessoa ou explícito na descrição sempre prevalece.

### 4. O Leitor de fatos também lê a operação

O Leitor passa a receber os fatos dos regimes ativos e o tipo de estabelecimento (prompt
`extrair_fatos` v2). Ele roda também para itens sem NCM (o grafo agora vai do Navegador sem código para
o Leitor, e o Jurista sempre segue para o Leitor, que não chama a IA se não houver o que perguntar).
"CAFÉ ESPRESSO" num restaurante é afirmação explícita de preparo no local; "LATA", "LONG NECK" e "ÁGUA
MINERAL" afirmam produto comprado pronto. Quando a descrição não diz, a resposta fica como suposição,
não como fato.

### 5. Resposta em grupo vale só para os itens listados

- A resposta a uma pergunta de categoria ou de NCM grava **um fato por item listado** (o fato de grupo
  deixa de ser criado). Um item que chega depois na mesma pergunta a **reabre**, em vez de herdar a
  resposta em silêncio.
- Migração `0005`: os fatos de grupo ativos viram fatos de item para os itens da mesma auditoria e do
  mesmo grupo. Itens de outras auditorias deixam de herdar e, se precisarem, recebem a pergunta de
  novo.
- Tela de perguntas: o texto explica o alcance da resposta, e o botão **"Confirmar as suposições"**
  aceita de uma vez a suposição da IA de cada item. É a "presunção" pedida pelo usuário, mas conferida
  por uma pessoa, porque foi justamente a presunção sem conferência que classificou a água mineral
  com 200047.

### 6. Pequenas correções

- A mensagem de identificação usa o parecer que decidiu ("nenhum código da tabela oficial descreve o
  item…") e diz quando nem a busca guiada achou código.
- O Navegador tenta até 3 capítulos (antes, 2). Isso só ajuda quando o modelo lista o capítulo certo
  entre as alternativas; a busca inicial de candidatos continua sendo o ponto fraco para bebidas
  prontas (ver pendências).

- **Travas que não congelam a fila.** As travas de "um estudo por família" e de "uma chamada por conteúdo"
  tinham validade de 15 e 10 minutos. Um worker reiniciado no meio de uma chamada (em desenvolvimento, isso
  acontece a cada edição de código) deixava a trava órfã, e os itens da mesma família esperavam até ela
  expirar. Agora a validade é de 1 minuto, renovada enquanto o trabalho dura (`trava_viva`).

## Cobertura por ramo (conferida com a tabela cClassTrib de 2026-09)

| Ramo | Regime da operação ativo | O que decide |
|---|---|---|
| Restaurante, bar, lanchonete | bares e restaurantes (200047) | Operação para o que é preparado; produto para o que é revendido pronto e para as bebidas alcoólicas |
| Padaria / supermercado com lanchonete (`fornece_refeicoes = sim`) | bares e restaurantes, com a pergunta "servido como refeição?" | Operação só para o que é servido; produto para a mercadoria |
| Supermercado sem refeições | nenhum | Produto (sem mudança) |
| Farmácia de manipulação (`manipula_medicamentos = sim`) | manipulação (200032) | Operação para o manipulado; produto para o industrializado (200032 pela Anvisa, 200009 alíquota zero etc.) |
| Farmácia / drogaria sem manipulação | nenhum | Produto (sem mudança) |
| Autopeças, roupas, material de construção, varejo em geral | nenhum | Produto; em regra, 000001 |

## Fora do escopo, de propósito

- **Comprador ou destino** (governo, PcD/taxista, produtor rural, exportação, Zona Franca): mudam a nota
  de uma venda específica, não o cadastro do item. Entram quando houver cenários de operação além da
  venda ao consumidor.
- **Imunidade ou não incidência pelo vendedor** (entidade religiosa, partido, sindicato, instituição de
  educação ou assistência sem fins lucrativos, art. 9º; nanoempreendedor, art. 26): o catálogo
  comporta esses regimes (só a condição de empresa), mas o dossiê ainda não pergunta a natureza
  jurídica. Nenhum dos ramos atendidos hoje é desse tipo.
- **Hotelaria, parques e agências de turismo** (200048, 200051): são serviços (NBS) com regime
  específico. Entram no catálogo quando esses segmentos existirem no dossiê.

## Consequências

- Itens iguais recebem o mesmo tratamento do regime, com o mesmo fundamento, em qualquer família.
- As teses de família de empresas com `fornece_refeicoes = sim` mudam de chave (o 200047 saiu do
  material do Jurista). Ao reanalisar, essas famílias são estudadas de novo, uma vez cada.
- Pendências: medir o prompt `extrair_fatos` v2 no conjunto-ouro com itens de restaurante, padaria e
  farmácia; melhorar a busca de candidatos para bebidas e pratos prontos (capítulo 21).
