import { useQuery } from "@tanstack/react-query";
import {
  ChevronDown,
  ChevronRight,
  CornerDownRight,
  FileSpreadsheet,
  GitBranch,
  Sparkles,
  X,
  Zap,
} from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { api, ok } from "@/api/client";
import type { components } from "@/api/schema";
import { EstadoErro, STATUS, type StatusItem } from "@/components/dominio";
import { Skeleton } from "@/components/ui/primitives";
import { fmtNum } from "@/lib/format";
import { cn } from "@/lib/utils";
import { AGENTES, SeloCusto, fmtUSD, type Custo } from "./FluxoAgentes";
import {
  DESTINOS_FINAIS,
  ROTEIROS,
  type DestinoFinal,
  type Ramo,
  type Tom,
} from "./RoteirosAgentes";

type Fluxo = components["schemas"]["FluxoOut"];
type CaixaResumo = components["schemas"]["CaixaResumo"];

const VAZIA: CaixaResumo = { passaram: 0, agora: 0, custo_usd: 0, chamadas: 0, destaques: [] };

/** Cor de cada tipo de agente: a faixa no topo do cartão e o círculo do número. */
const TIPO: Record<Custo, { ponto: string; faixa: string; rotulo: string }> = {
  gratis: { ponto: "bg-conferido text-white", faixa: "border-t-conferido", rotulo: "Regras fixas · grátis" },
  talvez: { ponto: "bg-conferido text-white", faixa: "border-t-conferido", rotulo: "Regras fixas · grátis" },
  ia: { ponto: "bg-caneta text-white", faixa: "border-t-caneta", rotulo: "Usa IA · custa" },
  voce: { ponto: "bg-ocre text-white", faixa: "border-t-ocre", rotulo: "Pessoa decide" },
};

const TOM: Record<Tom, string> = {
  normal: "border-regua bg-superficie text-tinta-2",
  atalho: "border-conferido/50 bg-conferido-suave text-conferido",
  desvio: "border-caneta/40 bg-caneta-suave text-caneta",
  fim: "border-regua-forte bg-superficie-2 text-tinta-2",
  humano: "border-ocre/40 bg-ocre-suave text-ocre",
};

const QUEM_RESOLVE: Record<string, string> = {
  classificado: "pronto; com aprovação automática, já vai à planilha",
  aguardando_informacao: "você responde na aba Perguntas",
  revisao_contador: "o contador confere",
  revisao_especialista: "o especialista tributário decide",
};
const RESULTADOS: StatusItem[] = ["classificado", "aguardando_informacao", "revisao_contador", "revisao_especialista"];

function nomeDestino(k: string): string {
  return AGENTES[k]?.nome ?? DESTINOS_FINAIS[k as DestinoFinal] ?? k;
}

/** Tudo o que os pedaços do diagrama precisam saber. */
type Ctx = {
  f: Fluxo;
  aberta: string | null;
  destinos: Set<string>;
  alternar: (k: string) => void;
  ir: (k: string) => void;
};

function caixa(f: Fluxo, k: string): CaixaResumo {
  if (k === "revisao") {
    const n = (f.resultados.revisao_contador ?? 0) + (f.resultados.revisao_especialista ?? 0);
    return { ...VAZIA, passaram: n };
  }
  return f.caixas[k] ?? VAZIA;
}

function destaque(f: Fluxo, k: string, rotulo: string): number | null {
  const v = f.caixas[k]?.destaques?.find((x) => x.rotulo === rotulo)?.valor;
  if (v == null) return null;
  const n = Number(String(v).replace(/\./g, ""));
  return Number.isFinite(n) ? n : null;
}

/** Quantos itens desta auditoria seguiram por um ramo (quando o sistema conta). */
function contarRamo(f: Fluxo, k: string, r: Ramo): number | null {
  if (r.conta) return destaque(f, k, r.conta);
  if (r.contaStatus) return r.contaStatus.reduce((a, s) => a + (f.resultados[s] ?? 0), 0);
  return null;
}

