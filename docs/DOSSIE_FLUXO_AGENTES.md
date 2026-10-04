# Dossiê Completo de Arquitetura e Fluxo de Agentes: Auditor Fiscal de Cadastros (Reforma Tributária - LC 214/2025)

> **Finalidade deste documento:** Registro detalhado, fidedigno e didático de todo o funcionamento do sistema, cobrindo o problema que ele resolve, os componentes de infraestrutura, os agentes de chegada da planilha e os agentes de processamento item a item até o *Leitor de Fatos*. Este documento foi estruturado para permitir a continuação imediata desta análise em qualquer outro assistente de IA.

---

## 1. Visão Geral e o Problema que o Sistema Resolve

### O Problema do Negócio
Com a aprovação da **Reforma Tributária do Consumo no Brasil (Emenda Constitucional 132/2023, Lei Complementar 214/2025, LC 227/2026 e Decreto 12.955/2026)**, os antigos tributos sobre o consumo (PIS, COFINS, ICMS, ISS e IPI) serão substituídos pelo **IBS** (Imposto sobre Bens e Serviços) e pela **CBS** (Contribuição sobre Bens e Serviços), além do **IS** (Imposto Seletivo).
Cada produto ou serviço comercializado no país precisa receber novas etiquetas fiscais padronizadas:
- **CST** (Código de Situação Tributária).
- **cClassTrib** (Código de Classificação Tributária oficial da Reforma).

As empresas possuem cadastros legados nos seus sistemas ERP com dezenas ou centenas de milhares de itens cadastrados com descrições truncadas, abreviadas, marcas comerciais e códigos antigos (NCM/NBS) frequentemente incorretos ou defasados. Se um contador fosse analisar manualmente item por item à luz das novas centenas de artigos e anexos da lei, o processo levaria meses e custaria valores impraticáveis.

### A Solução
O sistema atua como um **Analista Fiscal Digital**. Ele não faz um "de-para" cego de códigos. Ele:
1. Audita e identifica o que o item realmente é com base na sua descrição e nas tabelas oficiais do governo (NCM do Siscomex e NBS do MDIC).
2. Constrói uma **tese jurídica** fundamentada na lei oficial por **família de produtos** (reaproveitada entre todos os itens com o mesmo perfil).
3. Levanta os fatos reais do item sem alucinações (suposição não vira fato).
4. Aplica os fatos às hipóteses legais e gera o perfil tributário auditável (`tax_profiles`), com justificativa e referência aos artigos da lei.
5. Se faltar alguma informação que mude a alíquota, agrupa em perguntas inteligentes para o responsável responder de uma só vez.

---

## 2. Analogia Central: O Escritório e a Biblioteca da Escola

Para facilitar a compreensão e a interface do usuário (ADR 0016), o sistema é modelado como um **escritório com funcionários especializados**:
- **Funcionários da Planilha Inteira (Chegada):** Cuidam do arquivo em bloco, antes de qualquer IA ser chamada.
- **Funcionários de Cada Item (A Esteira LangGraph):** Pegam item por item e guiam a análise por um grafo de decisão determinístico e inteligente.

---

## 3. Infraestrutura e Orquestração: Celery, Redis e LangGraph

### O "Cérebro" e os "Músculos"
- **LangGraph (O Cérebro):** Define a máquina de estados finitos e o grafo de nós (agentes) por onde cada item transita. Possui persistência via *checkpoints* no PostgreSQL (`PostgresSaver`), permitindo que a execução seja interrompida, pausada ou retomada exatamente de onde parou.
- **Celery + Redis (Os Músculos e a Fila):**
  - **Redis:** Atua como o "varal de comandas" em memória. Guarda a fila de tarefas ultrarrápida.
  - **Celery Workers:** É o time de operários em segundo plano que executa as tarefas pesadas sem travar a interface web.

### Como funciona a divisão dos itens (`TAMANHO_BLOCO = 10` e `-c 4`):
1. **Fatiamento em Pacotes:** O sistema pega a lista total de itens da auditoria e divide em blocos fixos de **10 itens** (`backend/app/audits/processing.py`). Exemplo:
   - 30 itens $\rightarrow$ 3 pacotes de 10.
   - 55 itens $\rightarrow$ 5 pacotes de 10 + 1 pacote de 5 itens.
