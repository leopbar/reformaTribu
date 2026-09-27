# data/reference

Os arquivos oficiais **não são versionados no git** (são grandes e mudam com frequência). Cada
importação guarda o arquivo bruto no volume `storage` (`/data/storage/referencia/<fonte>/...`) com o
hash SHA-256 registrado na versão.

Para importar sem internet, coloque aqui, em `raw/` (ignorado pelo git), os arquivos baixados das fontes
oficiais e rode `make seed-reference`:

| Arquivo | Fonte |
|---|---|
| `raw/ncm.json` | Portal Único Siscomex — Tabela NCM vigente (JSON) |
| `raw/nbs.csv` | gov.br/MDIC — Tabela da NBS 2.0 (CSV) |
| `raw/cclasstrib.html` ou `raw/cclasstrib.json` | Portal da Conformidade Fácil (SVRS) — Classificação Tributária |
| `raw/lc214.htm` | Planalto — LC 214/2025 compilada |

Detalhes: [docs/base-de-referencia.md](../../docs/base-de-referencia.md).