/** Saídas distintas do agente (para onde ele pode mandar o item), na ordem em que aparecem. */
function saidas(f: Fluxo, k: string): { vai: string; tom: Tom; n: number | null }[] {
  const mapa = new Map<string, { vai: string; tom: Tom; n: number | null }>();
  for (const d of ROTEIROS[k]?.decisoes ?? []) {
    for (const r of d.ramos) {
      if (!r.vai || r.vai === k) continue;
      const n = contarRamo(f, k, r);
      const atual = mapa.get(r.vai);
      if (atual) {
        if (n != null) atual.n = (atual.n ?? 0) + n;
      } else mapa.set(r.vai, { vai: r.vai, tom: r.tom ?? "normal", n });
    }
  }
  return [...mapa.values()];
}

// ======================================================================= tela principal ==
/** O escritório inteiro, desenhado como um fluxograma: cada agente abre as próprias decisões. */
export function FluxoAuditoria({ auditId }: { auditId: string }) {
  const q = useQuery({
    queryKey: ["fluxo", auditId],
    queryFn: () =>
      ok(
        api.GET("/api/auditorias/{audit_id}/fluxo", {
          params: { path: { audit_id: auditId } },
        }),
      ),
    refetchInterval: (qq) => (qq.state.data?.ao_vivo ? 3000 : false),
  });
  const [aberta, setAberta] = useState<string | null>(null);

  useEffect(() => {
    if (!aberta) return;
    const fechar = (e: KeyboardEvent) => e.key === "Escape" && setAberta(null);
    document.addEventListener("keydown", fechar);
    return () => document.removeEventListener("keydown", fechar);
  }, [aberta]);

  if (q.isError) return <EstadoErro erro={q.error} aoTentar={() => void q.refetch()} />;
  if (!q.data) return <Skeleton className="h-[40rem]" />;
  const f: Fluxo = q.data;
  const destinos = new Set(
    (aberta ? (ROTEIROS[aberta]?.decisoes ?? []) : []).flatMap((d) => d.ramos.map((r) => r.vai ?? "")),
  );
  const ctx: Ctx = {
    f,
    aberta,
    destinos,
    alternar: (k) => setAberta((v) => (v === k ? null : k)),
    ir: (k) => {
      if (ROTEIROS[k]) setAberta(k);
    },
  };
  const vivo = f.ao_vivo;

  return (
    <div className="flex flex-col gap-3">
      <Cabecalho f={f} />

      <Fase
        numero={1}
        titulo="Entrada"
        subtitulo="A planilha inteira, uma vez por arquivo. Nenhuma IA trabalha antes de você confirmar."
      >
        <Linha
          ctx={ctx}
          vivo={vivo}
          inicio={<Ponta icone={<FileSpreadsheet className="size-6" />} titulo="Sua planilha" texto="Excel ou CSV" />}
          chaves={["recepcionista", "conferente", "orcamentista", "voce", "distribuidor"]}
          setas={{ voce: "prévia do custo", distribuidor: "confirmado" }}
        />
      </Fase>

      <Passagem vivo={vivo} texto="cada item segue sozinho · 4 itens processados ao mesmo tempo" />

      <Fase
        numero={2}
        titulo="Cada item"
        subtitulo="O roteiro de uma ficha. Os atalhos (em verde) pulam etapas e economizam IA."
      >
        <Etapa titulo="Preparar e reconhecer">
          <Linha ctx={ctx} vivo={vivo} chaves={["arrumador", "fiscal", "arquivista"]} />
        </Etapa>
        <Passagem vivo={vivo} texto="não está no caderno de aprovados" curta />
        <Etapa titulo="Descobrir o NCM certo">
          <Linha
            ctx={ctx}
            vivo={vivo}
            chaves={["pesquisador", "identificador", "segundo_parecer", "navegador"]}
            setas={{ identificador: "há alternativas", segundo_parecer: "tocou alarme", navegador: "nenhuma serve" }}
          />
        </Etapa>
        <Atalhos ctx={ctx} />
        <Etapa titulo="Aplicar a lei ao item">
          <Linha
            ctx={ctx}
            vivo={vivo}
            chaves={["jurista", "leitor", "juiz"]}
            setas={{ leitor: "hipóteses da família", juiz: "fatos do item" }}
            fim={<Destinos f={f} />}
            setaFim="boletim"
          />
        </Etapa>
      </Fase>

      <Passagem vivo={vivo} texto="o que não saiu pronto vai para pessoas" />

      <Fase numero={3} titulo="Resolução e saída" subtitulo="Perguntas, revisão humana e a planilha final.">
        <Linha
          ctx={ctx}
          vivo={vivo}
          chaves={["secretario", "revisao", "exportacao"]}
          setas={{ revisao: "ou", exportacao: "aprovado" }}
          fim={<Ponta icone={<FileSpreadsheet className="size-6" />} titulo="Planilha final" texto="pronta para o ERP" destaque />}
          setaFim=""
        />
      </Fase>
    </div>
  );
}

