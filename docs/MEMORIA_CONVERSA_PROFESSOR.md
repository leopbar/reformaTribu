# MEMÓRIA E TRANSCRIÇÃO DIDÁTICA DA CONVERSA: FLUXO DE AGENTES (REFORMA TRIBU)

> **Instrução para a próxima IA (Professor que assumir):**
> Você está assumindo o papel de um **professor paciente, criativo e didático**, especialista em explicar sistemas complexos para **leigos e crianças de 12 anos**.
> O usuário está estudando o projeto **reformaTribu** (um auditor fiscal de cadastros para a Reforma Tributária da LC 214/2025).
> **Regra de ouro mantida:** Explicamos **um agente por vez**, em ordem cronológica de esteira, e **só passamos para o próximo agente depois que o usuário confirma que entendeu perfeitamente**.
> Usamos a analogia consistente da **escola / biblioteca** (ou do escritório de funcionários).
> A conversa parou exatamente após o **Leitor de Fatos** ser compreendido. O próximo agente a ser apresentado é o **Juiz** (`concluir`).

---

## 1. O Acordo Inicial e Como as Explicações São Conduzidas
- **Linguagem:** Sem "tecniquês" sem explicação imediata. Metáforas do cotidiano (biblioteca da escola, operários, gaveteiros, esteiras de correio).
- **Rigor:** Fiel ao código real do repositório, mas sempre traduzido para conceitos simples.
- **Ritmo:** Um único agente por vez, detalhando:
  1. Quem ele é e o que ele faz.
  2. O que ele NÃO faz.
  3. Entradas (Input) e Saídas (Output).
  4. Caminhos e fluxo de decisão (bifurcações lógicas).
  5. Pergunta ao usuário se entendeu antes de avançar.

---

## 2. O Que Já Foi Explicado e Consolidado na Conversa (Até Agora)

### Parte A: A Chegada da Planilha (O Arquivo Inteiro)
Antes de olhar os produtos individualmente, o sistema processa a planilha em bloco:

1. **O Recepcionista (`api/audits.py` / `UploadedFile`):**
   - *Metáfora:* O porteiro da escola que recebe o envelope pesado de correspondência com a planilha do ERP.
   - *O que faz:* Confere se o arquivo abre sem erros (.xlsx, .csv), barra macros perigosas. Não usa IA (grátis).
   - *Decisão:* Se corrompido $\rightarrow$ rejeita na porta; se válido $\rightarrow$ passa para o Conferente.
   - *Status do usuário:* Entendido e confirmado.

2. **O Conferente (`api/audits.py`):**
   - *Metáfora:* O inspetor metódico de régua na mão.
   - *O que faz:* Limpa linhas em branco, cabeçalhos repetidos, verifica se as colunas essenciais existem e conta as linhas válidas.
   - *Decisão:* Se faltar coluna de descrição $\rightarrow$ erro; se correto $\rightarrow$ passa para o Orçamentista.
   - *Status do usuário:* Entendido e confirmado.

3. **O Orçamentista (`app/ingest/estimate.py`):**
   - *Metáfora:* O contador responsável com a calculadora antes de gastar qualquer centavo.
   - *O que faz:* Calcula uma estimativa prévia de custo em dólares (US$) para as chamadas de IA. Avalia se compensa rodar em Tempo Real ou Lote (Batch API com 50% de desconto). Confere se não ultrapassa o orçamento mensal da empresa.
   - *Decisão:* Se estourar o orçamento $\rightarrow$ trava; se tiver saldo $\rightarrow$ mostra a prévia na tela.
   - *Status do usuário:* Entendido e confirmado.

4. **Você (Ação Humana Obrigatória):**
   - *Metáfora:* O Diretor da Escola batendo o martelo.
   - *O que faz:* Trava de segurança. Nenhuma IA trabalha antes que o usuário humano escolha a velocidade (tempo real ou lote) e clique em "Confirmar e Iniciar".
   - *Status do usuário:* Entendido e confirmado.

5. **O Distribuidor (`app/audits/processing.py` - `enfileirar_itens`):**
   - *Metáfora:* O despachante com carrinhos de mão e esteiras rolantes.
   - *Dúvidas aprofundadas e sanadas sobre a infraestrutura:*
     - **Pacotes fixos de 10 (`TAMANHO_BLOCO = 10`):** O sistema fatia a planilha em envelopes de até 10 itens. Se tiver 30 itens $\rightarrow$ 3 pacotes de 10. Se tiver 55 itens $\rightarrow$ 5 pacotes de 10 + 1 pacote de 5 itens.
     - **O que é o Redis:** É o varal de pedidos em memória ultrarrápida onde os pacotes de 10 ficam pendurados.
     - **O que é o Celery:** É a equipe de cozinheiros/operários em segundo plano.
     - **Quantos operários trabalham juntos:** O comando tem `-c 4` (concorrência 4), significando **4 operários trabalhando simultaneamente em paralelo**! Ou seja, 4 pacotes de 10 são processados ao mesmo tempo.
     - **Relação com o LangGraph:** O LangGraph é o mapa de regras/cérebro; o Celery é o operário com pernas e mãos que carrega a prancheta do LangGraph durante todo o percurso.
   - *Status do usuário:* Entendido e confirmado com louvor.

