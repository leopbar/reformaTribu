/**
 * Régua de conferência — o elemento de assinatura visual do produto.
 *
 * Mostra o código atual e o sugerido decompostos na hierarquia oficial (capítulo › posição ›
 * subposição › item), como um revisor conferindo um documento: o trecho que diverge é riscado no
 * atual e reescrito "à caneta" no sugerido, e a descrição oficial do primeiro nível divergente
 * aparece lado a lado. Assim a diferença é compreendida em um relance, sem ler as duas descrições
 * completas.
 */
import { ArrowDown, Equal } from "lucide-react";
import { cn } from "@/lib/utils";
import { segmentosNbs, segmentosNcm, soDigitos } from "@/lib/format";

export interface Nivel {
  codigo: string;
  formatado: string;
  descricao: string;
}

export interface CodigoInfo {
  codigo: string;
  formatado?: string;
  tipo?: string | null;
  existe?: boolean | null;
  descricao_completa?: string | null;
  hierarquia?: Nivel[];
  informado?: string | null;
  zero_restaurado?: boolean;
}

function primeiroNivelDivergente(a: string, b: string, tipo: string): number {
  const cortes = tipo === "nbs" ? [1, 3, 5, 7, 9] : [2, 4, 6, 8];
  for (let i = 0; i < cortes.length; i++) {
    const n = cortes[i]!;
    if (a.slice(0, n) !== b.slice(0, n)) return i;
  }
  return -1;
}

export function ReguaConferencia({
  atual,
  sugerido,
  className,
}: {
  atual: CodigoInfo | null;
  sugerido: CodigoInfo | null;
  className?: string;
}) {
  const tipo = sugerido?.tipo ?? atual?.tipo ?? "ncm";
  const seg = tipo === "nbs" ? segmentosNbs : segmentosNcm;
  const cA = soDigitos(atual?.codigo);
  const cS = soDigitos(sugerido?.codigo);
  const igual = !!cA && cA === cS;
  const div = cA && cS ? primeiroNivelDivergente(cA, cS, tipo) : -1;
  const segA = cA ? seg(cA) : null;
  const segS = cS ? seg(cS) : null;
  const rotulos = (segS ?? segA ?? seg("")).map((s) => s.rotulo);

  const nivelTexto = (info: CodigoInfo | null, idx: number) => {
    if (!info?.hierarquia?.length) return null;
    const cortes = tipo === "nbs" ? [1, 3, 5, 7, 9] : [2, 4, 6, 8];
    const alvo = soDigitos(info.codigo).slice(0, cortes[idx]);
    // Nível exato, ou o mais profundo disponível até ele (subposições de 5 dígitos etc.).
    const candidatos = info.hierarquia.filter((h) => alvo.startsWith(h.codigo) || h.codigo.startsWith(alvo));
    return candidatos.sort((x, y) => y.codigo.length - x.codigo.length).find((h) => h.codigo.length <= alvo.length + 1) ?? null;
  };

  return (
    <figure className={cn("rounded-lg border border-regua bg-superficie", className)} aria-label="Comparação entre o código atual e o sugerido">
      <div className="grid grid-cols-[5.5rem_1fr] items-stretch">
        <div />
        <div className="grid border-b border-regua" style={{ gridTemplateColumns: `repeat(${rotulos.length}, minmax(0,1fr))` }}>
          {rotulos.map((r, i) => (
            <div
              key={r}
              className={cn(
                "px-2 py-1.5 text-center text-2xs text-tinta-3",
                i === div && "font-semibold text-caneta",
              )}
            >
              {r}
            </div>
          ))}
        </div>

        <Linha rotulo="Atual" sub={atual?.zero_restaurado ? `informado ${atual.informado}` : atual?.existe === false ? "inexistente" : undefined}>
          {segA ? (
            segA.map((s, i) => (
              <Celula key={i} riscada={!igual && div >= 0 && i >= div} valor={s.valor} />
            ))
          ) : (
            <div className="col-span-full px-3 py-3 text-sm text-tinta-3">Sem código cadastrado</div>
          )}
        </Linha>

        <div className="flex items-center justify-center py-0.5 text-tinta-3" aria-hidden>
          {igual ? <Equal className="size-4 text-conferido" /> : <ArrowDown className="size-4" />}
        </div>
        <div />

        <Linha rotulo="Sugerido" destaque>
          {segS ? (
            segS.map((s, i) => <Celula key={i} caneta={!igual && (div < 0 ? !cA : i >= div)} valor={s.valor} />)
          ) : (
            <div className="col-span-full px-3 py-3 text-sm text-tinta-3">Sem sugestão — análise humana</div>
          )}
        </Linha>
      </div>

      <figcaption className="border-t border-regua px-4 py-3 text-sm">
        {igual ? (
          <p className="text-tinta-2">
            <span className="font-medium text-conferido">Código conferido.</span> O código cadastrado descreve o item em
            todos os níveis da hierarquia.
          </p>
        ) : cS && cA && div >= 0 ? (
          <div className="grid gap-2 sm:grid-cols-2">
            <DescricaoNivel titulo={`Atual · diverge no nível ${rotulos[div]?.toLowerCase()}`} nivel={nivelTexto(atual, div)} riscado />
            <DescricaoNivel titulo="Sugerido" nivel={nivelTexto(sugerido, div)} />
          </div>
        ) : cS ? (
          <DescricaoNivel titulo="Sugerido" nivel={{ codigo: cS, formatado: sugerido?.formatado ?? cS, descricao: sugerido?.descricao_completa ?? "" }} />
        ) : (
          <p className="text-tinta-3">Nenhum código sugerido com segurança suficiente.</p>
        )}
      </figcaption>
    </figure>
  );
}

function Linha({ rotulo, sub, destaque, children }: { rotulo: string; sub?: string; destaque?: boolean; children: React.ReactNode }) {
  const filhos = Array.isArray(children) ? children.length : 1;
  return (
    <>
      <div className="flex flex-col justify-center px-3 py-2">
        <span className={cn("text-xs font-medium", destaque ? "text-tinta" : "text-tinta-3")}>{rotulo}</span>
        {sub ? <span className="text-2xs text-ocre">{sub}</span> : null}
      </div>
      <div className="grid" style={{ gridTemplateColumns: `repeat(${filhos}, minmax(0,1fr))` }}>
        {children}
      </div>
    </>
  );
}

function Celula({ valor, riscada, caneta }: { valor: string; riscada?: boolean; caneta?: boolean }) {
  return (
    <div className="relative flex items-center justify-center border-l border-regua px-1 py-2.5 first:border-l-0">
      <span
        className={cn(
          "codigo text-xl tracking-wider",
          riscada && "text-ocre line-through decoration-2 decoration-ocre/80",
          caneta && "font-medium text-caneta traco-caneta",
        )}
      >
        {valor.trim() || "·"}
      </span>
    </div>
  );
}

function DescricaoNivel({ titulo, nivel, riscado }: { titulo: string; nivel: Nivel | null; riscado?: boolean }) {
  return (
    <div className={cn("rounded-md border-l-2 pl-3", riscado ? "border-ocre" : "border-caneta")}>
      <p className="text-2xs text-tinta-3">{titulo}</p>
      {nivel ? (
        <p className="mt-0.5">
          <span className="codigo text-xs text-tinta-2">{nivel.formatado}</span>{" "}
          <span className={cn(riscado && "text-tinta-3")}>{nivel.descricao}</span>
        </p>
      ) : (
        <p className="mt-0.5 text-tinta-3">Descrição oficial indisponível.</p>
      )}
    </div>
  );
}