function Cabecalho({ f }: { f: Fluxo }) {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
        {f.ao_vivo ? (
          <span className="inline-flex items-center gap-1.5 font-medium text-caneta">
            <span className="size-2 animate-ping rounded-full bg-caneta" aria-hidden /> Ao vivo · atualiza a cada 3
            segundos
          </span>
        ) : null}
        <span>
          <b className="num">{fmtNum(f.concluidos)}</b> de <b className="num">{fmtNum(f.total)}</b> itens concluídos
        </span>
        <span>
          Custo total: <b className="num">{fmtUSD(f.custo_usd)}</b>
        </span>
      </div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-2xs text-tinta-3">
        {(["gratis", "ia", "voce"] as Custo[]).map((c) => (
          <span key={c} className="inline-flex items-center gap-1.5">
            <span className={cn("size-3 rounded-full", TIPO[c].ponto)} aria-hidden /> {TIPO[c].rotulo}
          </span>
        ))}
        <span className="inline-flex items-center gap-1.5">
          <span className={cn("rounded-full border px-1.5", TOM.atalho)}>atalho</span> pula etapas
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className={cn("rounded-full border px-1.5", TOM.desvio)}>desvio</span> só em alguns casos
        </span>
        <span className="font-medium text-caneta">Clique num agente para abrir os caminhos que ele pode seguir.</span>
      </div>
    </div>
  );
}

// ========================================================================== estrutura ==
function Fase({
  numero,
  titulo,
  subtitulo,
  children,
}: {
  numero: number;
  titulo: string;
  subtitulo: string;
  children: ReactNode;
}) {
  return (
    <section className="rounded-xl border border-regua bg-superficie-2/50 p-3 sm:p-4">
      <header className="mb-3 flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h3 className="inline-flex items-center gap-2 text-base font-semibold">
          <span className="rounded-md border border-tinta/20 bg-superficie px-2 py-0.5 text-xs uppercase tracking-wide">
            Fase {numero}
          </span>
          {titulo}
        </h3>
        <p className="text-xs text-tinta-3">{subtitulo}</p>
      </header>
      {children}
    </section>
  );
}

function Etapa({ titulo, children }: { titulo: string; children: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-regua-forte/70 p-2 sm:p-3">
      <p className="mb-2 text-2xs font-semibold uppercase tracking-wide text-tinta-3">{titulo}</p>
      {children}
    </div>
  );
}

/** Uma fileira de agentes ligados por setas; o painel de decisões abre logo abaixo dela. */
function Linha({
  ctx,
  chaves,
  vivo,
  setas = {},
  inicio,
  fim,
  setaFim,
}: {
  ctx: Ctx;
  chaves: string[];
  vivo: boolean;
  setas?: Record<string, string>;
  inicio?: ReactNode;
  fim?: ReactNode;
  setaFim?: string;
}) {
  const aberta = ctx.aberta && chaves.includes(ctx.aberta) ? ctx.aberta : null;
  return (
    <div>
      <div className="flex flex-col items-stretch xl:flex-row">
        {inicio ? (
          <>
            {inicio}
            <Seta vivo={vivo} />
          </>
        ) : null}
        {chaves.map((k, i) => (
          <div key={k} className="contents">
            {i > 0 ? <Seta rotulo={setas[k]} vivo={vivo} /> : null}
            <CartaoAgente chave={k} ctx={ctx} />
          </div>
        ))}
        {fim ? (
          <>
            <Seta rotulo={setaFim} vivo={vivo} />
            {fim}
          </>
        ) : null}
      </div>
      {aberta ? <PainelDecisoes key={aberta} chave={aberta} ctx={ctx} /> : null}
    </div>
  );
}

