# Registro de decisões de arquitetura (ADR)

Cada ADR registra uma decisão: o contexto, o que foi decidido, as alternativas e as consequências.
Uma decisão revista não é apagada: a ADR antiga recebe um aviso apontando para a nova.

## Fundação (2026-09-26)

| ADR | Decisão | Status |
|---|---|---|
| [0001](0001-monorepo-backend-unico.md) | Monorepo e um único código de backend (API, worker e agendador) | aceito |
| [0002](0002-celery-redis.md) | Celery + Redis para filas e agendamentos | aceito |
| [0003](0003-embeddings-locais.md) | Embeddings locais (TEI, multilingual-e5-base) para a busca | aceito |
| [0004](0004-rls.md) | Isolamento entre organizações com Row-Level Security | aceito |
| [0005](0005-snapshots-da-base.md) | Snapshots imutáveis da base de referência por auditoria | aceito |
| [0006](0006-regras-declarativas.md) | Regras declarativas aprovadas por humano | revista pela 0013 |
| [0007](0007-batch-api-com-interrupt.md) | Batch API com `interrupt()` do LangGraph | aceito |
| [0008](0008-portoes-e-confianca.md) | Portões rígidos antes da confiança numérica | substituída pela 0013 |
| [0009](0009-sse.md) | Progresso ao vivo por SSE | aceito |
| [0010](0010-cliente-openapi.md) | Cliente do frontend gerado do OpenAPI | aceito |
| [0011](0011-versoes-fixadas.md) | Versões de dependências fixadas | aceito |
| [0012](0012-sonnet-sem-temperatura.md) | Modelos sem parâmetro de temperatura | aceito |

## Analista fiscal digital (2026-09-28 a 2026-09-30)

| ADR | Decisão | Status |
|---|---|---|
| [0013](0013-analista-fiscal.md) | Analista fiscal: dossiê, fatos com origem, tese por família, perguntas decisivas, confiança por dimensão | aceito |
| [0014](0014-varias-plataformas-de-ia.md) | Várias plataformas de IA (Anthropic, OpenAI, DeepSeek), modelo por agente, chaves cifradas | aceito |
| [0015](0015-tese-reaproveitada-pelo-conteudo.md) | Tese reaproveitada pelo conteúdo do material jurídico; "refazer com o modelo atual" | aceito |
| [0016](0016-caminho-e-fluxo-dos-agentes.md) | Caminho de cada item e fluxo dos agentes, ao vivo (metáfora dos funcionários) | aceito |
| [0017](0017-navegador-da-ncm.md) | Navegador da NCM: busca guiada pela árvore oficial; NCM do ERP como referência | aceito |
| [0018](0018-conflito-so-quando-muda-o-resultado.md) | Conflito normativo só quando muda o cClassTrib | aceito |
| [0019](0019-duvida-que-nao-muda-o-imposto.md) | Dúvida de identificação que não muda o imposto (com condições de segurança) | aceito |
| [0020](0020-checagem-cruzada-com-os-anexos.md) | Checagem cruzada com os anexos da lei e código da lei na prova | aceito |
| [0021](0021-revisao-humana-e-reanalise.md) | Revisão humana: resultado × decisão, motivo da revisão, reanálise em lote | aceito |
| [0022](0022-economia-de-ia-e-estimativa.md) | Economia de IA e estimativa de custo calibrada | aceito |
| [0023](0023-robustez-das-chamadas-de-ia.md) | Robustez das chamadas de IA entre plataformas | aceito |
| [0024](0024-execucao-paralela-e-recuperacao.md) | Execução em pacotes, paralelismo e recuperação de itens travados | aceito, melhorias pendentes |
| [0025](0025-reanalise-acompanhada-ao-vivo.md) | Reanálise acompanhada ao vivo: faixa, ações bloqueadas, lista e caminho sem F5 | aceito |
| [0026](0026-regimes-decididos-pela-operacao.md) | Regimes decididos pela operação (bares e restaurantes, manipulação), valem sem NCM; resposta em grupo só para os itens listados | aceito |
| [0027](0027-beneficios-pela-natureza-do-produto.md) | Benefícios pela natureza do produto sem lista de NCM (medicamentos, in natura, livros); marca que é o produto fica; tipo do ERP | aceito |

## Mapa rápido: os agentes e as ADRs

| Agente (caixa na tela) | Usa IA? | Onde está decidido |
|---|---|---|
| Recepcionista, Conferente, Orçamentista, Distribuidor | não | 0013, 0022, 0024 |
| Arrumador, Fiscal da tabela, Arquivista | não (Arrumador opcional) | 0013, 0022 |
| Pesquisador (monta a prova) | não | 0003, 0017, 0020, 0027 |
| Identificador | sim | 0013, 0014, 0019, 0020 |
| Segundo parecer | sim, só com alarme | 0013, 0014, 0019 |
| Navegador da NCM | sim, só sem código | 0017 |
| Jurista (tese da família) | sim, uma vez por família | 0013, 0015, 0018, 0026, 0027 |
| Leitor de fatos | sim | 0013, 0023, 0026 |
| Juiz (boletim de 10 notas) | não | 0013, 0018, 0019, 0020, 0026 |
| Secretário (perguntas) | não | 0013, 0021, 0026 |
