# Base de referência oficial

A base de referência é global (compartilhada por todas as organizações), versionada e nunca
sobrescrita. Cada importação cria uma versão com URL de origem, data da coleta, hash SHA-256,
arquivo bruto guardado, responsável e estatísticas. As auditorias gravam o **snapshot** (conjunto de
versões + regras aprovadas) que usaram.

## Fontes

| Fonte | De onde vem | Formato | Download automático |
|---|---|---|---|
| **NCM** | Portal Único Siscomex — Classificação Fiscal → Tabela NCM vigente (`/classif/api/publico/nomenclatura/download/json`) | JSON com `Nomenclaturas` (código, descrição, datas de início e fim, ato legal) | Sim (`SOURCE_NCM_URL`). O portal tem janelas de manutenção. |
| **NBS** | gov.br/MDIC — NBS 2.0, "Tabela em CSV da versão 2.0 da NBS" | CSV `;` em Windows-1252 | Sim (`SOURCE_NBS_URL`) |
| **CST e cClassTrib** | Portal da Conformidade Fácil (SVRS) — `dfe-portal.svrs.rs.gov.br/CFF/ClassificacaoTributaria` | Página HTML com os dados embutidos, ou JSON exportado | Sim (`SOURCE_CCLASSTRIB_URL`). Inclui indicadores, percentuais de redução, dispositivo legal e a **correlação cClassTrib ↔ NCM/NBS** dos anexos (itens permitidos e vedados). |
| **LC 214/2025** | Planalto — texto compilado (`/ccivil_03/leis/lcp/lcp214.htm`) | HTML (Windows-1252) | Sim (`SOURCE_LC214_URL`). O texto riscado (revogado) é descartado. |
| **Imposto Seletivo** | Anexo XVII da LC 214/2025 | extraído do texto da lei | junto com a LC 214 |

A NBS e o Informe Técnico 2025.002 do Portal da NF-e podem ser acrescentados como novas fontes seguindo
o padrão dos importadores em `backend/app/reference/importers/`.

## Atualização

- **Automática**: o beat roda `referencia.verificar_atualizacoes` todo dia às 4h30. Se o conteúdo mudou
  (hash diferente), cria uma versão nova, regenera as regras afetadas (como **novas versões pendentes**;
  a versão aprovada anterior continua valendo até a nova ser aprovada) e revalida todas as regras.
- **Manual pela interface**: Base de referência → "Baixar da fonte oficial" ou "Envio manual".
- **Linha de comando**: `make seed-reference` (se o download falhar, usa arquivos em
  `/data/reference/raw/`: `ncm.json`, `nbs.csv`, `cclasstrib.html|json`, `lc214.htm`).

Se uma fonte não estiver disponível, o sistema **não inventa conteúdo**: a base fica marcada como
incompleta e os itens que dependem dela vão para análise humana (`BASE_REFERENCIA_INCOMPLETA`).

### Onde baixar manualmente

- **NCM**: portalunico.siscomex.gov.br → Classificação Fiscal de Mercadorias → Tabela NCM → "Download da
  tabela vigente" em JSON.
- **NBS**: gov.br/mdic → Comércio e Serviços → NBS → "Tabela em CSV da versão 2.0 da NBS".
- **cClassTrib**: dfe-portal.svrs.rs.gov.br/CFF/ClassificacaoTributaria → salvar a página (somente HTML)
  ou "Exportar para JSON".
- **LC 214/2025**: planalto.gov.br/ccivil_03/leis/lcp/lcp214.htm → salvar a página (somente HTML).

## Regras declarativas

Geradas por `backend/app/rules/official.py`, a partir de (em ordem de preferência):

1. **Correlação oficial** da tabela cClassTrib: um item de anexo por cClassTrib, com os códigos
   permitidos (abrangência) e vedados (exceções) já expandidos pela administração tributária.
2. **Texto dos anexos da LC 214** para anexos sem correlação publicada (códigos citados no texto; o
   cClassTrib é o único associado ao anexo na tabela oficial — se houver mais de um, a regra nasce
   inválida até o superadministrador escolher).
3. **Anexo XVII** (Imposto Seletivo): sinalização do item, sem CST/cClassTrib.
4. **Regra padrão** de tributação integral (cClassTrib `000001` da tabela oficial), aplicada só quando
   nenhuma regra de anexo casa e não há regra pendente que poderia casar.

Formato (exportável/importável em YAML em Base de referência → Regras):

```yaml
id: cct-200035-1a2b3c4d
anexo: VIII
item: "1"
descricao_legal: Sabões de toucador classificados no código 3401.11.90 da NCM/SH
dispositivo_legal: LC 214/2025, art. 136, Anexo VIII, item 1
tipo_tratamento: reducao_60
abrangencia:
  tipo_codigo: ncm
  codigos: [{codigo: "34011190", nivel: item}]
excecoes: []
condicoes: []            # ex.: {atributo: adicao_acucar, fonte: item, deve_ser: "nao", pergunta: "..."}
cst_ibs_cbs: "200"
cclasstrib: "200035"
vigencia: {inicio: null, fim: null}
status_revisao: pendente_revisao
```