function Seta({ rotulo, vivo }: { rotulo?: string; vivo: boolean }) {
  if (rotulo === "ou")
    return (
      <div className="flex items-center justify-center py-1 text-2xs font-medium text-tinta-3 xl:w-10">ou</div>
    );
  return (
    <div
      className={cn(
        "flex shrink-0 items-center justify-center gap-2 py-1 xl:w-[4.5rem] xl:flex-col xl:gap-0.5 xl:px-1 xl:py-0",
        vivo ? "text-caneta" : "text-regua-forte",
      )}
      aria-hidden
    >
      <div className="flex flex-col items-center xl:w-full xl:flex-row">
        <span className={cn("seta-v h-4 w-0.5 xl:hidden", vivo && "seta-viva")} />
        <span className={cn("seta-h hidden h-0.5 flex-1 xl:block", vivo && "seta-viva")} />
        <ChevronDown className="-mt-1.5 size-4 xl:hidden" />
        <ChevronRight className="-ml-1.5 hidden size-4 xl:block" />
      </div>
      {rotulo ? (
        <span className="text-center text-2xs leading-tight text-tinta-3 xl:order-first">{rotulo}</span>
      ) : null}
    </div>
  );
}

function Passagem({ texto, vivo, curta }: { texto: string; vivo: boolean; curta?: boolean }) {
  return (
    <div className={cn("flex flex-col items-center", vivo ? "text-caneta" : "text-regua-forte")} aria-hidden>
      <span className={cn("seta-v w-0.5", curta ? "h-3" : "h-4", vivo && "seta-viva")} />
      <span className="rounded-full border border-regua bg-superficie px-3 py-0.5 text-2xs text-tinta-2">{texto}</span>
      <span className={cn("seta-v w-0.5", curta ? "h-2" : "h-3", vivo && "seta-viva")} />
      <ChevronDown className="-mt-1.5 size-4" />
    </div>
  );
}

/** Pontas do fluxo (a planilha que entra e a que sai). */
function Ponta({
  icone,
  titulo,
  texto,
  destaque: forte,
}: {
  icone: ReactNode;
  titulo: string;
  texto: string;
  destaque?: boolean;
}) {
  return (
    <div
      className={cn(
        "flex items-center gap-3 rounded-lg border px-3 py-2 max-xl:mx-auto max-xl:w-full max-xl:max-w-xl xl:w-32 xl:flex-none xl:flex-col xl:justify-center xl:text-center",
        forte ? "border-conferido/50 bg-conferido-suave text-conferido" : "border-regua bg-superficie text-tinta-2",
      )}
    >
      {icone}
      <div>
        <p className="text-sm font-semibold">{titulo}</p>
        <p className="text-2xs text-tinta-3">{texto}</p>
      </div>
    </div>
  );
}