2. **Execução Paralela:** O worker do Celery está configurado por padrão com concorrência 4 (`-c 4` no `compose.yaml`).
   - Isso significa que **4 operários trabalham simultaneamente**.
   - Se houver 30 itens (3 pacotes), 3 operários pegam um pacote cada e trabalham em paralelo no mesmo segundo. O quarto operário fica livre.
   - Para 55 itens (6 pacotes), 4 operários pegam os 4 primeiros pacotes. Assim que qualquer um termina suas 10 fichas, ele puxa o pacote 5 e depois o pacote 6.
3. **Execução por Item no LangGraph:** Dentro de cada pacote de 10, o operário do Celery executa o LangGraph sequencialmente para cada item (do item 1 ao item 10), garantindo isolamento e gravação de estado.

---

## 4. Agentes da Chegada (Processamento da Planilha Inteira)

Estes agentes atuam em nível de arquivo, antes de a análise individual começar:

### 4.1. Recepcionista (`api/audits.py` / `UploadedFile`)
- **Papel:** Porta de entrada e leitura física do arquivo.
- **O que faz:** Lê o arquivo `.xlsx`, `.xls` ou `.csv`, valida se o arquivo não está corrompido, impede macros perigosas e faz a leitura estruturada das colunas.
- **O que NÃO faz:** Não analisa impostos, não altera textos e não analisa itens isolados.
- **Custo:** Grátis (zero IA).
- **Decisão:** Se o arquivo for inválido $\rightarrow$ rejeita na porta; se válido $\rightarrow$ envia ao Conferente.

### 4.2. Conferente (`api/audits.py` / `UploadedFile`)
- **Papel:** Limpeza de linhas e validação estrutural da planilha.
- **O que faz:** Remove linhas em branco, detecta cabeçalhos duplicados, confere se as colunas obrigatórias existem (descrição e código), detecta itens sem nome e conta os itens válidos.
- **O que NÃO faz:** Não julga nomes, não calcula valores fiscais.
- **Custo:** Grátis (zero IA).
- **Decisão:** Se faltar coluna obrigatória $\rightarrow$ barra com erro; se correto $\rightarrow$ envia ao Orçamentista.

### 4.3. Orçamentista (`app/ingest/estimate.py` / `previa`)
- **Papel:** Previsão transparente de custos de Inteligência Artificial e tempo.
- **O que faz:** Analisa o volume de itens, calcula quantas chamadas de IA serão evitadas (por produtos repetidos e famílias compartilhadas), estima o gasto em dólares (US$) e verifica se a empresa tem saldo no seu orçamento mensal.
- **Recomendação de Modo:** Se a planilha for grande, sugere o modo **Lote (Batch API)** que oferece 50% de desconto no custo de IA da Anthropic.
- **O que NÃO faz:** Não inicia a execução sozinho; não debita sem consentimento.
- **Custo:** Grátis.
- **Decisão:** Se o orçamento mensal estiver estourado $\rightarrow$ bloqueia o início; se houver saldo $\rightarrow$ exibe a prévia na tela.

### 4.4. Você (Ação Humana Obrigatória)
- **Papel:** O tomador de decisão (Diretor da Escola).
- **O que faz:** Trava de segurança humana. Escolhe o modo de processamento (`tempo_real` ou `lote`), visualiza o custo estimado e clica no botão **"Confirmar e Iniciar"**. Nenhuma IA é chamada antes dessa autorização expressa.
- **Custo:** Ação humana.
- **Decisão:** Confirmar e iniciar $\rightarrow$ dispara o Distribuidor; Cancelar/Ajustar $\rightarrow$ nada é cobrado.

### 4.5. Distribuidor (`app/audits/processing.py` - `enfileirar_itens`)
- **Papel:** Despachante logístico da esteira.
- **O que faz:** Pega a lista de IDs de todos os itens aprovados pelo usuário, fatia em lotes de 10 itens e despacha como tarefas na fila do Celery (`queue="pipeline"`), utilizando o Redis como intermediário.
- **O que NÃO faz:** Não analisa regras fiscais nem altera dados dos produtos.
- **Custo:** Grátis.
- **Decisão:** Despacha as tarefas e acorda os operários do Celery para iniciarem a esteira item a item.

---

## 5. Agentes de Cada Item (A Esteira LangGraph)

A partir daqui, cada item segue individualmente o fluxo orquestrado pelo LangGraph:

