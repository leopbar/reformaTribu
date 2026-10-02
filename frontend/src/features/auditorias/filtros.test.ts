import type { LinhaItem } from "./comum";
import { ordenarFila } from "./FilaRevisaoPage";
import { FILTROS_INICIAIS, filtrarItens } from "./Resultado";

const item = (p: Partial<LinhaItem>): LinhaItem => ({
  id: Math.random().toString(), linha: 1, codigo_interno: "1", descricao: "x", tipo: "produto", codigo_atual: "34011190",
  codigo_sugerido: "34011190", tipo_codigo: "ncm", status: "classificado", motivos: [], confianca_global: "alta",
  revisao_status: "pendente", tratamento: "regra_geral", cclasstrib_sugerido: "000001", cst_sugerido: "000", imposto_seletivo: "nao_sujeito",
  perguntas: 0, origem: "pipeline", nivel_revisao: null, aprovado_automaticamente: false, categoria: null, hipotese: "H1", ...p,
});

describe("filtros da tabela de resultado", () => {
  const itens = [
    item({ descricao: "SAB LIQ ERVA DOCE", status: "revisao_contador", codigo_sugerido: "34013000", motivos: ["NCM_INCOERENTE_COM_DESCRICAO"], confianca_global: "media" }),
    item({ descricao: "SUCO UVA 1L", status: "revisao_especialista", codigo_atual: "20096100", codigo_sugerido: "20096100", confianca_global: "baixa", tratamento: "beneficio" }),
    item({ descricao: "ARROZ", codigo_atual: "10063021", codigo_sugerido: "10063021" }),
  ];
  it("por status, motivo, tratamento, capítulo e confiança", () => {
    expect(filtrarItens(itens, { ...FILTROS_INICIAIS, status: ["revisao_contador"] })).toHaveLength(1);
    expect(filtrarItens(itens, { ...FILTROS_INICIAIS, motivo: "NCM_INCOERENTE_COM_DESCRICAO" })).toHaveLength(1);
    expect(filtrarItens(itens, { ...FILTROS_INICIAIS, tratamento: "beneficio" })[0]!.descricao).toBe("SUCO UVA 1L");
    expect(filtrarItens(itens, { ...FILTROS_INICIAIS, capitulo: "10" })).toHaveLength(1);
    expect(filtrarItens(itens, { ...FILTROS_INICIAIS, confianca: "baixa" })).toHaveLength(1);
  });
  it("busca por texto ou por código", () => {
    expect(filtrarItens(itens, { ...FILTROS_INICIAIS, busca: "suco" })).toHaveLength(1);
    expect(filtrarItens(itens, { ...FILTROS_INICIAIS, busca: "3401.30" })).toHaveLength(1);
  });
  it("fila de revisão: pendentes, especialista primeiro", () => {
    const fila = ordenarFila([...itens, item({ revisao_status: "aprovado", aprovado_automaticamente: true })], "todos", "analise");
    expect(fila).toHaveLength(3);
    expect(fila[0]!.status).toBe("revisao_especialista");
    expect(ordenarFila(itens, "todos", "incertos")[0]!.confianca_global).toBe("baixa");
  });
  it("fila de um grupo: só os itens dele, mesmo os já aprovados na sessão", () => {
    const aprovado = item({ id: "g2", status: "revisao_contador", revisao_status: "aprovado" });
    const grupo = [item({ id: "g1", status: "revisao_contador" }), aprovado];
    const fila = ordenarFila([...itens, ...grupo], "todos", "linha", ["g1", "g2"]);
    expect(fila.map((i) => i.id).sort()).toEqual(["g1", "g2"]);
  });
});