// ============================================================================ cartões ==
function CartaoAgente({ chave, ctx }: { chave: string; ctx: Ctx }) {
  const ag = AGENTES[chave];
  const rot = ROTEIROS[chave];
  if (!ag || !rot) return null;
  const dados = caixa(ctx.f, chave);
  const aberto = ctx.aberta === chave;
  const destino = !aberto && ctx.destinos.has(chave);
  const Icone = ag.icone;
  const agora = dados.agora ?? 0;
  const parcela = ctx.f.total ? Math.min(100, Math.round(((dados.passaram ?? 0) / ctx.f.total) * 100)) : 0;
  const lista = saidas(ctx.f, chave);
  const rotuloN = chave === "jurista" ? "com parecer" : chave === "revisao" ? "em revisão" : "passaram";
  return (
    <button
      onClick={() => ctx.alternar(chave)}
      aria-expanded={aberto}
      className={cn(
        "relative flex min-w-0 flex-col rounded-lg border border-t-4 bg-superficie p-3 text-left transition-all max-xl:mx-auto max-xl:w-full max-xl:max-w-xl xl:flex-1",
        TIPO[ag.custo].faixa,
        agora > 0 ? "border-x-caneta border-b-caneta" : "border-x-regua border-b-regua",
        aberto
          ? "shadow-painel ring-2 ring-foco"
          : destino
            ? "ring-2 ring-foco/35"
            : "hover:-translate-y-0.5 hover:shadow-painel",
        ctx.aberta && !aberto && !destino && "opacity-70",
      )}
    >
      {agora > 0 ? (
        <span className="absolute -top-3 right-2 inline-flex items-center gap-1 rounded-full bg-caneta px-2 py-px text-2xs font-semibold text-white">
          <span className="size-1.5 animate-ping rounded-full bg-white" aria-hidden /> {fmtNum(agora)} aqui agora
        </span>
      ) : null}
      {destino ? (
        <span className="absolute -top-3 left-2 rounded-full bg-foco px-2 py-px text-2xs font-semibold text-white">
          pode ir para cá
        </span>
      ) : null}
      <div className="flex items-center gap-2">
        <span
          className={cn("num grid size-7 shrink-0 place-items-center rounded-full text-xs font-semibold", TIPO[ag.custo].ponto)}
        >
          {rot.numero}
        </span>
        <Icone className="size-5 shrink-0 text-tinta-2" aria-hidden />
      </div>
      <p className="mt-1.5 text-sm font-semibold leading-tight">{ag.nome}</p>
      <p className="text-2xs leading-snug text-tinta-3">{ag.papel}</p>
      <div className="mt-1.5">
        <SeloCusto custo={ag.custo} modelo={ag.custo === "ia" ? ctx.f.modelos?.[chave] : undefined} />
      </div>
      {chave !== "exportacao" ? (
        <>
          <p className="mt-2 text-2xs text-tinta-3">
            <b className="num text-base text-tinta">{fmtNum(dados.passaram ?? 0)}</b> {rotuloN}
            {dados.chamadas ? (
              <>
                {" "}
                · <span className="num">{fmtUSD(dados.custo_usd ?? 0)}</span>
              </>
            ) : null}
          </p>
          <div className="mt-1 h-1 overflow-hidden rounded-full bg-superficie-3" aria-hidden>
            <div
              className={cn("h-full rounded-full transition-all", ag.custo === "ia" ? "bg-caneta" : ag.custo === "voce" ? "bg-ocre" : "bg-conferido")}
              style={{ width: `${parcela}%` }}
            />
          </div>
        </>
      ) : null}
      {lista.length ? (
        <ul className="mt-2 flex flex-col gap-0.5">
          {lista.slice(0, 4).map((s) => (
            <li key={s.vai} className="flex items-center gap-1 text-2xs text-tinta-3">
              <CornerDownRight className="size-3 shrink-0" aria-hidden />
              <span className={cn("truncate rounded border px-1", TOM[s.tom])}>{nomeDestino(s.vai)}</span>
              {s.n != null ? <b className="num ml-auto text-tinta-2">{fmtNum(s.n)}</b> : null}
            </li>
          ))}
        </ul>
      ) : null}
      <span className="mt-auto inline-flex items-center gap-1 pt-2 text-2xs font-medium text-caneta">
        {aberto ? "fechar decisões" : "ver decisões"}
        <ChevronDown className={cn("size-3 transition-transform", aberto && "rotate-180")} aria-hidden />
      </span>
    </button>
  );
}

/** Faixa dos atalhos: itens que chegam ao Jurista sem passar pela identificação com IA. */
function Atalhos({ ctx }: { ctx: Ctx }) {
  const memoria = destaque(ctx.f, "arquivista", "Achou no caderno (pula a identificação)") ?? 0;
  const semIa = destaque(ctx.f, "pesquisador", "Atalho: confirmados sem IA") ?? 0;
  const itens = [
    { chave: "arquivista", texto: "já aprovado antes por uma pessoa", n: memoria },
    { chave: "pesquisador", texto: "NCM do ERP confirmado sem IA", n: semIa },
  ];
  return (
    <div className="my-2 rounded-lg border-2 border-dashed border-conferido/50 bg-conferido-suave/50 px-3 py-2">
      <p className="flex flex-wrap items-center gap-1.5 text-xs font-medium text-conferido">
        <Zap className="size-4" aria-hidden /> Atalhos direto ao Jurista
        <span className="font-normal text-tinta-3">
          (os demais chegam depois de identificados pelo 10, 11 ou 12)
        </span>
      </p>
      <div className="mt-1.5 flex flex-wrap gap-2">
        {itens.map((a) => (
          <button
            key={a.chave}
            onClick={() => ctx.ir(a.chave)}
            className="inline-flex items-center gap-1.5 rounded-full border border-conferido/50 bg-superficie px-2.5 py-0.5 text-2xs text-tinta-2 hover:border-conferido"
          >
            <b className="num text-conferido">{ROTEIROS[a.chave]?.numero}</b> {AGENTES[a.chave]?.nome}: {a.texto}
            <b className="num text-conferido">{fmtNum(a.n)}</b>
            <ChevronRight className="size-3 text-conferido" aria-hidden />
            Jurista
          </button>
        ))}
      </div>
    </div>
  );
}