```text
[Arrumador] ──► [Fiscal da Tabela] ──► [Arquivista] ──(não achou)──► [Pesquisador]
                                             │                                 │
                                      (achou na memória)                 (confirmado
                                             │                            sem IA)
                                             ▼                                 ▼
                                      [Jurista (Tese)] ◄───────────────────────┘
                                             ▲
                                             │
      [Pesquisador] ──► [Identificador (IA)] ┼──(certeza alta)──► [Jurista]
                              │              │
                    (gatilho de dúvida)      │
                              ▼              │
                    [Segundo Parecer (IA)] ──┤
                              │              │
                   (nenhum candidato serve)  │
                              ▼              │
                   [Navegador da Árvore] ────┴──(código achado)──► [Jurista]
                              │
                     (sem código na árvore)
                              ▼
                     [Leitor de Fatos] ──► [Juiz]
```

### 5.1. Agente: Arrumador (`normalizar` em `nodes.py`)
- **Papel:** Limpeza e padronização do texto da descrição.
- **O que faz:**
  1. Remove a marca comercial (ex: remove "Dove" de "Sabonete Dove", pois marca não altera a alíquota tributária).
  2. Expande abreviações usando um dicionário customizado (ex: troca "refrig." por "refrigerante", "cx" por "caixa").
  3. Infere se o item é um `PRODUTO` (físico/NCM) ou `SERVICO` (NBS).
- **Caminhos Internos de Decisão:**
  - *Caminho 1 (Rápido e Grátis):* Texto limpo via dicionário $\rightarrow$ segue direto sem IA.
  - *Caminho 2 (Dúvida com IA Leve):* Se sobrarem 2 ou mais palavras estranhas/desconhecidas no nome $\rightarrow$ chama o modelo leve (Claude Haiku) com prompt específico para desvendar as abreviações.
  - *Caminho 3 (Recuperação de Falha):* Se a IA leve oscilar/falhar $\rightarrow$ o sistema captura a exceção, mantém a melhor descrição possível e segue em frente sem quebrar.
- **Entrada (Input):** Descrição original, marca, tipo informado pelo ERP e dicionário de abreviações.
- **Saída (Output):** `descricao_normalizada`, lista de `expansoes` realizadas e `tipo` (`PRODUTO` ou `SERVICO`).

---

### 5.2. Agente: Fiscal da Tabela (`validar_estrutura` em `nodes.py`)
- **Papel:** Auditoria dos códigos antigos cadastrados no ERP.
- **O que faz:** Não confia no cadastro legado (trata-o como mera "evidência"). Valida o código NCM/NBS contra a tabela oficial do governo carregada no banco:
  1. Verifica se o código existe de fato.
  2. Verifica se está completo (NCM com 8 dígitos; se tiver 7, detecta se o Excel engoliu o zero à esquerda e testa com "0").
  3. Verifica se o código está vigente na data de referência da auditoria (ex: 2027).
- **O que NÃO faz:** Não usa IA; não avalia se o código combina com o texto do produto.
- **Entrada (Input):** Código NCM/NBS informado, tipo do item e tabelas oficiais vigentes.
- **Saída (Output):** Raio-X do código atual (`existe`, `vigente`, `folha`), motivos de erro (`NCM_INEXISTENTE`, `NCM_NAO_VIGENTE`, `NCM_ZERO_A_ESQUERDA_SUSPEITO`, etc.) e sinalização de `base_incompleta`.
- **Caminho e Fluxo de Decisão:**
  - *Rota 1 (`base_incompleta == True`):* Se faltar alguma tabela oficial no sistema $\rightarrow$ pula todo o fluxo e vai direto para a mesa de encerramento com erro.
  - *Rota 2 (`base_incompleta == False`):* Código validado $\rightarrow$ segue para o **Arquivista**.

---

### 5.3. Agente: Arquivista (`buscar_memoria` em `nodes.py`)
- **Papel:** O guardião da memória histórica de aprovações da empresa.
- **O que faz:** Busca se aquele item idêntico (verificado por *hash* da descrição normalizada e código de barras GTIN) **já foi auditado e aprovado anteriormente por um ser humano nesta empresa** (`ApprovedMemory`).
- **O que NÃO faz:** Não reutiliza palpites automáticos de IA; só aceita o que teve validação humana anterior. Não compartilha memória entre empresas diferentes.
- **Custo:** 100% grátis (busca direta no banco).
- **Entrada (Input):** Hash da descrição normalizada, GTIN, `company_id`.
- **Saída (Output):** `memoria` (dados fiscais aprovados no passado) ou `None`.
- **Caminho e Fluxo de Decisão (O Grande Atalho):**
  - *Rota 1 (Achou na Memória):* **Pula** o Pesquisador, o Identificador, o Segundo Parecer e o Navegador da Árvore! Vai direto para a mesa do **Jurista** (`investigar`). Economia total de IA na identificação!
  - *Rota 2 (Não achou):* Segue o fluxo normal para o **Pesquisador**.

