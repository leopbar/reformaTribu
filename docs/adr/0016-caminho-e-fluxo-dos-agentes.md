# ADR 0016 — Caminho de cada item e fluxo dos agentes, ao vivo

**Status:** aceito · 2026-09-29

## Contexto

O usuário não conseguia entender o que o sistema fazia com cada item. O grafo LangGraph, os nós e as
chamadas de IA eram invisíveis na tela. A explicação que funcionou foi a de um **escritório com
funcionários**: cada caixa do sistema é um "funcionário" com uma tarefa, e alguns usam IA (custam) e
outros seguem regras fixas (grátis).

## Decisão

Duas visões baseadas nessa metáfora, com os mesmos nomes em todas as telas:

- **Planilha inteira:** Recepcionista (lê o arquivo) → Conferente (limpeza e problemas) → Orçamentista
  (prévia de custo) → **Você** (confirma o custo) → Distribuidor (pacotes na fila).
- **Cada item:** Arrumador (normaliza a descrição) → Fiscal da tabela (confere o NCM do ERP) →
  Arquivista (memória aprovada) → Pesquisador (monta a prova de alternativas) → Identificador (IA) →
  Segundo parecer (IA, só com alarme) → Navegador da NCM (IA, só sem código; ADR 0017) → Jurista (IA,
  uma vez por família) → Leitor de fatos (IA) → Juiz (sem IA, boletim de 10 notas) → Secretário
  (perguntas agrupadas).

**Aba "Caminho pelos agentes"** (dentro do detalhe do item). Mostra:

- uma trilha vertical com todas as caixas;
- o trecho percorrido em verde;
- as caixas puladas tracejadas, cada uma com o motivo;
- as caixas com falha em vermelho;
- em cada caixa, o que foi feito ("ver o que fez") e o modelo de IA que respondeu de fato, com o custo.
  Uma resposta reaproveitada aparece como "grátis", e o parecer da família aparece com o custo dividido
  entre os itens.

**Aba "Fluxo dos agentes"** (na auditoria). Mostra todas as caixas com:

- quantos itens passaram;
- quantos estão lá agora, piscando;
- quantas chamadas de IA foram feitas e o custo;
- os atalhos (memória, confirmação sem IA, base incompleta);
- números detalhados ao clicar: alarmes do Segundo parecer, pareceres reaproveitados, fatos lidos,
  palpites;
- onde cada item terminou.

**Ao vivo.** O caminho do item se atualiza a cada 2 s e o fluxo a cada 3 s enquanto há processamento.
Como o item só é gravado no fim, o estado parcial é lido do **checkpoint do LangGraph**
(`grafo().get_state(thread)`).

**Rotas.** A lógica das rotas é uma **função pura** (`caminho.rota`). Ela reproduz as arestas
condicionais do grafo: se o grafo muda, esse módulo muda junto e os testes acusam a diferença.

**Contagens.** São calculadas direto nos itens (status e etapa), sem usar os contadores guardados da
auditoria, que ficavam desatualizados.

## Consequências

- Explica o sistema para quem não é técnico e ajuda a depurar: foi por essa tela que se viu, por
  exemplo, o Segundo parecer em GPT-5 levando mais de 3 minutos por item.
- O vocabulário dos funcionários passa a ser o da interface e o da documentação.
- Há acoplamento consciente entre `caminho.py` e `graph.py`, protegido por testes.

## Onde está no código

- `backend/app/analise/caminho.py`: `Registro`, `rota`, `montar`.
- `backend/app/api/fluxo.py`: `/itens/{id}/caminho` e `/auditorias/{id}/fluxo`.
- `frontend/src/features/auditorias/FluxoAgentes.tsx`: `CaminhoItem`, `FluxoAuditoria`, `AGENTES`.

## Verificação

- `backend/tests/test_caminho.py` (rotas: simples, com alarme, memória, sem candidatos, resposta
  descartada, base incompleta, perguntas, em andamento, Navegador).
