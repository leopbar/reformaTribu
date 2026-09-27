# Auditor Fiscal de Cadastros — Reforma Tributária (LC 214/2025)

Sistema que audita cadastros de produtos e serviços para a Reforma Tributária do consumo. Para cada
item da planilha de uma empresa, ele:

1. confere se o **NCM** (produtos) ou a **NBS** (serviços) combina com a descrição real do item;
2. verifica o **enquadramento na LC 214/2025** (anexos com alíquota zero ou reduzida, condições e exceções);
3. sugere o **CST do IBS/CBS** e o **cClassTrib**, com o dispositivo legal e a confiança;
4. classifica o item em **Confirmado**, **Corrigido** ou **Análise humana**;
5. permite que o contador **revise, aprove, altere e exporte** o resultado.

> As sugestões são apoio à decisão. A classificação final e a responsabilidade técnica são do
> profissional responsável. Nada é exportado como final sem aprovação humana.

## Como funciona, em uma página

- **Base de referência oficial, versionada**: tabelas NCM (Siscomex), NBS (MDIC), CST/cClassTrib com a
  correlação oficial dos anexos (Portal da Conformidade Fácil/SVRS) e o texto da LC 214/2025
  (Planalto). Cada importação é uma versão nova, com URL, data, hash e responsável.
  ([docs/base-de-referencia.md](docs/base-de-referencia.md))
- **Regras declarativas**: os anexos viram regras (abrangência por código, exceções, condições,
  CST/cClassTrib), geradas das fontes oficiais, validadas contra as tabelas e **aprovadas por um
  superadministrador** comparando com o texto legal. Regras pendentes não são usadas.
- **Pipeline por item (LangGraph)**: normalização → validação estrutural → memória aprovada → busca
  híbrida (pgvector + texto em português) → julgamento pelo Claude (só pode escolher entre os códigos
  candidatos da tabela oficial) → segundo parecer quando há dúvida → motor de regras → decisão com
  confiança calibrada. Checkpoint no PostgreSQL; Batch API para auditorias grandes.
  ([docs/arquitetura.md](docs/arquitetura.md))
- **Revisão rápida**: tabela virtualizada, painel de detalhe com a "régua de conferência", fila de
  revisão por teclado, aprovação em lote com confirmação, desfazer, exportação XLSX/CSV e relatório PDF.
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
make seed-reference           # importa NCM, NBS, cClassTrib e LC 214 (gera as regras como PENDENTES)
make bootstrap                # cria o superadministrador (senha temporária exibida uma vez)
make seed-demo                # (opcional, só em desenvolvimento) organização e empresas fictícias
```

Depois:

1. Entre como superadministrador em http://localhost:5180 → **Base de referência → Revisar regras
   legais**. Revise e aprove as regras (texto legal lado a lado). **Sem regras aprovadas, todos os itens
   vão para análise humana** — de propósito.
2. Crie uma organização em **Organizações** (ou use a de demonstração), entre com o administrador dela,
   cadastre empresas e envie a primeira planilha.

Portas no host (configuráveis no `.env`): frontend `5180`, API `8100` (`/api/docs`), Flower `5556`,
PostgreSQL `5432` (somente 127.0.0.1).

As planilhas de exemplo (fictícias) estão em `data/samples/` (`make amostras` para regerar).

## Configuração

Todas as variáveis estão documentadas em [.env.example](.env.example). As principais:

| Variável | Para quê |
|---|---|
| `ANTHROPIC_API_KEY` | Chave da API do Claude (somente no servidor). |
| `LLM_MODEL_PRIMARY` / `LLM_MODEL_ESCALATION` / `LLM_MODEL_LIGHT` | Modelos (padrão `claude-sonnet-5`, `claude-opus-5-5`, `claude-haiku-4-5-20251001`). Também configuráveis por organização. |
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
| "Base de referência incompleta" em todos os itens | Falta importar uma tabela ou **aprovar as regras**. Veja Base de referência. |
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