---

### 5.4. Agente: Pesquisador (`recuperar_candidatos` em `nodes.py` e `search.py`)
- **Papel:** Garimpeiro e criador da prova de múltipla escolha com candidatos oficiais.
- **Arquitetura de RAG Híbrido Local:**
  - Não utiliza modelos pagos externos (como OpenAI) para busca/embeddings.
  - Utiliza o modelo aberto **`multilingual-e5-base`** (ou `bge-m3`) rodando localmente em contêiner Docker via Hugging Face Text Embeddings Inference (TEI). Custo de busca = **R$ 0,00**, com privacidade total (LGPD) e resposta em milissegundos.
  - Faz busca híbrida: **Busca Vetorial (pgvector)** + **Busca Textual em Português (tsvector)**, combinadas pelo algoritmo **RRF** (*Reciprocal Rank Fusion*).
  - Traz os "irmãos" do código antigo do ERP (mesmos primeiros 4 dígitos) para a lista de candidatos.
  - Busca na Lei Complementar 214/2025 se o produto é explicitamente citado em algum anexo com código recomendado.
- **O Atalho da "Confirmação Sem IA":**
  Se o código antigo do ERP existir, estiver vigente e ficar em **1º lugar** tanto na busca por palavras quanto na busca por significado sem nenhuma divergência, o sistema carimba `confirmado_sem_ia = True`!
- **Entrada (Input):** Descrição normalizada, código antigo do ERP, índice local de embeddings e tabelas oficiais.
- **Saída (Output):** Lista de até **15 candidatos oficiais** (com descrição completa e notas da lei) e flag `confirmado_sem_ia`.
- **Caminho e Fluxo de Decisão:**
  - *Rota 1 (`confirmado_sem_ia == True`):* Pula o Identificador, Segundo Parecer e Navegador. Vai direto ao **Jurista**.
  - *Rota 2 (Candidatos levantados com incerteza):* Envia a prova para o **Identificador**.
  - *Rota 3 (Nenhum candidato adequado encontrado):* Envia direto para o **Navegador da Árvore**.

---

### 5.5. Agente: Identificador (`julgar_coerencia` em `nodes.py`)
- **Papel:** O analista com IA que responde à prova de múltipla escolha.
- **Modelo Utilizado:** Modelo primário rápido (Claude 3.5 Haiku).
- **O que faz:**
  1. Escolhe o código mais adequado dentre a lista fechada de 15 candidatos.
  2. Avalia se o código antigo do ERP era coerente ou incorreto (`ncm_atual_coerente`).
  3. Atribui uma nota de confiança (0.0 a 1.0) conforme uma régua rigorosa do prompt (`v2.md`):
     - `0.95+`: Descrição inequívoca e código único em todos os níveis.
     - `0.80 - 0.94`: Escolha bem sustentada com ambiguidade mínima.
     - `0.50 - 0.79`: Dois ou mais candidatos plausíveis ou descrição omissa em ponto crítico.
     - `< 0.50`: Descrição insuficiente ou nenhum candidato adequado.
  4. Aponta sinais de dúvida textuais (ex: "não diz se tem açúcar").
- **Proteção Contra Alucinação (`_validar_codigo`):** Se a IA sugerir qualquer código que **não** estava na lista oficial de candidatos entregue pelo Pesquisador, a resposta é **descartada sumariamente** pelo código em Python.
- **Avaliação dos 5 Alarmes no Python (1 chamada de IA apenas):**
  A IA responde uma única vez. O Python avalia 5 condições lógicas (`gatilhos`):
  1. `baixa_confianca`: Confiança menor que o limiar configurado pela organização.
  2. `codigo_atual_incoerente`: IA marcou que o NCM antigo do ERP estava errado.
  3. `sem_codigo_atual_valido`: Item não tinha código válido de origem.
  4. `divergencia_busca_julgamento`: IA escolheu um candidato abaixo do 10º lugar sem ter 95% de certeza.
  5. `sinais_de_duvida`: IA apontou dúvidas e a confiança foi < 85%.