---

### Parte B: A Esteira de Cada Produto (Agente por Agente no LangGraph)

6. **O Arrumador (`normalizar` em `nodes.py`):**
   - *Metáfora:* O tradutor e faxineiro de etiquetas rasuradas.
   - *O que faz:* Tira a marca comercial (ex: tira "Dove", pois marca não altera imposto), troca abreviações por palavras completas via dicionário e classifica como `PRODUTO` ou `SERVICO`.
   - *Caminhos internos:*
     1. Sem IA (grátis) se o dicionário resolveu.
     2. Com IA Leve (Claude Haiku) se restarem 2 ou mais palavras misteriosas.
     3. Recuperação de falha se a IA leve oscilar (continua sem travar).
   - *Status do usuário:* Entendido e confirmado.

7. **O Fiscal da Tabela (`validar_estrutura` em `nodes.py`):**
   - *Metáfora:* O auditor rigoroso que abre a lista oficial do governo (Siscomex).
   - *O que faz:* Confere se o código antigo (NCM/NBS) existe de verdade, se tem 8 dígitos (detecta se o Excel comeu o zero à esquerda e restaura) e se está vigente na data da auditoria. Código do ERP é tratado como mera "evidência", nunca como verdade cega.
   - *Rotas:* Se base incompleta $\rightarrow$ encerra com erro; se válida $\rightarrow$ vai para o Arquivista.
   - *Status do usuário:* Entendido e confirmado.

8. **O Arquivista (`buscar_memoria` em `nodes.py`):**
   - *Metáfora:* O guardião do gaveteiro de decisões antigas aprovadas.
   - *O que faz:* Procura se esse item idêntico já foi **auditado e aprovado no passado por um ser humano nesta mesma empresa** (`ApprovedMemory`).
   - *O Grande Atalho:* Se achar na memória, **PULA** o Pesquisador, o Identificador, o Segundo Parecer e o Navegador da Árvore, indo direto ao Jurista!
   - *Status do usuário:* Entendido e confirmado.

9. **O Pesquisador (`recuperar_candidatos` em `nodes.py` e `search.py`):**
   - *Metáfora:* O criador da prova de múltipla escolha.
   - *O que faz:* Faz um **RAG Híbrido Local Gratuito**. Usa o modelo aberto **`multilingual-e5-base`** baixado da Hugging Face rodando localmente no Docker (sem OpenAI, sem custo por busca e respeitando a LGPD). Cruza busca por palavras com busca por significado via algoritmo RRF e monta uma lista de **até 15 candidatos oficiais**.
   - *Atalho Confirmação Sem IA:* Se o código antigo for o 1º lugar em ambas as buscas e sem dúvidas na lei, carimba como confirmado sem gastar IA e pula para o Jurista.
   - *Rotas:* Confirmado sem IA $\rightarrow$ pula ao Jurista; Dúvidas $\rightarrow$ manda a prova para o Identificador; Sem candidatos $\rightarrow$ manda para o Navegador da Árvore.
   - *Status do usuário:* Entendido e confirmado.

10. **O Identificador (`julgar_coerencia` em `nodes.py`):**
    - *Metáfora:* O aluno que responde à prova de múltipla escolha.
    - *O que faz:* Usa Claude 3.5 Haiku para escolher a melhor opção entre os 15 candidatos oficiais. Dá uma nota de confiança (0 a 100%) conforme a régua do prompt (`v2.md`).
    - *Proteção contra alucinação:* Se a IA sugerir qualquer código fora da lista de candidatos, o código em Python descarta sumariamente a resposta.
    - *Os 5 Alarmes no Python (1 única chamada de IA):* A IA responde a prova uma única vez. O Python confere se toca algum dos 5 alarmes (`baixa_confianca`, `codigo_atual_incoerente`, `sem_codigo_atual_valido`, `divergencia_busca_julgamento`, `sinais_de_duvida`).
    - *Rotas:* Alarme tocou $\rightarrow$ vai ao Segundo Parecer; Marcado que nenhuma opção serve $\rightarrow$ vai ao Navegador da Árvore; Sem alarmes $\rightarrow$ vai direto ao Jurista.
    - *Status do usuário:* Entendido e confirmado.

11. **O Segundo Parecer (`escalar` em `nodes.py`):**
    - *Metáfora:* O professor sênior e independente da banca.
    - *O que faz:* Usa Claude 3.5 Sonnet com prompt próprio (`prompts/escalar/v2.md`). É chamado apenas quando o alarme do novato toca. Revisa a decisão com independência para concordar ou corrigir.
    - *Rotas:* Código escolhido $\rightarrow$ vai ao Jurista; Nenhuma opção serve $\rightarrow$ vai ao Navegador da Árvore.
    - *Status do usuário:* Entendido e confirmado.

