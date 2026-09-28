# Auditor Fiscal de Cadastros — Reforma Tributária (LC 214/2025)

Um **analista fiscal digital** para a Reforma Tributária do consumo. O arquivo do ERP é só o ponto de
partida: para cada item, o sistema reconstrói o raciocínio que um especialista faria para chegar ao
enquadramento válido **numa data de vigência** (inicialmente 2027) e só então o traduz em CST e cClassTrib.

1. **Conhece quem vende** — o dossiê do estabelecimento (segmento, produção própria, refeições...).
2. **Entende o que cada item é** — NCM/NBS conferido contra a tabela oficial; o cadastro antigo é evidência, não verdade.
3. **Investiga a lei uma vez por família** — hipóteses em ordem de precedência, condições, exceções e
   trechos citados da base normativa versionada (LC 214/2025, EC 132/2023, LC 227/2026, Decreto 12.955/2026,
   tabela cClassTrib e correlação oficial).
4. **Aplica aos fatos do item** — fatos com origem (pessoa, ERP, cadastro, texto explícito); suposição da IA
   não vira fato.
5. **Pergunta só o que muda o resultado** — agrupado por empresa, categoria ou NCM; a resposta reclassifica
   os itens na hora, sem novo custo de IA.
6. **Explica a confiança por dimensão** — e separa **Classificado**, **Aguardando informação**,
   **Revisão do contador** e **Revisão do especialista**.
7. **Guarda o dossiê de decisão** — perfil tributário versionado por item, cenário e vigência, auditável meses depois.
8. **Exporta** o cadastro enriquecido, o perfil tributário e a planilha para o ERP.

> As sugestões são apoio à decisão. A classificação final e a responsabilidade técnica são do
> profissional responsável. Itens com confiança alta em todas as dimensões podem ser aprovados
> automaticamente (configurável); os demais só são exportados após aprovação humana.

## Como funciona, em uma página

- **Base normativa e tabelas oficiais, versionadas**: NCM (Siscomex), NBS (MDIC), CST/cClassTrib com a
  correlação oficial (Portal da Conformidade Fácil/SVRS), o texto da LC 214/2025 e os atos da reforma
  importados do Planalto. Cada importação é uma versão nova, com URL, data, hash e responsável; os trechos
  legais têm busca semântica. ([docs/base-de-referencia.md](docs/base-de-referencia.md))
- **Analista por item (LangGraph)**: identificação (busca híbrida + Claude restrito a códigos oficiais +
  segundo parecer) → **investigação jurídica da família** (Claude com pacote de evidências e lista fechada
  de cClassTrib) → fatos do item (modelo leve) → avaliação determinística → perfil tributário e perguntas.
  Checkpoint no PostgreSQL; Batch API para auditorias grandes. ([docs/arquitetura.md](docs/arquitetura.md))
- **Regras curadas são opcionais**: uma regra aprovada vira precedente — aumenta a confiança quando
  confirma a conclusão e aponta conflito quando diverge. Não é mais pré-requisito.
- **Revisão rápida**: tabela virtualizada, perguntas agrupadas, famílias com o raciocínio completo,
  dossiê de decisão por item, fila de revisão por nível, aprovação em lote, desfazer, exportação e PDF.
- **Multi-tenant** com Row-Level Security no PostgreSQL, papéis, log de auditoria imutável.

## Requisitos

- Docker Desktop (ou Docker Engine) com Compose v2. Reserve ~4 GB de RAM para os contêineres
  (o modelo de embeddings padrão usa ~1,5 GB).
- Uma chave da API da Anthropic para a análise por IA (`ANTHROPIC_API_KEY`). Sem ela, tudo funciona,
  exceto iniciar a análise (a interface explica o motivo).
- `make` (Git Bash/WSL no Windows) — opcional; os comandos equivalentes estão no `Makefile`.

## Instalação e primeira execução

```bash
cp .env.example .env          # preencha as senhas, JWT_SECRET e ANTHROPIC_API_KEY
make up                       # sobe db, redis, embeddings, api, worker, beat, flower e frontend
make seed-reference           # importa NCM, NBS, cClassTrib, LC 214 e os atos da reforma (EC 132, LC 227, Decreto 12.955)
make bootstrap                # cria o superadministrador (senha temporária exibida uma vez)
make seed-demo                # (opcional, só em desenvolvimento) organização e empresas fictícias
```

Depois:

