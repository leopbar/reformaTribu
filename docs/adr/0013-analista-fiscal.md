# ADR 0013 — Analista fiscal digital no lugar de "NCM → regra aprovada → cClassTrib"

**Contexto.** O desenho anterior tratava a classificação como conversão de códigos. A IA só conferia o
NCM, e o prompt proibia que considerasse tributação. O enquadramento vinha de um motor de regras por
prefixo de NCM que só funcionava com regras aprovadas uma a uma pelo superadministrador. Sem regras
aprovadas, tudo ia para análise humana. A IA quase nunca classificava. O contexto da operação era um só
por auditoria, e a confiança era um número sem explicação.

**Decisão.** O sistema passa a funcionar como um analista fiscal:

- A unidade de análise é item + empresa + operação + data + condições. A primeira versão cobre o cenário
  "venda ao consumidor"; o perfil tributário (`tax_profiles`) já é por cenário e vigência.
- Dossiê do estabelecimento e **fatos com origem** (`company_facts`). Suposição da IA não vira fato: vira
  sugestão numa pergunta.
- **Tese por família** (`tax_theses`): o modelo de investigação recebe um pacote de evidências
  determinístico e devolve hipóteses em ordem de precedência. Cada hipótese traz condições, exceções e
  citações ao pacote, e a lista de cClassTrib é fechada. A tese é reaproveitada por todos os itens da
  família e em auditorias seguintes (custo proporcional às famílias, não às linhas).
- **Avaliação determinística** dos fatos contra a tese, com **perguntas decisivas** apenas quando as
  alternativas levam a cClassTrib diferentes. As perguntas são agrupadas por empresa, categoria ou
  família, e a resposta reavalia os itens sem IA.
- **Confiança por dimensão** (10 dimensões) e quatro resultados, cada um com o nível de revisão
  correspondente. Aprovação automática opcional para itens com todas as dimensões confirmadas.
- Regras curadas viram **precedentes opcionais**: confirmam (dimensão fonte) ou geram conflito
  (especialista). O detector de divergências lei × tabela continua alimentando a dimensão de conflito.

**Por que não um agente com ferramentas em várias rodadas?** As "ferramentas" (busca na lei,
correlação, tabela cClassTrib, precedentes) são consultas determinísticas feitas antes de uma única
chamada estruturada. Isso mantém a idempotência por chave, a Batch API, o controle de custo e a
reprodutibilidade (o pacote enviado fica gravado na tese). Uma segunda rodada só seria necessária se o
material fosse insuficiente; nesse caso o analista registra o limite em `conflitos` e o item vai ao
especialista.

**Consequências.** O raciocínio fica auditável (dossiê de decisão por item, versões do perfil) e a
revisão humana se concentra no que tem dúvida real. A métrica principal da avaliação passa a ser
"falsos classificados". Os prompts de investigação (`prompts/investigar_enquadramento`) e de fatos
(`prompts/extrair_fatos`) devem ser avaliados com o conjunto-ouro validado antes de mudanças.

**Evolução (2026-09-29 e 2026-09-30).** Decisões que detalham ou revisam partes desta ADR:
[0014](0014-varias-plataformas-de-ia.md) (modelos por agente),
[0015](0015-tese-reaproveitada-pelo-conteudo.md) (chave da tese pelo conteúdo),
[0016](0016-caminho-e-fluxo-dos-agentes.md) (caminho e fluxo dos agentes),
[0017](0017-navegador-da-ncm.md) (Navegador da NCM),
[0018](0018-conflito-so-quando-muda-o-resultado.md) (conflito só quando muda o resultado),
[0019](0019-duvida-que-nao-muda-o-imposto.md) (dúvida imaterial),
[0020](0020-checagem-cruzada-com-os-anexos.md) (anexos da lei),
[0021](0021-revisao-humana-e-reanalise.md) (revisão e reanálise),
[0022](0022-economia-de-ia-e-estimativa.md) (economia),
[0023](0023-robustez-das-chamadas-de-ia.md) (robustez) e
[0024](0024-execucao-paralela-e-recuperacao.md) (execução paralela).
