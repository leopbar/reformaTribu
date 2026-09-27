import { fmtCnpj, fmtCodigo, fmtNbs, fmtNcm, fmtNum, fmtUSD, segmentosNcm } from "./format";

describe("formatação", () => {
  it("formata NCM e NBS", () => {
    expect(fmtNcm("34011190")).toBe("3401.11.90");
    expect(fmtNcm("03061")).toBe("0306.1");
    expect(fmtNbs("101011100")).toBe("1.0101.11.00");
    expect(fmtCodigo("nbs", "113022100")).toBe("1.1302.21.00");
    expect(fmtCodigo("ncm", null)).toBe("—");
  });
  it("números, moeda e CNPJ no padrão brasileiro", () => {
    expect(fmtNum(1234567)).toBe("1.234.567");
    expect(fmtUSD(5.5)).toMatch(/US\$\s?5,50/);
    expect(fmtCnpj("12abc34501de35")).toBe("12.ABC.345/01DE-35");
  });
  it("decompõe o NCM na hierarquia", () => {
    expect(segmentosNcm("34011190").map((s) => s.valor)).toEqual(["34", "01", "11", "90"]);
  });
});
