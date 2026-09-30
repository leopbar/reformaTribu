# ADR 0019 — Dúvida de identificação que não muda o imposto

**Status:** aceito · 2026-09-30

## Contexto

Qualquer dúvida registrada pela IA sobre o NCM mandava o item ao contador, mesmo quando todas as
possibilidades davam o mesmo imposto. Exemplo: biscoito maisena, 1905.31.00 (com açúcar) ou 1905.90.20
(sem açúcar). Os dois pagam integral. Um analista humano faz duas perguntas: "o que é o produto?" e
"**se eu estiver errado, o resultado muda?**". O Juiz já fazia a segunda pergunta para os **fatos**
(ADR 0013: só pergunta quando a resposta muda o cClassTrib), mas não para o **NCM**.

## Decisão

- O Identificador e o Segundo parecer (prompts `julgar_coerencia` e `escalar` v2) informam
  `codigos_alternativos`: até 3 códigos **da prova** que a dúvida poderia justificar. A identidade grava
  só os que estão entre os candidatos oficiais.
- O Juiz calcula, **sem IA**, o tratamento de cada alternativa (`cClassTrib|Imposto Seletivo`):
  - se a família da alternativa já tem tese: aplica a tese aos fatos do item. Hipótese em aberto ou IS
    "depende" contam como desconhecido;
  - se não tem: consulta a base oficial. Sem correlação permitida e sem item de anexo que cite o código,
    vale a regra geral (`000001|nao_sujeito`); caso contrário, desconhecido.
- **Se todas as alternativas têm o mesmo tratamento do código escolhido**, a dúvida é imaterial e a nota
  de identificação passa a "confirmada", com o texto *"A dúvida sobre o código não muda o imposto: X ou
  Y têm o mesmo tratamento"*. A dúvida fica registrada.
- **Condições de segurança (revisão de 2026-09-30).** A regra só dispensa a pessoa quando:
  - o **NCM do ERP foi mantido** (situação `confirmado`);
  - a **descrição é suficiente**;
  - a **certeza é de pelo menos 70%**.

  Criar ou trocar um NCM mexe no cadastro e em outros impostos (ICMS, IPI), então sempre vai ao contador,
  com a nota *"o imposto seria o mesmo, mas o NCM precisa de confirmação"*. A revisão veio de um caso
  real: um kit festa **sem NCM**, com descrição vaga ("conteúdo do kit não informado") e 64% de certeza,
  foi aprovado sozinho.

## Consequências

- Menos itens no contador sem motivo:
  - biscoito maisena: 1905.31.00 × 1905.90.20;
  - pote plástico: 3924.10.00 × 3924.90.00 × 3923.30.90;
  - papel alumínio.
- Dúvidas que mudam o imposto continuam com uma pessoa. Exemplos: suco integral (a alternativa pode ter
  redução de 60%); pão (1905.90.90 depende de ser pão francês).
- Itens analisados antes desta versão não têm `codigos_alternativos`; a regra vale depois de reanalisar.

## Onde está no código

- `backend/prompts/julgar_coerencia/v2.md` e `backend/prompts/escalar/v2.md`.
- `backend/app/llm/schemas.py`: `Julgamento.codigos_alternativos`.
- `backend/app/analise/identidade.py`: identidade com `codigos_alternativos`.
- `backend/app/analise/aplicacao.py`: `tratamento_alternativas`, `tratamento_do_codigo`.
- `backend/app/analise/avaliacao.py`: bloco "a dúvida de identificação muda o imposto?".

## Verificação

- `test_duvida_que_nao_muda_o_imposto_nao_manda_ao_contador`.
- `test_duvida_que_muda_ou_nao_se_sabe_continua_com_o_contador`.
- `test_duvida_imaterial_nao_aprova_ncm_criado_descricao_vaga_ou_certeza_baixa`.
- Dados reais:
  - 1905.90.20 → integral;
  - 1905.90.90 → desconhecido;
  - 2202.10.00 → integral com IS.