Toda regra nasce `pendente_revisao` e é validada contra as tabelas oficiais (CST/cClassTrib existem e
são compatíveis; códigos existem na NCM/NBS vigente — extintos são sinalizados). Condições descritas em
palavras (ex.: "sem adição de açúcar") geram um aviso; o superadministrador as estrutura manualmente ou
com "Sugerir condições com IA" (sugestão também pendente). Regras aprovadas são **precedentes opcionais**: o analista raciocina a partir do texto legal e das tabelas; a regra aprovada aumenta a confiança quando confirma a conclusão e gera conflito (revisão do especialista) quando diverge.

O relatório `GET /api/referencia/validacao` lista regras (inclusive aprovadas) que citam códigos
inexistentes na tabela vigente.

## Divergências entre a lei, a tabela oficial e a regra

A correlação oficial cClassTrib ↔ NCM/NBS nem sempre reproduz o texto da LC 214/2025. Exemplo real
(Anexo I, item 20): a lei exclui do benefício "os salmonídeos, atuns, bacalhaus, hadoque e saithe
classificados nas subposições 0304.4…", mas a tabela veta **a subposição inteira**, inclusive filés de
cação e de peixes chatos, que a lei não exclui.

`backend/app/rules/divergencias.py` lê o item do anexo em partes e compara com a regra no nível dos
códigos folha da nomenclatura vigente:

- **Leitura da lei**: códigos incluídos; exceções por código ("exceto os produtos das subposições…");
  exceções **parciais** ("exceto os salmonídeos… classificados nas subposições…"), que excluem só certos
  produtos dentro do código; exclusões por **referência a outro anexo** ("ressalvados os produtos
  relacionados no Anexo I"); e restrições em palavras ("destinados à alimentação animal", "sem adição
  de açúcar").
- **Divergências detectadas** (avisos `DIV_*` na regra, com os códigos envolvidos e uma ação sugerida):

| Código | Gravidade | Situação |
|---|---|---|
| `DIV_ALEM_DA_LEI` | alta | a regra beneficia códigos que o item da lei não cita |
| `DIV_EXCECAO_DA_LEI_IGNORADA` | alta | a lei exclui expressamente códigos que a regra beneficia |
| `DIV_EXCECAO_PARCIAL_AMPLIADA` | alta | a lei exclui só certos produtos, e a regra exclui o código inteiro |
| `DIV_VETO_SEM_BASE_NA_LEI` | alta | a tabela veta códigos que a lei inclui sem exceção |
| `DIV_LEI_NAO_COBERTA` | alta | a lei inclui códigos que a regra não abrange |
| `DIV_TRATAMENTO` | média | o cClassTrib aplica tratamento diferente do título do anexo, sem condição que o limite |
| `DIV_RESTRICAO_TEXTUAL` | média | a lei restringe em palavras e a regra não tem condição nem exceção textual |
| `DIV_LEI_CODIGO_INEXISTENTE` | média | a lei cita código que não existe na tabela vigente (renumeração) |
| `DIV_ANEXO` | média | o cClassTrib pertence, na tabela oficial, a outro anexo |
| `DIV_SOBREPOSICAO` | informativa | outra regra, de outro item e cClassTrib, cobre os mesmos códigos sem condição que as diferencie |
| `DIV_SEM_TEXTO_LEGAL` | informativa | o item da lei correspondente não foi localizado |

Nada é corrigido automaticamente. Na tela de revisão, cada divergência mostra os códigos (com a
descrição oficial) e um botão para aplicar a correção sugerida aos códigos marcados; abrangência e
exceções também podem ser editadas diretamente. **Regras com divergência alta ou média só podem ser
aprovadas individualmente, com justificativa escrita** (registrada na trilha de auditoria), e ficam
fora da aprovação em lote. As divergências são recalculadas a cada edição e após cada importação de
tabela.


## Atos normativos da reforma (fonte `normas`)

Além da LC 214/2025, o analista consulta os artigos vigentes destes atos, importados do Planalto
(`make seed-reference` ou **Base normativa → Atos normativos da reforma**; CLI: `python -m app.cli seed-normas`):

| Ato | Endereço |
|---|---|
| EC 132/2023 (inclui a transição no ADCT) | planalto.gov.br/ccivil_03/constituicao/emendas/emc/emc132.htm |
| LC 227/2026 (CGIBS, processo do IBS, alterações da LC 214) | planalto.gov.br/ccivil_03/leis/lcp/lcp227.htm |
| Decreto 12.955/2026 (regulamento da CBS) | planalto.gov.br/ccivil_03/_ato2023-2026/2026/decreto/D12955.htm |

Cada ato é uma versão própria (várias ficam ativas ao mesmo tempo); o texto riscado é descartado e
artigos longos são divididos em trechos para a busca por significado. O catálogo fica em
`backend/app/reference/importers/normas.py`. O calendário da transição (2026 teste, 2027–2028 CBS e
IBS de 0,1 p.p., 2029–2032 redução de ICMS/ISS, 2033 vigência integral) está em `app/analise/transicao.py`.
