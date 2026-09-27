# ADR 0010 — Cliente do frontend gerado do OpenAPI

**Decisão.** `openapi-typescript` gera `src/api/schema.d.ts`; `openapi-fetch` faz as chamadas tipadas.
`make api-gen` regenera. Frontend e backend não ficam dessincronizados sem erro de compilação.
