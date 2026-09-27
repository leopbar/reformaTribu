/** Formatação no padrão brasileiro e de códigos fiscais. */

const numero = new Intl.NumberFormat("pt-BR");
const dataHora = new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short" });
const data = new Intl.DateTimeFormat("pt-BR", { dateStyle: "short" });
const usd = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "USD", minimumFractionDigits: 2 });
const pct = new Intl.NumberFormat("pt-BR", { style: "percent", maximumFractionDigits: 0 });

export const fmtNum = (v: number | null | undefined) => (v == null ? "—" : numero.format(v));
export const fmtUSD = (v: number | null | undefined) => (v == null ? "—" : usd.format(v).replace(/\s/u, " "));
export const fmtPct = (v: number | null | undefined) => (v == null ? "—" : pct.format(v));
export const fmtDataHora = (v: string | null | undefined) => (v ? dataHora.format(new Date(v)) : "—");
export const fmtData = (v: string | null | undefined) =>
  v ? data.format(new Date(v.length === 10 ? `${v}T12:00:00` : v)) : "—";

export function soDigitos(v: string | null | undefined): string {
  return (v ?? "").replace(/\D/g, "");
}

/** 34011190 → 3401.11.90 */
export function fmtNcm(v: string | null | undefined): string {
  const c = soDigitos(v);
  if (c.length <= 4) return c;
  if (c.length <= 6) return `${c.slice(0, 4)}.${c.slice(4)}`;
  return `${c.slice(0, 4)}.${c.slice(4, 6)}.${c.slice(6)}`;
}

/** 101011100 → 1.0101.11.00 */
export function fmtNbs(v: string | null | undefined): string {
  const c = soDigitos(v);
  if (c.length <= 1) return c;
  const partes = [c[0], c.slice(1, 5)];
  const resto = c.slice(5);
  if (resto) partes.push(resto.slice(0, 2));
  if (resto.length > 2) partes.push(resto.slice(2));
  return partes.filter(Boolean).join(".");
}

export function fmtCodigo(tipo: string | null | undefined, v: string | null | undefined): string {
  if (!v) return "—";
  return tipo === "nbs" ? fmtNbs(v) : fmtNcm(v);
}

export function fmtCnpj(v: string): string {
  const c = v.replace(/[^0-9A-Za-z]/g, "").toUpperCase();
  if (c.length !== 14) return v;
  return `${c.slice(0, 2)}.${c.slice(2, 5)}.${c.slice(5, 8)}/${c.slice(8, 12)}-${c.slice(12)}`;
}

/** Segmentos hierárquicos do código para a régua de conferência. */
export interface Segmento {
  rotulo: string;
  valor: string;
}

export function segmentosNcm(v: string): Segmento[] {
  const c = soDigitos(v).padEnd(8, " ");
  return [
    { rotulo: "Capítulo", valor: c.slice(0, 2) },
    { rotulo: "Posição", valor: c.slice(2, 4) },
    { rotulo: "Subposição", valor: c.slice(4, 6) },
    { rotulo: "Item", valor: c.slice(6, 8) },
  ];
}

export function segmentosNbs(v: string): Segmento[] {
  const c = soDigitos(v).padEnd(9, " ");
  return [
    { rotulo: "Seção", valor: c.slice(0, 1) },
    { rotulo: "Capítulo", valor: c.slice(1, 3) },
    { rotulo: "Posição", valor: c.slice(3, 5) },
    { rotulo: "Subposição", valor: c.slice(5, 7) },
    { rotulo: "Item", valor: c.slice(7, 9) },
  ];
}

export const plural = (n: number, um: string, varios: string) => `${fmtNum(n)} ${n === 1 ? um : varios}`;