- **Caminho e Fluxo de Decisão:**
  - *Rota 1 (Pelo menos 1 alarme disparado):* Segue para o **Segundo Parecer** (`escalar`).
  - *Rota 2 (Marcou que 'nenhum candidato serve' ou resposta descartada):* Segue para o **Navegador da Árvore** (`navegar_arvore`).
  - *Rota 3 (Alta confiança, sem alarmes):* Pula o Segundo Parecer e vai direto ao **Jurista** (`investigar`).

---

### 5.6. Agente: Segundo Parecer (`escalar` em `nodes.py`)
- **Papel:** Revisor sênior e independente para casos difíceis.
- **Modelo Utilizado:** Modelo de alto raciocínio (Claude 3.5 Sonnet).
- **O que faz:**
  - Lê um prompt específico (`backend/prompts/escalar/v2.md`).
  - Recebe a ficha do item, a lista de candidatos, a resposta do primeiro analista e os motivos exatos do alarme.
  - Tem instrução expressa para **não concordar por mera simpatia**; reanalisa o produto e dá a palavra final:
    - Confirma a escolha do primeiro (`concorda_com_analise_anterior = True`).
    - Ou corrige e escolhe outro candidato oficial da lista.
    - Ou confirma que nenhum candidato da lista é aplicável.
- **Custo:** IA avançada (acionada apenas por exceção).
- **Caminho e Fluxo de Decisão:**
  - *Rota 1 (Código escolhido com sucesso):* Segue para o **Jurista** (`investigar`).
  - *Rota 2 (Nenhum código serve):* Segue para o **Navegador da Árvore** (`navegar_arvore`).

---

### 5.7. Agente: Navegador da Árvore (`navegar_arvore` em `arvore.py`)
- **Papel:** O guia de resgate pela hierarquia oficial da Receita Federal.
- **Quando é acionado:** Apenas quando o item ficou totalmente sem código (o Pesquisador não achou opções viáveis e o Identificador/Segundo Parecer concluíram que nenhuma opção servia).
- **Como Funciona (A Descida dos Galhos):**
  A tabela NCM do banco foi modelada como uma árvore (`ncm_nodes` com `codigo_pai` e `folha`):
  1. *Tronco (Capítulo - 2 dígitos):* Mostra apenas grandes categorias e a IA escolhe a gaveta (ex: Capítulo 34 - Sabões).
  2. *Galho (Posição - 4 dígitos):* Abre a pasta e a IA escolhe a subcategoria (ex: 3401 - Sabões e preparações para pele).
  3. *Subposição (6 dígitos):* A IA escolhe o estado físico (ex: 3401.30 - Líquido ou creme).
  4. *Folha (8 dígitos):* A IA escolhe o código final de venda a retalho (`3401.30.00`).
- **Por que a IA não raciocina pesado aqui:** A IA só escolhe entre placas de trânsito válidas exibidas pelo banco. O risco de inventar código é zero.
- **Caminho e Fluxo de Decisão:**
  - *Rota 1 (Código encontrado):* Segue para o **Jurista** (`investigar`).
  - *Rota 2 (Item impossível de identificar):* Pula o Jurista da família e vai ao **Leitor de Fatos** (para verificar se algum regime da empresa resolve o imposto).

---

### 5.8. Agente: Jurista (`investigar` em `analista.py` e `evidencias.py`)
- **Papel:** Advogado tributarista que estuda a nova lei (LC 214/2025) e cria a Tese da Família.
- **O Segredo da Economia: 1 Tese por Família:**
  - A lei é estudada **uma única vez para cada código NCM/NBS + perfil da empresa + vigência**.
  - A tese é gravada na tabela **`tax_theses`** do PostgreSQL.
  - Todos os itens com o mesmo código utilizam a mesma tese, zerando chamadas repetidas de IA!
