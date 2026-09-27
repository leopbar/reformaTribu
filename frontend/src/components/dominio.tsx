/** Componentes do domínio: status, códigos, confiança, motivos, estados vazios e de erro. */
import { AlertTriangle, CheckCircle2, CircleDashed, Clock3, FileWarning, PenLine, SearchX, Stamp, XCircle } from "lucide-react";
import type { ReactNode } from "react";
import { ApiError } from "@/api/client";
import { cn } from "@/lib/utils";
import { fmtCodigo, fmtPct } from "@/lib/format";
import { Button, Dica } from "./ui/primitives";

// -------------------------------------------------------------------------------- status --
export const STATUS = {
  confirmado: { rotulo: "Confirmado", icone: CheckCircle2, cor: "text-conferido", fundo: "bg-conferido-suave", borda: "border-conferido/40" },
  corrigido: { rotulo: "Corrigido", icone: PenLine, cor: "text-caneta", fundo: "bg-caneta-suave", borda: "border-caneta/40" },
  analise_humana: { rotulo: "Análise humana", icone: AlertTriangle, cor: "text-ocre", fundo: "bg-ocre-suave", borda: "border-ocre/40" },
  pendente: { rotulo: "Na fila", icone: Clock3, cor: "text-tinta-3", fundo: "bg-superficie-2", borda: "border-regua" },
  processando: { rotulo: "Processando", icone: CircleDashed, cor: "text-tinta-2", fundo: "bg-superficie-2", borda: "border-regua" },
  erro: { rotulo: "Erro", icone: XCircle, cor: "text-perigo", fundo: "bg-perigo-suave", borda: "border-perigo/40" },
} as const;

export type StatusItem = keyof typeof STATUS;

/** Status nunca só por cor: ícone + texto + cor. */
export function SeloStatus({ status, compacto, className }: { status: string; compacto?: boolean; className?: string }) {
  const s = STATUS[status as StatusItem] ?? STATUS.pendente;
  const Icone = s.icone;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2 py-0.5 text-2xs font-medium",
        s.cor,
        s.fundo,
        s.borda,
        className,
      )}
    >
      <Icone className="size-3.5" aria-hidden />
      {compacto ? <span className="sr-only">{s.rotulo}</span> : s.rotulo}
    </span>
  );
}

export const REVISAO = {
  pendente: { rotulo: "Aguardando revisão", cor: "text-tinta-3" },
  aprovado: { rotulo: "Aprovado", cor: "text-conferido" },
  rejeitado: { rotulo: "Rejeitado", cor: "text-perigo" },
} as const;

export function SeloRevisao({ status }: { status: string }) {
  if (status === "aprovado")
    return (
      <span className="inline-flex items-center gap-1 text-2xs font-semibold uppercase tracking-wide text-conferido">
        <Stamp className="size-3.5" aria-hidden /> Aprovado
      </span>
    );
  if (status === "rejeitado")
    return (
      <span className="inline-flex items-center gap-1 text-2xs font-medium text-perigo">
        <XCircle className="size-3.5" aria-hidden /> Rejeitado
      </span>
    );
  return <span className="text-2xs text-tinta-3">Aguardando revisão</span>;
}

// -------------------------------------------------------------------------------- código --
export function Codigo({ tipo, valor, className }: { tipo?: string | null; valor?: string | null; className?: string }) {
  return <span className={cn("codigo text-sm", !valor && "text-tinta-3", className)}>{fmtCodigo(tipo, valor)}</span>;
}

