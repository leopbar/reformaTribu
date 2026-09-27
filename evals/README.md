# Harness de avaliação

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
| `esperado_status` | não | `confirmado`, `corrigido` ou `analise_humana` |
| `validado_por` | sim para uso real | nome e registro (CRC) do contador que validou o caso |
| `observacao` | não | justificativa ou fonte |

**O conjunto só tem valor se validado por um contador.** O arquivo `exemplo_nao_validado.csv` é
ilustrativo: as respostas foram escritas para testar o harness e não são verdade.

## Métricas

- acerto do NCM em 8 dígitos e em 4 dígitos (posição); acerto do cClassTrib;
- **taxa de falsos confirmados** (itens marcados como Confirmado que estavam errados) — a principal;
- falsos corrigidos, taxa de análise humana, taxa de escalonamento, custo e tempo médios por item;
- curva de calibração: cobertura × falsos confirmados para limiares de 0,80 a 0,99.

## Regressão

`make eval-regressao` compara com `evals/baseline.json` e falha (código 1) se a taxa de falsos
confirmados piorar. Nenhuma mudança de prompt ou de regra deve entrar nessa situação.
