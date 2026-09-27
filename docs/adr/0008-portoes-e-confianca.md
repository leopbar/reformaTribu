# ADR 0008 — Portões rígidos antes da confiança numérica

**Decisão.** Motivos bloqueantes (condição não verificável, divergência entre modelos, regra pendente,
código inválido, base incompleta, descrição insuficiente...) levam à análise humana antes de qualquer
cálculo. A confiança final combina sinais (modelo, busca, concordância, regra, descrição, estrutura) com
pesos em `calibracao.json`; mudança de código exige concordância do segundo parecer.

**Consequências.** Mais itens em análise humana em troca de menos falsos confirmados — a métrica
principal. Os pesos devem ser recalibrados com o conjunto-ouro validado.
