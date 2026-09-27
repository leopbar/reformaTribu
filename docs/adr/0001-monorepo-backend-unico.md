# ADR 0001 — Monorepo e um único código de backend

**Status:** aceito · 2026-09-26

**Contexto.** API, worker e agendador compartilham modelos, regras e migrações.

**Decisão.** Monorepo (`backend/`, `frontend/`, `infra/`, `data/`, `evals/`, `docs/`). O mesmo pacote
Python roda como API (uvicorn), worker e beat (Celery), com comandos diferentes na mesma imagem.

**Consequências.** Uma só fonte de verdade para domínio e esquema; deploy simples. As dependências de
worker (LangGraph, WeasyPrint) também estão na imagem da API — aceitável pelo tamanho.
