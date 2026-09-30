# ADR 0018 — Conflito normativo só quando muda o cClassTrib

**Status:** aceito · 2026-09-29

## Contexto

O parecer do Jurista tem um campo `conflitos`. Ele serve para apontar fontes oficiais que se contradizem
(ex.: a lei põe o código num anexo e a correlação oficial em outro). O Juiz manda para o **especialista**
todo item cujo parecer tenha conflito que "toca" a hipótese escolhida.

Na prática, o Jurista usava o campo para comentários que não são contradições:

- **feijão preto:** *"a correlação C2 marca VEDADO por já estar no Anexo I, **o que é consistente**"*;
- **orquídea:** *"não está explícito se a redução vale para o Simples Nacional"*.

Os dois itens estavam classificados corretamente e foram ao especialista à toa.

## Decisão

Duas camadas:

1. **Instruções do Jurista v2** (`investigar_enquadramento/v2.md`). Conflito é **só** a contradição real
   que muda o cClassTrib da família no cenário. Cada conflito traz `muda_resultado` (true/false) e
   `cclasstrib_em_jogo`. Fontes coerentes entre si, dúvidas de regime (Simples Nacional, obrigações
   acessórias), lacunas sem efeito e comentários sobre hipóteses descartadas vão para `observacoes`.
2. **Proteção no Juiz** (vale também para pareceres antigos, sem os campos novos):
   - conflito com `muda_resultado = false` é informativo;
   - para os demais, o Juiz calcula os cClassTrib em disputa (declarados, das referências T/C e citados
     no texto). O conflito só trava o item (→ especialista) se apontar um cClassTrib **diferente do
     escolhido e não VEDADO** pela correlação oficial para o código;
   - conflito que toca a conclusão mas não aponta alternativa válida fica registrado como observação.

**Mudar as instruções não refaz pareceres guardados** (ADR 0015). A proteção do Juiz vale na hora, na
reavaliação dos itens.

## Consequências

- O feijão preto passou de especialista para **classificado** (aplicado sem custo, por reavaliação).
- O óleo de soja continua indo ao especialista, porque a correlação oficial o põe nos Anexos VII e IX
  com cClassTrib diferentes.
- A orquídea, com parecer antigo que cita outro cClassTrib permitido, só sai do especialista com
  **Refazer** na família.

## Onde está no código

- `backend/prompts/investigar_enquadramento/v2.md`.
- `backend/app/llm/schemas.py`: `Conflito`, com `muda_resultado` e `cclasstrib_em_jogo`.
- `backend/app/analise/avaliacao.py`: `_cclasstrib_citados` e o bloco de conflitos de `avaliar`.

## Verificação

- `test_conflito_que_nao_muda_o_resultado_nao_trava_o_item`.
- `test_conflito_antigo_so_trava_se_apontar_outro_cclasstrib_permitido`.
