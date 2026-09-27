# Sistema de design "Conferência"

O produto é usado por contadores que conferem milhares de itens. A identidade vem do próprio ato de
**conferir um documento oficial**: papel, tinta, régua e a caneta do revisor. A ousadia visual está num
único ponto — a **régua de conferência** — e o resto é disciplinado.

## Paleta

| Nome | Claro | Escuro | Uso |
|---|---|---|---|
| Papel | `#F4F5F2` | `#0E1319` | fundo da página (cinza frio levemente esverdeado, não creme) |
| Superfície | `#FFFFFF` | `#151C25` | painéis e tabelas |
| Tinta | `#17202E` | `#E8EBEF` | texto e ações primárias |
| Régua | `#D6DAD3` | `#2A3441` | linhas e bordas finas |
| **Conferido** | `#0C6F5C` | `#4FC9A8` | status Confirmado (verde azulado) |
| **Caneta** | `#2343B5` | `#8AA4FF` | status Corrigido e marcas de correção (azul de caneta esferográfica) |
| **Ocre** | `#A44D06` | `#F0A45B` | status Análise humana e trechos divergentes |
| Perigo | `#B42318` | `#FF8A80` | ações destrutivas e erros |

Os três status usam matizes separados em luminância e tom (seguro para daltonismo) e **nunca aparecem
só por cor**: sempre ícone + texto (`CheckCircle2` Confirmado, `PenLine` Corrigido, `AlertTriangle`
Análise humana). Contraste de texto ≥ 4,5:1 nos dois temas.

## Tipografia

- **IBM Plex Sans** (interface) e **IBM Plex Mono** (códigos, números). Plex tem o desenho "de
  engenharia" que combina com documentos técnicos, e números tabulares em ambas.
- Escala (razão ~1,2): 12 · 13 · 14 · 16 · 19 · 23 · 28 px. Corpo em 14 px.
- Códigos sempre formatados e em mono (`3401.11.90`, `1.0101.11.00`); valores com `tabular-nums`.
- Sem rótulos em caixa alta com espaçamento largo acima de títulos.

## Layout

```
┌──────────┬─────────────────────────────────────────────────────────────┐
│ ▤ Auditor│ Organização ▾            [Buscar ou ir para…  Ctrl K]  🔔 ☾ 👤│
│  Fiscal  ├─────────────────────────────────────────────────────────────┤
│ Painel   │ Carteira de clientes                     [Enviar planilha]  │
│ Auditorias│ ┌Empresas 4┐┌Para revisar 1.240┐┌Análise humana 212┐┌IA mês┐│
│ Empresas │ │          ││                  ││                  ││      ││
│ Atividade│ Empresas ───────────────────────────────────────────────── │
│ Config.  │ Razão social      Última auditoria  Para revisar  Análise   │
│          │ Mercado X  11.222… 26/09/2026        1.030          188  → │
│ aviso de │                                                             │
│ responsab│                                                             │
└──────────┴─────────────────────────────────────────────────────────────┘

Resultado da auditoria (tabela virtualizada + painel lateral de detalhe)
┌──────────────────────────────────────────────┬──────────────────────────┐
│ [Confirmado 2.310] [Corrigido 418] [Análise 212]│ ● Corrigido  Aguardando  │
│ Busca [___]  Motivo ▾ Confiança ▾ Anexo ▾ ...│ SAB LIQ ERVA DOCE 250ML  │
│ Linha Cód  Descrição        Atual     Sugerido│ ┌ Cap │Pos│Subp│Item ┐  │
│ 12    1041 SAB LIQ ERVA…    3401.11.90 3401.30│ │ 34  │01 │ 1̶1̶  │ 9̶0̶  │  │
│ 13    1042 LEITE UHT…       0401.20.10 ✓      │ │ 34  │01 │ 30 │ 00  │  │
│ ...  (50 mil linhas, rolagem virtual)          │ └diverge na subposição┘  │
│                                               │ Enquadramento · Lei ·    │
│ ↑↓ navegar · Enter abrir                      │ [Aprovar A][Editar E][R] │
└──────────────────────────────────────────────┴──────────────────────────┘

Fila de revisão focada (somente teclado)
┌──────────────┬───────────────────────────────────────────────────────────┐
│ 1 ▲ SUCO UVA │  Perguntas: "O suco tem adição de açúcar?" [Sim] [Não]      │
│ 2 ✎ SAB LIQ  │  Régua de conferência · trecho da lei · confiança         │
│ 3 ✓ ARROZ    │  [Aprovar A] [Editar E] [Rejeitar R] [Desfazer U]  J/K ↕  │
└──────────────┴───────────────────────────────────────────────────────────┘
```

- Navegação lateral fixa, barra de contexto no topo (organização) e paleta de comandos (`Ctrl+K`).
- Painéis com borda fina (régua), sem sombra padrão; sombra só em camadas flutuantes.
- Desktop primeiro; acompanhamento, painel e relatórios funcionam no celular.

## O ponto memorável: a régua de conferência

O código atual e o sugerido aparecem decompostos em capítulo · posição · subposição · item. Os
segmentos que divergem são **riscados em ocre** no atual e **reescritos à caneta** (sublinhado de marca
de texto azul) no sugerido. Abaixo, só a descrição oficial do **primeiro nível divergente** de cada
lado. O revisor entende a correção num relance, sem ler duas descrições completas.

## Movimento

O movimento só responde à ação do usuário: o painel de detalhe desliza ao abrir, e a aprovação imprime
um **carimbo "Aprovado"** (0,28 s). Não há animações de entrada decorativas. `prefers-reduced-motion`
desliga todas as transições.

## Voz

Português do Brasil, linguagem do usuário ("Enviar planilha", "Aprovar sugestão", "Itens para revisar").
A mesma ação tem o mesmo nome em todo o fluxo (botão "Aprovar" → aviso "Aprovado"). Erros dizem o que
aconteceu e o que fazer, sem códigos HTTP. Estados vazios sempre indicam o próximo passo.
