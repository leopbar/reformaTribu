# ADR 0005 — Snapshot imutável da base de referência por auditoria

**Decisão.** Ao iniciar uma auditoria, grava-se (ou reutiliza-se, por hash) um `ref_snapshot` com as
versões ativas de cada fonte, as regras aprovadas e as pendentes. Todo o processamento e as revisões
daquela auditoria usam esse snapshot.

**Consequências.** Rastreabilidade com um identificador; reprocessamentos reprodutíveis; atualizações
da base não mudam auditorias em andamento.
