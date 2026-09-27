import { cnpjValido } from "./EmpresasPage";

it("valida CNPJ numérico e alfanumérico (IN RFB 2.229/2024)", () => {
  expect(cnpjValido("11.222.333/0001-81")).toBe(true);
  expect(cnpjValido("11.222.333/0001-82")).toBe(false);
  expect(cnpjValido("12.ABC.345/01DE-35")).toBe(true);
  expect(cnpjValido("00000000000000")).toBe(false);
});