// ------------------------------------------------------------------------------ confiança --
export function Confianca({
  valor,
  componentes,
  className,
}: {
  valor: number | null | undefined;
  componentes?: Record<string, number> | null;
  className?: string;
}) {
  if (valor == null) return <span className="text-tinta-3">—</span>;
  const tom = valor >= 0.9 ? "bg-conferido" : valor >= 0.75 ? "bg-caneta" : "bg-ocre";
  const barra = (
    <span className={cn("inline-flex items-center gap-2", className)}>
      <span className="relative h-1.5 w-12 overflow-hidden rounded-full bg-superficie-3" aria-hidden>
        <span className={cn("absolute inset-y-0 left-0", tom)} style={{ width: `${valor * 100}%` }} />
      </span>
      <span className="num text-xs text-tinta-2">{fmtPct(valor)}</span>
    </span>
  );
  if (!componentes) return barra;
  const nomes: Record<string, string> = {
    modelo: "Modelo de IA",
    busca: "Posição na busca",
    concordancia: "Concordância entre etapas",
    regra: "Certeza da regra legal",
    descricao: "Qualidade da descrição",
    estrutura: "Validade do código atual",
  };
  return (
    <Dica
      texto={
        <span className="flex flex-col gap-0.5">
          {Object.entries(nomes).map(([k, n]) => (
            <span key={k} className="flex justify-between gap-4">
              <span>{n}</span>
              <span className="num">{fmtPct(componentes[k] ?? 0)}</span>
            </span>
          ))}
        </span>
      }
    >
      <span tabIndex={0}>{barra}</span>
    </Dica>
  );
}

// -------------------------------------------------------------------------------- motivo --
export function Motivo({ codigo, textos }: { codigo: string; textos?: Record<string, string[]> }) {
  const t = textos?.[codigo];
  const chip = (
    <span className="inline-flex items-center rounded border border-regua bg-superficie-2 px-1.5 py-0.5 text-2xs text-tinta-2">
      {t?.[0] ?? codigo}
    </span>
  );
  return t?.[1] ? <Dica texto={t[1]}>{chip}</Dica> : chip;
}

// ---------------------------------------------------------------------- estados vazios --
export function EstadoVazio({
  titulo,
  descricao,
  acao,
  icone,
}: {
  titulo: string;
  descricao?: ReactNode;
  acao?: ReactNode;
  icone?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-regua-forte px-6 py-14 text-center">
      <div className="text-tinta-3">{icone ?? <SearchX className="size-8" aria-hidden />}</div>
      <h3 className="text-base font-semibold">{titulo}</h3>
      {descricao ? <p className="max-w-md text-sm text-tinta-3">{descricao}</p> : null}
      {acao ? <div className="mt-2">{acao}</div> : null}
    </div>
  );
}

export function EstadoErro({ erro, aoTentar }: { erro: unknown; aoTentar?: () => void }) {
  const e = erro instanceof ApiError ? erro : null;
  return (
    <div role="alert" className="flex flex-col items-start gap-2 rounded-lg border border-perigo/40 bg-perigo-suave px-5 py-4">
      <p className="flex items-center gap-2 font-medium">
        <FileWarning className="size-4 text-perigo" aria-hidden />
        {e?.message ?? "Não foi possível carregar estas informações."}
      </p>
      <p className="text-sm text-tinta-2">
        {e?.acao ?? "Verifique sua conexão e tente novamente. Se o problema continuar, informe o suporte."}
      </p>
      {aoTentar ? (
        <Button tamanho="sm" onClick={aoTentar}>
          Tentar novamente
        </Button>
      ) : null}
    </div>
  );
}

export function mensagemErro(e: unknown): string {
  if (e instanceof ApiError) return e.acao ? `${e.message} ${e.acao}` : e.message;
  return "Algo deu errado. Tente novamente.";
}

// ------------------------------------------------------------------- aviso permanente --
export function AvisoResponsabilidade({ className }: { className?: string }) {
  return (
    <p className={cn("text-2xs text-tinta-3", className)}>
      As sugestões são apoio à decisão. A classificação final e a responsabilidade técnica são do profissional
      responsável.
    </p>
  );
}

export function Cabecalho({
  titulo,
  subtitulo,
  acoes,
  voltar,
}: {
  titulo: ReactNode;
  subtitulo?: ReactNode;
  acoes?: ReactNode;
  voltar?: ReactNode;
}) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        {voltar ? <div className="mb-2">{voltar}</div> : null}
        <h1 className="text-xl">{titulo}</h1>
        {subtitulo ? <p className="mt-1 text-sm text-tinta-3">{subtitulo}</p> : null}
      </div>
      {acoes ? <div className="flex flex-wrap items-center gap-2">{acoes}</div> : null}
    </header>
  );
}
