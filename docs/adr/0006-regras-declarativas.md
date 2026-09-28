# ADR 0006 — Regras declarativas geradas das fontes oficiais, aprovadas por humano

> **Revista pela [ADR 0013](0013-analista-fiscal.md)**: regras aprovadas deixaram de ser pré-requisito e viraram precedentes opcionais.

**Decisão.** Nenhuma regra legal no código. As regras (abrangência por prefixo de código, exceções,
condições com fonte item/empresa/operação, CST/cClassTrib, vigência) são geradas da correlação oficial
publicada com a tabela cClassTrib e do texto da LC 214, validadas contra as tabelas e aprovadas por um
superadministrador. A extração de condições por IA é só sugestão. Novas versões nunca sobrescrevem;
a aprovada vale até a nova ser aprovada.

**Consequências.** Sem regras aprovadas, tudo vai para análise humana. Anexos sem cClassTrib único
(ex.: medicamentos, Anexo XIV) exigem decisão explícita do superadministrador.
