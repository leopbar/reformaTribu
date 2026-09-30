# Auditor Fiscal de Cadastros — comandos principais.
# Requer Docker (Compose v2). No Windows, rode pelo Git Bash ou WSL.

COMPOSE ?= docker compose
PROD = $(COMPOSE) -f compose.yaml -f compose.prod.yaml
API = $(COMPOSE) exec api
CONJUNTO ?= /evals/conjunto_ouro/exemplo_nao_validado.csv
CONFIGS ?= padrao

.PHONY: help up down logs ps migrate bootstrap seed-reference seed-dicionario seed-demo indexar amostras \
        test test-backend test-frontend e2e lint typecheck eval eval-baseline eval-regressao api-gen \
        prod-build prod-up prod-down backup restore

help:  ## Lista os comandos
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-18s %s\n", $$1, $$2}'

up:  ## Sobe o ambiente de desenvolvimento completo (hot reload)
	$(COMPOSE) up -d --build
	@echo "Frontend: http://localhost:$${FRONTEND_HOST_PORT:-5180}   API: http://localhost:$${API_HOST_PORT:-8100}/api/docs"

down:  ## Para os serviços (os volumes são mantidos)
	$(COMPOSE) down

logs:  ## Acompanha os logs (ex.: make logs S=worker)
	$(COMPOSE) logs -f --tail 100 $(S)

ps:
	$(COMPOSE) ps

migrate:  ## Aplica as migrações e prepara o checkpoint do LangGraph
	$(API) python -m app.cli migrate

bootstrap:  ## Cria o primeiro superadministrador (BOOTSTRAP_ADMIN_EMAIL no .env)
	$(API) python -m app.cli bootstrap-admin

seed-reference:  ## Importa as fontes oficiais (NCM, NBS, cClassTrib, LC 214, atos da reforma) e o dicionário
	$(API) python -m app.cli seed-dicionario
	$(API) python -m app.cli seed-reference
	$(API) python -m app.cli seed-normas

seed-dicionario:
	$(API) python -m app.cli seed-dicionario

indexar:  ## Gera os embeddings pendentes (síncrono)
	$(API) python -m app.cli indexar-embeddings

seed-demo:  ## Organização, empresas e usuários fictícios (somente desenvolvimento)
	$(API) python -m app.cli seed-demo

amostras:  ## Regera as planilhas de exemplo em data/samples
	cd backend && uv run python ../data/samples/gerar_amostras.py

test: test-backend test-frontend  ## Roda todos os testes automatizados

test-backend:  ## Testes do backend (PostgreSQL real, banco *_test)
	$(API) python -m pytest -q -p no:cacheprovider --cov=app --cov-report=term-missing:skip-covered

test-frontend:  ## Testes unitários do frontend (Vitest)
	$(COMPOSE) exec frontend npm test

e2e:  ## Testes de ponta a ponta (Playwright) contra o ambiente em execução
	cd frontend && npx playwright test

lint:  ## ruff + eslint
	$(API) ruff check app tests migrations
	$(API) ruff format --check app tests
	$(COMPOSE) exec frontend npm run lint

typecheck:  ## mypy (estrito) + tsc
	$(API) mypy app
	$(COMPOSE) exec frontend npm run typecheck

eval:  ## Harness de avaliação (CHAMA A API DO CLAUDE: gera custo)
	$(API) python -m app.evals.runner --conjunto $(CONJUNTO) $(foreach c,$(CONFIGS),--config /evals/configs/$(c).yaml)

eval-baseline:  ## Grava a linha de base (configuração padrão)
	$(API) python -m app.evals.runner --conjunto $(CONJUNTO) --config /evals/configs/padrao.yaml \
		--baseline /evals/baseline.json --atualizar-baseline

eval-regressao:  ## Falha se a taxa de falsos confirmados piorar em relação à linha de base
	$(API) python -m app.evals.runner --conjunto $(CONJUNTO) --config /evals/configs/padrao.yaml \
		--baseline /evals/baseline.json

api-gen:  ## Regera o cliente TypeScript a partir do OpenAPI
	cd frontend && API_URL=http://localhost:$${API_HOST_PORT:-8100} npm run api:gen

prod-build:  ## Constrói as imagens de produção
	$(PROD) build

prod-up:  ## Sobe o perfil de produção
	$(PROD) up -d

prod-down:
	$(PROD) down

backup:  ## Backup do banco em ./backups (pg_dump formato custom)
	@mkdir -p backups
	$(COMPOSE) exec -T db sh -c 'pg_dump -U $$POSTGRES_USER -d $$POSTGRES_DB -Fc' > backups/reforma-$$(date +%Y%m%d-%H%M%S).dump
	@ls -1t backups | head -3

restore:  ## Restaura um backup: make restore ARQUIVO=backups/xxx.dump
	@test -n "$(ARQUIVO)" || (echo "Informe ARQUIVO=backups/arquivo.dump" && exit 1)
	$(COMPOSE) exec -T db sh -c 'pg_restore -U $$POSTGRES_USER -d $$POSTGRES_DB --clean --if-exists' < $(ARQUIVO)
