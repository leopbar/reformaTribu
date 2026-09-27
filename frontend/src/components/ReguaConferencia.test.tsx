import { render, screen } from "@testing-library/react";
import { SeloStatus } from "./dominio";
import { ReguaConferencia } from "./ReguaConferencia";

describe("régua de conferência", () => {
  it("destaca o nível divergente e a descrição oficial de cada lado", () => {
    render(
      <ReguaConferencia
        atual={{ codigo: "34011190", tipo: "ncm", existe: true, hierarquia: [{ codigo: "340111", formatado: "3401.11", descricao: "De toucador" }] }}
        sugerido={{ codigo: "34013000", tipo: "ncm", existe: true, hierarquia: [{ codigo: "340130", formatado: "3401.30", descricao: "Para lavagem da pele, líquido" }] }}
      />,
    );
    expect(screen.getByText(/diverge no nível subposição/i)).toBeInTheDocument();
    expect(screen.getByText("De toucador")).toBeInTheDocument();
    expect(screen.getByText("Para lavagem da pele, líquido")).toBeInTheDocument();
  });
  it("mostra código conferido quando são iguais", () => {
    render(<ReguaConferencia atual={{ codigo: "10063021", tipo: "ncm" }} sugerido={{ codigo: "10063021", tipo: "ncm" }} />);
    expect(screen.getByText("Código conferido.")).toBeInTheDocument();
  });
  it("status nunca só por cor: tem texto", () => {
    render(<SeloStatus status="analise_humana" />);
    expect(screen.getByText("Análise humana")).toBeInTheDocument();
  });
});
