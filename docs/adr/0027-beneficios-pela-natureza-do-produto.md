# ADR 0027 — Benefícios que a lei dá pela natureza do produto (sem lista de NCM)

**Status:** aceito · 2026-09-30

## Contexto

Simulação pedida pelo usuário: farmácia vende "NALDECON PACK", tipo "medicamento para revenda", NCM
3004.90.36. Seguindo o código com os dados reais da base:

1. **O Jurista não teria como acertar.** O pacote de evidências só oferecia 000001 (integral), 200038
   (insumo **veterinário**) e 515001 (diferimento veterinário). A correlação oficial liga a posição 30.04
   apenas ao Anexo IX (uso veterinário). O cClassTrib certo, 200032 (medicamento registrado na Anvisa,
   redução de 60%, art. 133), e o de alíquota zero, 200009 (art. 146), não têm **nenhuma** correlação na
   tabela: a lei os concede pela natureza do produto, sem lista de NCM. Como a lista de cClassTrib do
   Jurista é fechada, o remédio sairia com tributação integral, possivelmente aprovado sozinho.
2. **Não era só farmácia.** Na tabela inteira, estão na mesma situação: 200009, 200032, 200053 (soros e
   vacinas), 200036 (in natura, art. 137), 410008 (livros, jornais, periódicos, art. 9º, IV) e 410009
   (fonogramas brasileiros, art. 9º, V).
3. **A marca apagava o produto.** O Arrumador tira a marca da descrição para juntar itens iguais de
   marcas diferentes. Com a marca "Naldecon", sobraria "PACK": nada a identificar, e "BENEGRIP PACK"
   viraria o mesmo item.
4. **O tipo do ERP se perdia.** "medicamento para revenda" só era usado para saber se o item é produto ou
   serviço.

## Decisão

- **Ligações pela lei** (`app/analise/natureza.py`): catálogo declarativo que liga posições do NCM aos
  cClassTrib concedidos pela natureza do produto, com a condição e a exceção que a lei exige:

  | Posições | cClassTrib | Artigo | Condição |
  |---|---|---|---|
  | 30.03, 30.04 | 200009 | 146 | estar na lista oficial de alíquota zero (§ 3º) |
  | 30.03, 30.04 | 200032 | 133 | registrado na Anvisa ou manipulado; exceção: lista do art. 146 |
  | 30.02 | 200053 | 146, § 1º, III | ser soro ou vacina |
  | capítulos 01–04, 06–10, 12, 14; 44.01, 44.03 | 200036 | 137 | estar in natura (§ 1º) |
  | 49.01–49.03; 48.01 | 410008 | 9º, IV | livro, jornal, periódico; papel destinado à impressão |
  | 85.23 | 410009 | 9º, V | fonograma musical brasileiro |

  A ligação entra no pacote como mais uma linha de `correlacoes_oficiais`, com `fonte: "lei (…)"`. Com
  isso, o cClassTrib passa a ser candidato, o artigo entra nos trechos (pelo nome do cClassTrib) e o
  Jurista precisa tratá-lo como hipótese ou justificar o descarte, como já faz com a tabela. O prompt
  `investigar_enquadramento` v3 explica essas linhas: não são conflito; a regularidade sanitária do que
  a farmácia vende é presumida; estar na lista de alíquota zero ou estar in natura vira condição de item.
- **"Sem parecer = regra geral"** (usado para saber se a dúvida de NCM muda o imposto) deixa de valer para
  códigos com ligação pela lei.
- **Marca que é o próprio produto fica.** Se, sem a marca, o que sobra só fala de embalagem ou quantidade
  ("PACK", "36 COMPRIMIDOS", "LATA 350ML"), a descrição fica inteira. "CAFÉ SÃO JOSÉ 500G" continua
  virando "CAFÉ 500G".
- **O tipo do ERP** vai ao Identificador e ao Leitor de fatos (`tipo_no_erp`). Para o Leitor, "revenda"
  afirma que o item foi comprado pronto de terceiros.

## Resultado esperado para o Naldecon

Identificação confirmada (3004.90.36). Hipóteses do Jurista: 200009 se estiver na lista do art. 146;
senão, 200032. Um antigripal não está nas categorias do art. 146, então a pergunta "está na lista de
alíquota zero?" tende a ser respondida "não" (ou já vem como suposição do Leitor). O resultado é
**CST 200 / cClassTrib 200032, redução de 60%**. Nunca mais a tributação integral por falta de opção.

## Consequências

- As teses das famílias alcançadas (medicamentos, hortifrúti in natura, livros) mudam de chave e são
  estudadas de novo uma vez, na próxima análise.
- Supermercados passam a ver a hipótese in natura (60%) para hortifrúti fora do Anexo XV. A pergunta "está
  in natura?" só aparece quando muda o resultado. Os anexos com benefício maior (cesta básica, Anexo XV)
  continuam prevalecendo.
- Pendências: a lista oficial do art. 146, § 3º, ainda não é importada. Quando for, o fato "está na
  lista de alíquota zero" pode vir da base, e não de uma pergunta. Também falta medir o prompt v3 no
  conjunto-ouro.
