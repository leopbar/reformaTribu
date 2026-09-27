# ADR 0012 — "Temperatura baixa" com os modelos atuais

**Contexto.** O documento do projeto pede temperatura baixa. Nos modelos Claude Sonnet 5 e Opus 5.5 os
parâmetros de amostragem (`temperature`, `top_p`) foram removidos da API (retornam erro 400), e o
raciocínio adaptativo não pode ser desligado no Opus 5.5.

**Decisão.** Determinismo e controle vêm de: saídas estruturadas (`output_config.format` com JSON
Schema), escolha restrita a uma lista fechada de candidatos, validação contra o banco, esforço
configurável (`effort`) e prompts versionados. Os modelos continuam configuráveis.
