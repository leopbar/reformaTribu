# ADR 0022 — Economia de IA e estimativa de custo calibrada

**Status:** aceito · 2026-09-30

## Contexto

O custo por planilha era a principal preocupação do usuário. Na primeira planilha real (50 itens, 42 a
47 NCMs diferentes) foram gastos US$ 2,55, e a estimativa mostrada tinha sido de US$ 8,36. A divisão do
custo real foi:

| Etapa | Custo | Parte |
|---|---|---|
| Jurista | US$ 1,76 | 69% |
| Segundo parecer | US$ 0,43 | 17% |
| Identificador | US$ 0,35 | 14% |
| Leitor de fatos | desprezível | — |

A estimativa também supunha que 60% dos NCMs do ERP seriam confirmados sem IA. Na prática, foram 0%,
porque a busca é fraca e o atalho exige o 1º lugar nas duas buscas.

## Decisão

- **Reaproveitamento em quatro níveis:**
  1. **Memória aprovada:** item aprovado por pessoa pula a identificação nas próximas planilhas da
     empresa.
  2. **Chamada idêntica:** a chave de idempotência é o conteúdo (descrição sem marca e GTIN, alternativas,
     modelo, prompt). Itens iguais, na mesma ou em outra auditoria da organização, reusam a resposta.
  3. **Tese por família**, pelo conteúdo do material jurídico (ADR 0015).
  4. **Perguntas por grupo:** a resposta vira fato e vale para as próximas planilhas.
- **Modelos por agente** (ADR 0014): modelos baratos para tarefas simples; o Sonnet ou equivalente para
  o Jurista.
- **Estimativa por agente:**
  - a prévia mostra o custo de cada agente com o modelo escolhido **hoje**;
  - enquanto a auditoria não começa, ela é recalculada sempre que a auditoria é aberta;
  - o lote (−50%) só vale para modelos com Batch API (Anthropic);
  - a DeepSeek entra pelo preço de pico;
  - a estimativa inclui o Navegador (cerca de 3 chamadas por item sem código).
- **Taxas calibradas no piloto:**
  - confirmação sem IA: de 60% para **10%**;
  - segundo parecer (padrão quando há menos de 50 chamadas de histórico): de 20% para **40%**.

## Consequências

- Na segunda planilha, 5 das 7 famílias usaram pareceres existentes. Uma planilha de 10 itens custou
  US$ 0,17 com DeepSeek e OpenAI.
- A estimativa ficou mais próxima do real, mas ainda não desconta itens repetidos que nunca foram
  aprovados.
- Limite conhecido: a qualidade da busca (embeddings locais pequenos) mantém o atalho "sem IA" quase sem
  uso. Melhorar a busca (limpar peso e volume da consulta, modelo de embedding maior, reranqueador,
  dicionário de nomes comerciais) foi proposto e ainda não foi feito.

## Onde está no código

- `backend/app/ingest/estimate.py`: `estimar`, `estimativas`, taxas.
- `backend/app/api/audits.py`: `estimativa_atual`.
- `backend/app/pipeline/nodes.py`: `chave_conteudo`.
- `backend/app/llm/gateway.py`: `resultado_existente`.