1. Entre com o administrador da organização (ou crie uma em **Organizações** como superadministrador),
   cadastre a empresa e preencha o **dossiê do estabelecimento** na página dela.
2. Envie a primeira planilha em **Auditorias → Enviar planilha**, confira o custo estimado e inicie.
3. Responda às **perguntas** agrupadas, revise o que ficou para o contador ou o especialista e exporte.

Portas no host (configuráveis no `.env`): frontend `5180`, API `8100` (`/api/docs`), Flower `5556`,
PostgreSQL `5432` (somente 127.0.0.1).

As planilhas de exemplo (fictícias) estão em `data/samples/` (`make amostras` para regerar).

## Configuração

Todas as variáveis estão documentadas em [.env.example](.env.example). As principais:

| Variável | Para quê |
|---|---|
| `ANTHROPIC_API_KEY` | Chave da API do Claude (somente no servidor). |
| `LLM_MODEL_PRIMARY` / `LLM_MODEL_ESCALATION` / `LLM_MODEL_LIGHT` | Modelos: identificação `claude-haiku-4-5-20251001`; segundo parecer e investigação jurídica `claude-sonnet-5`; fatos da descrição `claude-haiku-4-5-20251001`. Também configuráveis por organização. |
| `LLM_EFFORT_ESCALATION` / `LLM_EFFORT_INVESTIGATION` | Esforço de raciocínio do segundo parecer e da investigação (padrão `medium`; `high` custa mais e pensa mais). |
| `LLM_BATCH_MIN_ITEMS` | A partir de quantos itens com IA a auditoria usa a Batch API (50% mais barata). |
| `EMBEDDINGS_MODEL` / `EMBEDDINGS_DIM` | Modelo local de embeddings. Trocar exige `make migrate` (reindexa sozinho). |
| `UPLOAD_MAX_MB`, `UPLOAD_MAX_ROWS` | Limites de upload. |
| `RETENTION_FILES_DAYS` | Padrão de retenção das planilhas originais (LGPD). |

Limites de confiança, orçamento mensal de IA, modelos e dicionário de abreviações ficam em
**Configurações**, por organização.

## Comandos úteis

```bash
make test            # testes do backend (PostgreSQL real) e do frontend
make e2e             # Playwright (fluxo principal) contra o ambiente em execução
make lint typecheck  # ruff, mypy, eslint, tsc
make eval            # harness de avaliação (chama a API: gera custo) — ver evals/README.md
make backup          # pg_dump em ./backups
make logs S=worker   # logs de um serviço
```

## Solução de problemas

| Sintoma | Causa provável e solução |
|---|---|
| "Base de referência incompleta" em todos os itens | Falta importar uma tabela (NCM/NBS, cClassTrib ou LC 214). Veja Base normativa. |
| Importação da NCM falha com "não é um JSON válido" | O Portal Único Siscomex entra em manutenção. Tente mais tarde ou baixe o JSON e envie pela tela (instruções na própria tela). |
| Contêiner `embeddings` reiniciando (código 137) | Falta de memória. Aumente a memória do Docker ou mantenha o modelo `multilingual-e5-base`. O `bge-m3` precisa de 6 GB+ livres. |
| "A chave da API da Anthropic não está configurada" | Defina `ANTHROPIC_API_KEY` no `.env` e rode `docker compose up -d api worker`. |
| Auditoria "Pausada (orçamento de IA)" | O orçamento mensal da organização foi atingido. Aumente em Configurações e clique em Retomar. |
| Porta já em uso ao subir | Ajuste `API_HOST_PORT`, `FRONTEND_HOST_PORT` etc. no `.env`. |
| Itens parados em "Processando" | O beat reenfileira itens parados a cada 5 minutos; o grafo retoma do checkpoint sem repetir chamadas. |

## Documentação

- [docs/arquitetura.md](docs/arquitetura.md) — arquitetura, pipeline, modelo de dados, isolamento.
- [docs/base-de-referencia.md](docs/base-de-referencia.md) — fontes oficiais e como atualizá-las.
- [docs/design-system.md](docs/design-system.md) — sistema de design “Conferência”.
- [docs/operacao.md](docs/operacao.md) — produção, segurança, LGPD, backups e monitoramento.
- [evals/README.md](evals/README.md) — harness de avaliação e formato do conjunto-ouro.
- [docs/adr/](docs/adr/) — registros de decisões de arquitetura.