12. **O Navegador da Árvore (`navegar_arvore` em `arvore.py`):**
    - *Metáfora:* O explorador guiado pelas placas da floresta.
    - *O que faz:* Resgate para itens sem código. Como o banco de dados tem a tabela NCM estruturada em pastas (`ncm_nodes`), ele faz a IA escolher de placa em placa:
      - Capítulo (Tronco - 2 dígitos, ex: 34 Sabões).
      - Posição (Galho - 4 dígitos, ex: 3401 Sabões para pele).
      - Subposição (Ramo - 6 dígitos, ex: 3401.30 Líquido ou creme).
      - Item final (Folha - 8 dígitos, ex: 3401.30.00).
    - A IA não raciocina pesado nem inventa códigos: apenas escolhe a bifurcação correta.
    - *Rotas:* Código achado $\rightarrow$ vai ao Jurista; Sem código viável $\rightarrow$ vai direto ao Leitor de Fatos.
    - *Status do usuário:* Entendido e confirmado.

13. **O Jurista (`investigar` em `analista.py` e `evidencias.py`):**
    - *Metáfora:* O advogado tributarista da família.
    - *O Segredo de Economia:* Estuda a lei da Reforma Tributária (LC 214/2025) **uma única vez por família (NCM)** e grava na tabela **`tax_theses`** do banco de dados PostgreSQL.
    - *Dados reais do banco do usuário:* O banco real já possui 14 auditorias e 111 teses reais geradas!
    - *A Tese e suas Hipóteses:* Gera de 2 a 4 hipóteses jurídicas escritas com texto completo, condições, explicações e artigos citados. A última hipótese é sempre a "Regra Geral" de tributação integral (`cClassTrib: 000001`).
    - *Trava viva (`trava_viva`):* Se dois operários pegarem itens da mesma família ao mesmo tempo, um tranca a porta para estudar a lei e o outro aguarda para reutilizar de graça.
    - *Status do usuário:* Entendido e confirmado.

14. **O Leitor de Fatos (`levantar_fatos` em `analista.py`):**
    - *Metáfora:* O perito que busca as provas do crime na embalagem do produto.
    - *O que faz:* Pega as condições que as hipóteses do Jurista exigiram (ex: *"é fio dental?", "tem açúcar?", "está na lista do art. 146?"*) e lê a descrição do produto para responder.
    - *Princípio fundamental: Suposição NÃO vira fato:* Se o texto comprova (ex: "FIO DENTAL 50M"), crava o fato oficial (`CompanyFact`). Se a descrição for omissa ou genérica, **a IA não chuta**: marca como "desconhecido".
    - *Perguntas Agrupadas:* Os fatos desconhecidos viram perguntas para o responsável humano responder. Se houver 50 itens com a mesma dúvida, o sistema gera **uma única pergunta para o grupo todo**!
    - *Status do usuário:* Entendido e consolidado!

---

## 3. O PONTO EXATO ONDE ESTAMOS (Para o próximo professor continuar)

O aluno já entendeu perfeitamente o **Leitor de Fatos**. 

O próximo passo obrigatório é apresentar o **décimo quarto agente**:
👉 **O Juiz (`concluir` em `analista.py` / `avaliacao.py`)**.

### O que o próximo professor deve explicar sobre o Juiz:
1. **Quem ele é:** Ele é uma **função matemática pura em Python (sem IA e instantânea)**. Ele pega a Tese do Jurista (com as hipóteses) e coloca os Fatos levantados pelo Leitor em cima da mesa.
2. **Como ele bate o martelo:** Percorre as hipóteses na ordem:
   - Se os fatos cumprem a Hipótese 1 $\rightarrow$ Escolhe a Hipótese 1!
   - Se houver exceção ou fato contrário $\rightarrow$ Descarta a 1 e testa a Hipótese 2.
   - Se faltar um fato decisivo $\rightarrow$ Guarda a dúvida para o Secretário de Perguntas.
   - Se nada especial se aplicar $\rightarrow$ Aplica a Regra Geral (tributação integral).
3. **As 4 Caixas de Confiança / Situações:** O Juiz separa o produto em:
   - *Classificado* (tudo certo, ou a dúvida de NCM não muda o imposto — aí o NCM vai para a lista "Ajustes de cadastro").
   - *Aguardando Informação* (falta responder uma pergunta decisiva, inclusive "o que é este item?" e "a empresa fabrica ou importa?").
   - *Revisão do Contador* (dúvida de NCM que muda o imposto, NCM que a lei cita com outro código).
   - *Revisão do Especialista* (conflitos na lei que nenhum fato resolve).
   - **Novidade de 01–02/10/2026 (ADR 0029):** antes de mandar para uma pessoa, o Juiz pergunta "o imposto muda?". Explique com o exemplo do café: o ERP dizia "café torrado", a primeira IA errou, a segunda concordou com o ERP — dois votos contra um, e todos os cafés da posição 09.01 têm o mesmo imposto. Resultado: classificado, sem incomodar o contador. Ver `docs/DOSSIE_FLUXO_AGENTES.md`, seção 5.10.
4. **O Perfil Tributário Final (`tax_profiles`):** Como o resultado é gravado de forma imutável com CST, cClassTrib e alíquotas.

> **Professor:** Comece acolhendo o aluno, valide que o Leitor de Fatos ficou claro e apresente o **Juiz** com a mesma didática e calma!
