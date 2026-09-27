# ADR 0011 — Versões fixadas e exceções à "última versão"

**Decisão.** Todas as dependências estão fixadas (`pyproject.toml` com `==` + `uv.lock`; `package.json`
com versões exatas + `package-lock.json`). Exceções deliberadas à regra da versão mais recente:

- **TypeScript 5.9.3** (não 7.x/6.x): `openapi-typescript` e `typescript-eslint` ainda exigem `<6`.
- **@tanstack/react-table 8.21.3** (não 9.x): a v9 mudou a API; a v8 é estável e conhecida.
- Gráficos do resumo feitos com elementos HTML/SVG simples, sem biblioteca (a mais leve possível).
