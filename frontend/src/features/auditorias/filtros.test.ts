import type { LinhaItem } from "./comum";
import { ordenarFila } from "./FilaRevisaoPage";
import { FILTROS_INICIAIS, filtrarItens } from "./Resultado";

const item = (p: Partial<LinhaItem>): LinhaItem => ({
  id: Math.random().toString(), linha: 1, codigo_interno: "1", descricao: "x", tipo: "produto", codigo_atual: "34011190",
  codigo_sugerido: "34011190", tipo_codigo: "ncm", status: "confirmado", motivos: [], confianca: 0.95,
  revisao_status: "pendente", anexo: null, cclasstrib_sugerido: "000001", cst_sugerido: "000", imposto_seletivo: false,
  perguntas: 0, origem: "pipeline", ...p,
});

describe("filtros da tabela de resultado", () => {
  const itens = [
    item({ descricao: "SAB LIQ ERVA DOCE", status: "corrigido", codigo_sugerido: "34013000", motivos: ["NCM_INCOERENTE_COM_DESCRICAO"] }),
    item({ descricao: "SUCO UVA 1L", status: "analise_humana", codigo_atual: "20096100", codigo_sugerido: "20096100", confianca: 0.6, anexo: "VII" }),
    item({ descricao: "ARROZ", codigo_atual: "10063021", codigo_sugerido: "10063021" }),
  ];
  it("por status, motivo, anexo, capítulo e confiança", () => {
    expect(filtrarItens(itens, { ...FILTROS_INICIAIS, status: ["corrigido"] })).toHaveLength(1);
    expect(filtrarItens(itens, { ...FILTROS_INICIAIS, motivo: "NCM_INCOERENTE_COM_DESCRICAO" })).toHaveLength(1);
    expect(filtrarItens(itens, { ...FILTROS_INICIAIS, anexo: "VII" })[0]!.descricao).toBe("SUCO UVA 1L");
    expect(filtrarItens(itens, { ...FILTROS_INICIAIS, capitulo: "10" })).toHaveLength(1);
    expect(filtrarItens(itens, { ...FILTROS_INICIAIS, confiancaMax: "0.9" })).toHaveLength(1);
  });
  it("busca por texto ou por código", () => {
    expect(filtrarItens(itens, { ...FILTROS_INICIAIS, busca: "suco" })).toHaveLength(1);
    expect(filtrarItens(itens, { ...FILTROS_INICIAIS, busca: "3401.30" })).toHaveLength(1);
  });
  it("fila de revisão: pendentes, análise humana primeiro", () => {
    const fila = ordenarFila([...itens, item({ revisao_status: "aprovado" })], "todos", "analise");
    expect(fila).toHaveLength(3);
    expect(fila[0]!.status).toBe("analise_humana");
    expect(ordenarFila(itens, "todos", "incertos")[0]!.confianca).toBe(0.6);
  });
});
