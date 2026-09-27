# ADR 0003 — Embeddings locais: multilingual-e5-base (padrão) e bge-m3 (opcional)

**Status:** aceito (revisado no mesmo dia)

**Contexto.** A Anthropic não oferece embeddings e nenhum texto de cliente deve sair da
infraestrutura. A busca precisa funcionar bem em português, com descrições hierárquicas longas.

**Decisão.** Hugging Face Text Embeddings Inference (CPU) servindo `intfloat/multilingual-e5-base`
(768 dimensões, prefixos `query:`/`passage:`) como padrão. `BAAI/bge-m3` (1024 dimensões, contexto de
8k, sem prefixos) é recomendado quando houver 6 GB+ de memória livre para o contêiner.

**Motivo da revisão.** A primeira escolha foi o bge-m3, mas ele foi encerrado por falta de memória
(OOMKilled) mesmo com limite de 6 GB numa máquina de 8 GB compartilhada com outros serviços. O e5-base
roda com ~1,5 GB.

**Consequências.** Modelo e dimensão são configuráveis (`EMBEDDINGS_MODEL`, `EMBEDDINGS_DIM`, prefixos);
`make migrate` ajusta a coluna `vector(N)` e dispara a reindexação. A escolha definitiva deve sair do
harness de avaliação (recall@20 dos candidatos no conjunto-ouro validado). A busca é híbrida (vetorial
+ `tsvector` português, combinadas por RRF), então a qualidade não depende só do modelo.