- **Proteção Concorrente (`trava_viva`):** Se dois operários pegarem itens da mesma família ao mesmo tempo (ex: Coca-Cola e Fanta), um operário põe uma trava no Redis enquanto estuda a lei, e o outro aguarda alguns segundos para reaproveitar a tese pronta, evitando cobrança duplicada.
- **Conteúdo da Tese (`resultado` em `tax_theses`):**
  Gera de 2 a 4 hipóteses jurídicas em ordem de prioridade, com fundamento em artigos da lei:
  - *Hipótese 1 (Benefício máximo):* Ex: Alíquota zero da Cesta Básica ou Isenção.
  - *Hipótese 2 (Benefício parcial):* Ex: Redução de 60% com condições específicas.
  - *Última Hipótese (Regra Geral):* Tributação integral de IBS/CBS (`cClassTrib: 000001`), servindo como garantia residual se nenhuma condição for atendida.
- **Entrada (Input):** Código NCM/NBS consolidado, dossiê do perfil da empresa, base normativa versionada da Reforma Tributária (LC 214/2025).
- **Saída (Output):** `tese_id` gravado no banco de dados e conjunto estruturado de hipóteses, condições exigidas e artigos legais citados.
- **Próximo Passo:** Entrega a Tese com suas exigências para o **Leitor de Fatos**.

---

### 5.9. Agente: Leitor de Fatos (`levantar_fatos` em `analista.py` / `fatos.py`)
- **Papel:** O perito investigador que confere se o item real cumpre as exigências das hipóteses.
- **O que faz:**
  1. Recebe da Tese do Jurista as **perguntas condicionais** que a lei impôs (ex: *"é fio dental?"*, *"tem adição de açúcar?"*, *"consta na lista oficial do art. 146?"*).
  2. Lê minuciosamente a descrição e os dados do item no ERP para tentar responder a essas perguntas com base em evidências textuais.
- **A Regra "Suposição NÃO vira fato":**
  - Se a embalagem diz explicitamente *"FIO DENTAL 50M"* $\rightarrow$ crava o fato oficial: `produto_e_fio_dental = "sim"`.
  - Se a descrição for genérica ou dúbia (ex: *"MEDICAMENTO XYZ 500MG"* sem dizer se está na lista especial do art. 146) $\rightarrow$ a IA é terminantemente proibida de chutar! Ela marca como **"desconhecido"**.
- **O que acontece com os fatos desconhecidos:**
  Em vez de inventar um imposto errado, o sistema transforma a condição em uma **Pergunta Decisiva** na interface.
  - As perguntas são **agrupadas por família ou categoria**: se houver 50 itens idênticos com a mesma dúvida, o sistema faz **1 única pergunta** para o contador responder para os 50 itens de uma só vez!
- **Entrada (Input):** Descrição do produto, perfil da empresa e lista de fatos necessários exigidos pelas hipóteses da Tese.
- **Saída (Output):** Fatos gravados com origem comprovada (`CompanyFact`) e pendências de perguntas para o usuário nos pontos onde faltam dados.
- **Próximo Passo:** Entrega a tese e os fatos comprovados para a conclusão final no agente **Juiz** (`concluir`).

---

## 5.10. O que mudou em 01–02/10/2026 (ADR 0029: só vai para uma pessoa o que muda o imposto)

Medido sem IA em 135 itens reais: os itens que iam para uma pessoa caíram de 44% para 5%, sem nenhum item
classificado sozinho com resultado diferente do que uma pessoa já tinha decidido.

- **Distribuidor / esteira:** se a plataforma de IA não responde (sem créditos, fora do ar), ninguém tenta
  "plano B" e nenhum item vai para revisão. A auditoria fica "Pausada (a IA não respondeu)" e volta sozinha.
- **Arrumador:** o campo "tipo" do ERP em texto livre agora é entendido ("Produção interna", "Revenda de…",
  "Medicamento…" = mercadoria). Antes, o item ficava "desconhecido" e a busca incluía serviços (foi assim
  que o frango assado de rotisseria recebeu um código de serviço de fast-food).
- **Pesquisador:** itens quase iguais que pessoas da organização já aprovaram entram na prova. Se a pessoa
  aprovou o mesmo NCM do ERP para um item quase igual, o código é confirmado sem IA.
- **Identificador e Segundo Parecer (instruções v3):** o NCM do ERP é o ponto de partida (conferir, não
  reclassificar do zero) e conta como um voto: ERP + Segundo Parecer iguais = confirmado, mesmo que o
  primeiro discorde. Dúvida só vale se apontar palavras da descrição ("e se fosse descafeinado?" sem nada na
  descrição vira observação).