/** Os quatro destinos possíveis depois do Juiz. */
function Destinos({ f }: { f: Fluxo }) {
  return (
    <div className="flex flex-col gap-1.5 rounded-lg border border-regua bg-superficie p-2 max-xl:mx-auto max-xl:w-full max-xl:max-w-xl xl:w-60 xl:flex-none">
      <p className="px-1 text-2xs font-semibold uppercase tracking-wide text-tinta-3">Onde o item termina</p>
      {RESULTADOS.map((st) => {
        const s = STATUS[st];
        const Icone = s.icone;
        return (
          <div key={st} className={cn("rounded-md border px-2 py-1", s.fundo, s.borda)}>
            <p className={cn("flex items-center gap-1.5 text-xs font-medium", s.cor)}>
              <Icone className="size-3.5" aria-hidden /> {s.rotulo}
              <b className="num ml-auto text-sm">{fmtNum(f.resultados[st] ?? 0)}</b>
            </p>
            <p className="text-2xs text-tinta-3">{QUEM_RESOLVE[st]}</p>
          </div>
        );
      })}
    </div>
  );
}

// ============================================================== painel de decisões ==
function PainelDecisoes({ chave, ctx }: { chave: string; ctx: Ctx }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    ref.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, []);
  const ag = AGENTES[chave];
  const rot = ROTEIROS[chave];
  if (!ag || !rot) return null;
  const dados = caixa(ctx.f, chave);
  const Icone = ag.icone;

  return (
    <div
      ref={ref}
      className="animar-abre-painel mt-3 rounded-lg border border-foco/40 bg-superficie p-4 shadow-painel"
      role="region"
      aria-label={`Decisões de ${ag.nome}`}
    >
      <div className="flex flex-wrap items-start gap-3">
        <span className={cn("num grid size-9 shrink-0 place-items-center rounded-full text-sm font-semibold", TIPO[ag.custo].ponto)}>
          {rot.numero}
        </span>
        <div className="min-w-0 flex-1">
          <h4 className="flex flex-wrap items-center gap-2 text-base font-semibold">
            <Icone className="size-5 text-tinta-2" aria-hidden /> {ag.nome}
            <span className="text-xs font-normal text-tinta-3">{ag.papel}</span>
            <SeloCusto custo={ag.custo} modelo={ag.custo === "ia" ? ctx.f.modelos?.[chave] : undefined} />
          </h4>
          <p className="mt-0.5 text-sm text-tinta-2">{ag.faz}</p>
        </div>
        <button
          onClick={() => ctx.alternar(chave)}
          className="rounded-md p-1 text-tinta-3 hover:bg-superficie-2 hover:text-tinta"
          aria-label="Fechar"
        >
          <X className="size-4" />
        </button>
      </div>

      <div className="mt-4 grid gap-5 lg:grid-cols-[1fr_1.5fr_0.9fr]">
        <div>
          <p className="mb-2 text-2xs font-semibold uppercase tracking-wide text-tinta-3">O que faz, em ordem</p>
          <ol className="flex flex-col gap-1.5">
            {rot.passos.map((p, i) => (
              <li key={i} className="flex gap-2 text-sm text-tinta-2">
                <span className="num mt-0.5 grid size-5 shrink-0 place-items-center rounded-full bg-superficie-3 text-2xs font-semibold text-tinta-2">
                  {i + 1}
                </span>
                {p}
              </li>
            ))}
          </ol>
          <p className="mt-3 flex gap-2 rounded-md border border-caneta/30 bg-caneta-suave px-2.5 py-1.5 text-xs text-tinta-2">
            <Sparkles className="mt-0.5 size-3.5 shrink-0 text-caneta" aria-hidden />
            <span>
              <b className="text-caneta">Quando usa IA:</b> {rot.ia}
            </span>
          </p>
        </div>

        <div>
          <p className="mb-2 text-2xs font-semibold uppercase tracking-wide text-tinta-3">Caminhos que pode seguir</p>
          <div className="flex flex-col gap-4">
            {rot.decisoes.map((d, i) => (
              <div key={i}>
                <p className="flex items-start gap-2 text-sm font-medium">
                  <GitBranch className="mt-0.5 size-4 shrink-0 text-caneta" aria-hidden /> {d.pergunta}
                </p>
                <ul className="ml-2 mt-1.5 flex flex-col gap-1.5 border-l-2 border-regua pl-4">
                  {d.ramos.map((r, j) => (
                    <RamoLinha key={j} ramo={r} n={contarRamo(ctx.f, chave, r)} ctx={ctx} />
                  ))}
                </ul>
                {Array.isArray(d.nota) ? (
                  <div className="ml-2 mt-1.5 pl-4 text-2xs text-tinta-3">
                    <p className="font-medium">{d.nota[0]}</p>
                    <ul className="list-disc pl-4">
                      {d.nota.slice(1).map((n) => (
                        <li key={n}>{n}</li>
                      ))}
                    </ul>
                  </div>
                ) : d.nota ? (
                  <p className="ml-2 mt-1.5 pl-4 text-2xs italic text-tinta-3">{d.nota}</p>
                ) : null}
              </div>
            ))}
          </div>
        </div>

        <div>
          <p className="mb-2 text-2xs font-semibold uppercase tracking-wide text-tinta-3">Nesta auditoria</p>
          <dl className="flex flex-col gap-1 text-xs">
            {chave !== "exportacao" ? (
              <Numero rotulo={chave === "revisao" ? "Itens em revisão" : "Itens que passaram"} valor={fmtNum(dados.passaram ?? 0)} />
            ) : null}
            {dados.chamadas ? (
              <>
                <Numero rotulo="Chamadas de IA" valor={fmtNum(dados.chamadas)} />
                <Numero rotulo="Custo" valor={fmtUSD(dados.custo_usd ?? 0)} />
              </>
            ) : null}
            {(dados.destaques ?? []).map((x, i) => (
              <Numero key={i} rotulo={x.rotulo ?? ""} valor={x.valor ?? "—"} />
            ))}
          </dl>
        </div>
      </div>
    </div>
  );
}

