/** Componentes do domínio: status, códigos, confiança, motivos, estados vazios e de erro. */
import { CheckCircle2, CircleDashed, CircleHelp, Clock3, FileWarning, MinusCircle, Scale, SearchX, Stamp, UserCheck, XCircle } from "lucide-react";
import type { ReactNode } from "react";
import { ApiError } from "@/api/client";
import { cn } from "@/lib/utils";
import { fmtCodigo } from "@/lib/format";
import { Button, Dica } from "./ui/primitives";

// -------------------------------------------------------------------------------- status --
export const STATUS = {
  classificado: { rotulo: "Classificado", icone: CheckCircle2, cor: "text-conferido", fundo: "bg-conferido-suave", borda: "border-conferido/40" },
  aguardando_informacao: { rotulo: "Aguardando informação", icone: CircleHelp, cor: "text-ocre", fundo: "bg-ocre-suave", borda: "border-ocre/40" },
  revisao_contador: { rotulo: "Revisão do contador", icone: UserCheck, cor: "text-caneta", fundo: "bg-caneta-suave", borda: "border-caneta/40" },
  revisao_especialista: { rotulo: "Revisão do especialista", icone: Scale, cor: "text-perigo", fundo: "bg-perigo-suave", borda: "border-perigo/40" },
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

export function SeloRevisao({ status, automatico }: { status: string; automatico?: boolean }) {
  if (status === "aprovado" && automatico)
    return (
      <span className="inline-flex items-center gap-1 text-2xs font-semibold uppercase tracking-wide text-conferido">
        <Stamp className="size-3.5" aria-hidden /> Aprovado automaticamente
      </span>
    );
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
export const CONFIANCA: Record<string, { rotulo: string; cor: string; ajuda: string }> = {
  alta: { rotulo: "Alta", cor: "text-conferido", ajuda: "Todas as dimensões foram confirmadas." },
  media: { rotulo: "Média", cor: "text-caneta", ajuda: "Alguma dimensão pede conferência de uma pessoa." },
  incompleta: { rotulo: "Incompleta", cor: "text-ocre", ajuda: "Falta uma informação que muda o enquadramento." },
  baixa: { rotulo: "Baixa", cor: "text-perigo", ajuda: "Há falha em alguma dimensão (identificação, regra ou fonte)." },
};

/** Confiança explicável: um nível em palavras, nunca um número solto. */
export function ConfiancaGlobal({ valor, className }: { valor: string | null | undefined; className?: string }) {
  const c = valor ? CONFIANCA[valor] : undefined;
  if (!c) return <span className="text-tinta-3">—</span>;
  const barras = { alta: 3, media: 2, incompleta: 1, baixa: 1 }[valor as "alta"] ?? 0;
  return (
    <Dica texto={c.ajuda}>
      <span tabIndex={0} className={cn("inline-flex items-center gap-1.5 text-xs font-medium", c.cor, className)}>
        <span className="flex items-end gap-0.5" aria-hidden>
          {[1, 2, 3].map((n) => (
            <span key={n} className={cn("w-1 rounded-sm", n <= barras ? "bg-current" : "bg-superficie-3")} style={{ height: 4 + n * 3 }} />
          ))}
        </span>
        {c.rotulo}
      </span>
    </Dica>
  );
}

export const SITUACAO_DIMENSAO: Record<string, { rotulo: string; icone: typeof CheckCircle2; cor: string }> = {
  ok: { rotulo: "Confirmado", icone: CheckCircle2, cor: "text-conferido" },
  atencao: { rotulo: "Conferir", icone: UserCheck, cor: "text-caneta" },
  pendente: { rotulo: "Falta informação", icone: CircleHelp, cor: "text-ocre" },
  falha: { rotulo: "Não confirmado", icone: XCircle, cor: "text-perigo" },
  nao_aplicavel: { rotulo: "Não se aplica", icone: MinusCircle, cor: "text-tinta-3" },
};

/** Relatório de confiança por dimensão (identificação, código, regra, fonte...). */
export function RelatorioConfianca({ dimensoes }: { dimensoes: { chave?: string; rotulo: string; situacao: string; texto: string }[] }) {
  return (
    <ul className="divide-y divide-regua rounded-md border border-regua">
      {dimensoes.map((d) => {
        const s = SITUACAO_DIMENSAO[d.situacao] ?? SITUACAO_DIMENSAO.nao_aplicavel!;
        const I = s.icone;
        return (
          <li key={d.chave ?? d.rotulo} className="grid grid-cols-[10.5rem_1fr] gap-3 px-3 py-2 text-sm">
            <span className="flex items-center gap-1.5 font-medium">
              <I className={cn("size-4 shrink-0", s.cor)} aria-hidden />
              {d.rotulo}
            </span>
            <span className="text-xs text-tinta-2">
              <span className={cn("mr-1.5 font-medium", s.cor)}>{s.rotulo}</span>
              {d.texto}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

export const ORIGEM_FATO: Record<string, string> = {
  usuario: "informado por pessoa",
  erp: "planilha do ERP",
  descricao: "explícito na descrição",
  cadastro: "cadastro da empresa",
};

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
