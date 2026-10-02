# Harness de avaliação

## Medição sem IA (ADR 0029)

Antes de mudar uma regra de decisão, meça sem custo quantos itens iriam para uma pessoa e se algum sairia
classificado sozinho com resultado diferente do que uma pessoa decidiu:

```bash
docker compose exec api python -m app.evals.replay --saida /evals/reports
docker compose exec api python -m app.evals.replay --gabarito /evals/conjunto_ouro/decisoes_humanas.local.csv
```

A medição refaz a identidade e a avaliação dos itens já analisados a partir das respostas da IA gravadas,
com o código atual, e não grava nada. O relatório lista os itens que mudam e os que ainda vão para uma
pessoa. **Falsos automáticos** tem de ficar em zero (o comando termina com código 1 se não ficar). O
gabarito exportado tem as decisões de pessoas no formato abaixo; o arquivo `*.local.csv` fica fora do Git
porque traz itens reais.

## Harness com a IA (gera custo)

Mede a qualidade do pipeline **real** (API do Claude, busca híbrida e motor de regras sobre a base de
referência vigente) num conjunto-ouro, e compara configurações de modelos e versões de prompt.

```bash
make eval                                   # configuração padrão, conjunto de exemplo
make eval CONJUNTO=/evals/conjunto_ouro/meu_conjunto.csv CONFIGS="padrao sonnet-esforco-alto"
make eval-baseline                           # grava a linha de base a partir da configuração padrão
```

Cada execução chama a API do Claude e **gera custo**. O relatório (Markdown e HTML) é salvo em
`evals/reports/`.

## Formato do conjunto-ouro

CSV UTF-8 com separador `;`. Linhas iniciadas por `#` são comentários.

| Coluna | Obrigatória | Conteúdo |
|---|---|---|
| `id` | sim | identificador único do caso |
| `descricao` | sim | descrição como viria do cadastro do cliente |
| `ncm_informado` / `nbs_informado` | não | código cadastrado hoje (pode estar errado de propósito) |
| `tipo` | não | `produto` ou `servico` |
| `esperado_tipo_codigo` | sim | `ncm` ou `nbs` |
| `esperado_codigo` | sim* | código correto, só dígitos (*vazio quando o correto é análise humana sem código) |
| `esperado_cst` / `esperado_cclasstrib` | não | enquadramento correto na data de referência |
| `esperado_status` | não | `classificado`, `aguardando_informacao`, `revisao_contador` ou `revisao_especialista` |
| `fatos` | não | fatos do item informados antes da análise, como um operador faria: `adicao_acucar=nao;produzido_na_loja=sim` |
| `validado_por` | sim para uso real | nome e registro (CRC) do contador que validou o caso |
| `observacao` | não | justificativa ou fonte |

**O conjunto só tem valor se validado por um contador.** O arquivo `exemplo_nao_validado.csv` é
ilustrativo: as respostas foram escritas para testar o harness e não são verdade.

## Métricas

- acerto do NCM em 8 dígitos e em 4 dígitos (posição); acerto do cClassTrib;
- **taxa de falsos classificados** (itens dados como Classificado — confiança alta em todas as dimensões, elegíveis para aprovação automática — com NCM ou cClassTrib errado) — a principal;
- taxas de classificados, aguardando informação e revisão; taxa de escalonamento; custo e tempo médios por item;
- erros por nível de confiança (alta, média, incompleta, baixa): erros devem se concentrar fora da confiança alta.

## Regressão

`make eval-regressao` compara com `evals/baseline.json` e falha (código 1) se a taxa de falsos
classificados piorar. Nenhuma mudança de prompt ou de regra deve entrar nessa situação.