function RamoLinha({ ramo, n, ctx }: { ramo: Ramo; n: number | null; ctx: Ctx }) {
  const tom = ramo.tom ?? "normal";
  const alvo = ramo.vai ? ROTEIROS[ramo.vai] : undefined;
  return (
    <li className="relative">
      <span className="absolute -left-[1.3rem] top-2 size-2 rounded-full border-2 border-regua-forte bg-superficie" aria-hidden />
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="text-sm text-tinta-2">
          <span className="text-tinta-3">se </span>
          {ramo.se}
        </span>
        {ramo.vai ? (
          alvo ? (
            <button
              onClick={() => ctx.ir(ramo.vai!)}
              className={cn("inline-flex items-center gap-1 rounded-full border px-2 py-px text-2xs font-medium hover:underline", TOM[tom])}
            >
              <ChevronRight className="size-3" aria-hidden />
              {alvo.numero}.{" "}
              {nomeDestino(ramo.vai)}
            </button>
          ) : (
            <span className={cn("inline-flex items-center gap-1 rounded-full border px-2 py-px text-2xs font-medium", TOM[tom])}>
              <ChevronRight className="size-3" aria-hidden />
              {nomeDestino(ramo.vai)}
            </span>
          )
        ) : null}
        {n != null ? (
          <span className="num text-2xs text-tinta-3">
            {fmtNum(n)} {n === 1 ? "item" : "itens"}
          </span>
        ) : null}
      </div>
    </li>
  );
}

function Numero({ rotulo, valor }: { rotulo: string; valor: string }) {
  return (
    <div className="flex justify-between gap-3 border-b border-regua/60 pb-1">
      <dt className="text-tinta-3">{rotulo}</dt>
      <dd className="num text-right font-medium text-tinta-2">{valor}</dd>
    </div>
  );
}