- **Navegador (instrução v3):** traduz o nome de loja para o nome técnico da tabela ("Gallus domesticus" é
  frango; assado é "cozido") antes de dizer que nenhuma opção serve.
- **Navegador (instrução v4):** quando fica em dúvida entre dois capítulos (cru × preparado, fresco ×
  conservado), procura o código nos dois e dá a cada opção um nome de loja ("hortaliças frescas cortadas"
  × "salada preparada"). Se os impostos forem diferentes, o operador responde qual é o item, em vez de o
  contador revisar. Se num dos capítulos nenhum código for achado, o item não sai sozinho.
- **Navegador (instrução v5):** ao escolher a posição, vê o que cada uma inclui (ex.: 16.02 "Outras
  preparações de carne" inclui "de aves"), e sabe que um título geral abrange o que não nomeia. Com
  esforço de raciocínio maior, todos os agentes recebem mais espaço de resposta, para o raciocínio não
  cortar a resposta.
- **Jurista (instrução v4):** todo conflito diz qual fato o resolve (ex.: "destinado a ração?"); o fato
  conhecido resolve sozinho.
- **Juiz:** pergunta "o imposto muda?". Se todos os NCM possíveis dão o mesmo imposto, o item sai
  classificado e o NCM vai para a lista **Ajustes de cadastro**. Se dão impostos diferentes, pergunta ao
  operador "o que é este item?". Imposto Seletivo: só para NCM do Anexo XVII; para quem só revende, sai
  "na origem" (cobrado na fábrica).
- **Secretário:** pergunta sobre a empresa (ex.: "a empresa fabrica ou importa?") vale sempre para a
  empresa toda, mesmo respondida no detalhe de um item.
- **Revisão:** a fila abre **por grupo** (uma decisão resolve os itens iguais) e aprovar um item aprova na
  hora os iguais da mesma auditoria, com "Desfazer todos". O botão **Reaplicar regras (sem IA)** atualiza
  auditorias concluídas sem custo.

---

## 5.11. O que mudou em 02/10/2026 (ADR 0030: cada produto com a sua resposta)

- **Secretário:** pergunta sobre a empresa continua com uma resposta só. Pergunta sobre o produto com vários
  itens agora é respondida item a item, com a lista à vista ("Marcar todos" agiliza). Antes, um clique em
  "Sim para os 12" gravou "dispositivo médico" em oito remédios.
- **Correção de respostas:** em "Ver perguntas respondidas", "Corrigir respostas" mostra cada item com a
  resposta que vale hoje; só os que mudarem são reavaliados, sem IA.
- **Jurista (instrução v5):** cada benefício que a lei dá pela natureza do produto vem com o nome fixo da
  pergunta (ex.: "medicamento_aliquota_zero_art146"); antes, cada parecer inventava um nome e o operador
  respondia a mesma coisa várias vezes. Medicamento também em 30.02 (imunológicos), 3006.30 (contrastes) e
  3006.60 (anticoncepcionais).
- **Catálogo de fatos padronizados:** as condições que se repetem têm nome e pergunta fixos, e o sistema
  responde sozinho o que a lei presume (remédio vendido no varejo é registrado na Anvisa), o que o ERP já diz
  (remédio não é dispositivo médico) e o que o dossiê diz (quem não manipula não vende manipulado). A
  sinvastatina, que recebia cinco perguntas, ficou com uma.

---

## 6. Próximos Passos na Sequência da Conversa

Os componentes que completam o ciclo de vida do sistema e que devem ser abordados no próximo bloco são:
1. **O Juiz (`concluir` / `avaliacao.py`):** A função pura e matemática (sem IA) que cruza os fatos levantados com as hipóteses da tese para definir o CST, cClassTrib, alíquotas do IBS/CBS e Imposto Seletivo.
2. **As 4 Caixas de Confiança:** Como o sistema calcula o grau de certeza em 10 dimensões e classifica o item em: *Classificado*, *Aguardando Informação*, *Revisão do Contador* ou *Revisão do Especialista*.
3. **O Secretário (Perguntas Agrupadas e Reavaliação):** Como a resposta a uma pergunta reclassifica centenas de itens instantaneamente no banco sem novo custo de IA (`aplicacao.reavaliar`).
4. **O Dossiê Tributário e a Exportação:** A geração do perfil tributário imutável (`tax_profiles`) e a exportação final da planilha pronta para o ERP da empresa.
