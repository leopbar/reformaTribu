# Operação, segurança e LGPD

## Produção

```bash
cp .env.example .env    # APP_ENV=producao, COOKIE_SECURE=true, CORS_ORIGINS=["https://seu.dominio"], senhas fortes
make prod-build
make prod-up            # db, redis, embeddings, api, worker, beat e frontend (Nginx na porta HTTP_PORT)
make bootstrap && make seed-reference
```

- Coloque um proxy TLS (Caddy, Traefik, balanceador da nuvem) na frente do `frontend` (porta 8080). O
  Nginx do frontend faz proxy de `/api` para a API e desliga o buffer para SSE.
- Imagens multi-stage, usuário não-root, sem código montado, healthchecks em todos os serviços.
- Portas do banco, Redis e API não são expostas no perfil de produção.
- Flower só sobe com `--profile monitoramento` e deve ter `FLOWER_BASIC_AUTH`.
- Documentação interativa da API (`/api/docs`) fica desligada em produção.

## Segurança

| Tema | Implementação |
|---|---|
| Isolamento | RLS no PostgreSQL (papel sem `BYPASSRLS`), filtro na aplicação, testes automatizados. |
| Senhas | Argon2id; mínimo de 12 caracteres com três classes; rehash automático. |
| Sessão | JWT de acesso de 15 min em memória no navegador; refresh token opaco em cookie `httpOnly`, `SameSite=Strict`, rotação a cada uso e revogação da família em caso de reuso. |
| CSRF | Cookie `csrf_token` + cabeçalho `X-CSRF-Token` (double submit) nas rotas que usam o cookie. |
| Força bruta | Bloqueio por e-mail e por IP após tentativas (Redis) e limitação de taxa global. |
| Cabeçalhos | `nosniff`, `X-Frame-Options: DENY`, CSP, `Referrer-Policy`, `Permissions-Policy`, HSTS em produção. |
| CORS | Somente as origens de `CORS_ORIGINS`. |
| Uploads | Tipo real pela assinatura; macros (VBA) recusadas; limite de tamanho e de linhas. |
| Segredos | Apenas variáveis de ambiente; a chave da Anthropic nunca chega ao navegador. |
| Logs | JSON estruturado com `request_id`; chaves sensíveis mascaradas; descrições de itens não são registradas. |
| Log de auditoria | Somente inserção, encadeado por hash; login, upload, aprovação, edição, exportação, configuração, base de referência. |

## LGPD

- **Minimização**: ao modelo vão apenas descrição, códigos e atributos do item — nunca dados pessoais,
  clientes finais ou a planilha inteira.
- **Retenção**: as planilhas originais são apagadas após `retencao_arquivos_dias` (por organização;
  tarefa diária `manutencao.expurgar_arquivos`), mantendo os itens auditados.
- **Portabilidade**: Configurações → Dados da organização → "Gerar pacote de dados" (JSON por tabela).
- **Exclusão**: o superadministrador exclui a organização (`DELETE /api/plataforma/organizacoes/{id}`
  com confirmação do nome); os dados em cascata são removidos. O log de auditoria da plataforma registra
  a exclusão.

## Backups

```bash
make backup                               # pg_dump -Fc em ./backups
make restore ARQUIVO=backups/xxx.dump     # restauração
```

Agende `make backup` (cron/systemd) e copie `./backups` e o volume `storage` para outro local. Os
volumes persistentes são `pgdata`, `storage`, `redisdata` e `embeddings_cache` (este é só cache).

## Monitoramento

- `GET /api/saude` (banco e Redis) — usado pelos healthchecks.
- Flower (`/flower`) para filas e tarefas.
- Custos de IA por chamada, item, auditoria e organização em `llm_calls`; orçamento mensal com alerta
  (notificação) e bloqueio (auditoria pausada).
- Logs JSON prontos para agregadores (Loki, CloudWatch, Datadog).

## Atualizações de modelo

Os modelos são configuráveis por variável de ambiente e por organização. Antes de trocar o padrão,
rode `make eval` com as duas configurações e compare a taxa de falsos confirmados
([evals/README.md](../evals/README.md)). Preços em `backend/app/llm/pricing.py` (conferidos em
26/09/2026 — revise ao trocar de modelo).
