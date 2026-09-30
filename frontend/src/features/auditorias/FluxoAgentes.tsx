import { useQuery } from "@tanstack/react-query";
import {
  ArrowDown,
  Compass,
  ArrowRight,
  BookOpenText,
  Brain,
  Calculator,
  ChevronDown,
  CircleHelp,
  ClipboardCheck,
  FileInput,
  FileSearch,
  Gavel,
  Hand,
  Inbox,
  Library,
  MailQuestion,
  Search,
  ShieldCheck,
  Split,
  Stethoscope,
  UserRound,
  type LucideIcon,
} from "lucide-react";
import { useState, type ReactNode } from "react";
import { api, ok } from "@/api/client";
import type { components } from "@/api/schema";
import { EstadoErro, STATUS, type StatusItem } from "@/components/dominio";
import { Skeleton } from "@/components/ui/primitives";
import { fmtNum, fmtUSD as fmtUSDBase } from "@/lib/format";
import { cn } from "@/lib/utils";

type Custo = "gratis" | "ia" | "voce";
type Agente = {
  nome: string;
  papel: string;
  faz: string;
  custo: Custo;
  icone: LucideIcon;
};

/** Cada caixa do sistema descrita como o funcionário que ela substitui. */
export const AGENTES: Record<string, Agente> = {
  recepcionista: {
    nome: "Recepcionista",
    papel: "lê a planilha",
    faz: "Abre o arquivo, recusa macros e liga cada coluna ao campo certo.",
    custo: "gratis",
    icone: Inbox,
  },
  conferente: {
    nome: "Conferente",
    papel: "confere linha por linha",
    faz: "Anota linhas vazias, NCM com formato estranho, GTIN inválido e duplicados, e guarda cada linha como uma ficha.",
    custo: "gratis",
    icone: ClipboardCheck,
  },
  orcamentista: {
    nome: "Orçamentista",
    papel: "prevê custo e tempo",
    faz: "Conta itens já conhecidos e famílias já estudadas e estima quanto a IA vai custar.",
    custo: "gratis",
    icone: Calculator,
  },
  voce: {
    nome: "Você",
    papel: "confirma o custo",
    faz: "Escolhe tempo real ou lote e aperta “Confirmar e iniciar”. Nenhuma IA trabalha antes disso.",
    custo: "voce",
    icone: Hand,
  },
  distribuidor: {
    nome: "Distribuidor",
    papel: "reparte o trabalho",
    faz: "Separa as fichas em pacotes de 10 e põe numa fila; várias mesas trabalham ao mesmo tempo.",
    custo: "gratis",
    icone: Split,
  },
  arrumador: {
    nome: "Arrumador",
    papel: "limpa a descrição",
    faz: "Tira a marca, acentos e abreviações para deixar a descrição legível.",
    custo: "gratis",
    icone: FileInput,
  },
  fiscal: {
    nome: "Fiscal da tabela",
    papel: "confere o NCM do ERP",
    faz: "Verifica na tabela oficial se o NCM informado existe, está completo e vale na data.",
    custo: "gratis",
    icone: ShieldCheck,
  },
  arquivista: {
    nome: "Arquivista",
    papel: "procura itens já aprovados",
    faz: "Abre o caderno de itens aprovados por pessoas nesta empresa. Se achar, pula a identificação.",
    custo: "gratis",
    icone: Library,
  },
  pesquisador: {
    nome: "Pesquisador",
    papel: "monta a prova de múltipla escolha",
    faz: "Busca pelo nome (por palavras e pelo sentido) os NCMs possíveis e acrescenta o do ERP e seus irmãos.",
    custo: "gratis",
    icone: Search,
  },
  identificador: {
    nome: "Identificador",
    papel: "responde a prova",
    faz: "A IA escolhe o NCM certo entre as alternativas oficiais, com justificativa e grau de certeza.",
    custo: "ia",
    icone: FileSearch,
  },
  segundo_parecer: {
    nome: "Segundo parecer",
    papel: "confere quando há dúvida",
    faz: "Uma IA mais forte revisa a resposta quando algum alarme toca. O NCM final é o dela.",
    custo: "ia",
    icone: Stethoscope,
  },
  navegador: {
    nome: "Navegador da NCM",
    papel: "procura o NCM que faltou",
    faz: "Quando o item fica sem NCM, desce pela tabela oficial (capítulo → posição → código) e sugere um código para o contador confirmar.",
    custo: "ia",
    icone: Compass,
  },
  jurista: {
    nome: "Jurista",
    papel: "estuda a lei da família",
    faz: "Lê a lei, a correlação oficial e a tabela cClassTrib e escreve hipóteses “se… então…”. Uma vez por NCM.",
    custo: "ia",
    icone: BookOpenText,
  },
  leitor: {
    nome: "Leitor de fatos",
    papel: "procura as respostas na descrição",
    faz: "Separa o que está escrito (vira fato) do que é palpite (vira só sugestão).",
    custo: "ia",
    icone: Brain,
  },
  juiz: {
    nome: "Juiz",
    papel: "aplica o parecer ao item",
    faz: "Percorre as hipóteses com os fatos, preenche o boletim de 10 notas e decide o destino. Sem IA.",
    custo: "gratis",
    icone: Gavel,
  },
  secretario: {
    nome: "Secretário",
    papel: "junta as perguntas",
    faz: "Agrupa perguntas iguais por categoria ou família para você responder uma vez só.",
    custo: "gratis",
    icone: MailQuestion,
  },
};

/** Custos de uma chamada costumam ser frações de centavo: mostra "< US$ 0,01" em vez de zero. */
function fmtUSD(v: number | null | undefined): string {
  const n = Number(v ?? 0);
  return n > 0 && n < 0.01 ? "< US$ 0,01" : fmtUSDBase(n);
}

const PLANILHA = [
  "recepcionista",
  "conferente",
  "orcamentista",
  "voce",
  "distribuidor",
];
const POR_ITEM = [
  "arrumador",
  "fiscal",
  "arquivista",
  "pesquisador",
  "identificador",
  "segundo_parecer",
  "navegador",
  "jurista",
  "leitor",
  "juiz",
  "secretario",
];
const RESULTADOS: StatusItem[] = [
  "classificado",
  "aguardando_informacao",
  "revisao_contador",
  "revisao_especialista",
];

const CUSTO: Record<Custo, { rotulo: string; classe: string }> = {
  gratis: { rotulo: "grátis · sem IA", classe: "border-regua text-tinta-3" },
  ia: {
    rotulo: "IA",
    classe: "border-caneta/40 bg-caneta-suave text-caneta",
  },
  voce: { rotulo: "pessoa", classe: "border-ocre/40 bg-ocre-suave text-ocre" },
};

/** Nome curto do modelo que de fato respondeu (a configuração pode ter mudado desde então). */
function nomeModelo(modelo: unknown): string {
  const m = String(modelo ?? "");
  if (m.includes("haiku")) return "Haiku";
  if (m.includes("sonnet")) return "Sonnet";
  if (m.includes("opus")) return "Opus";
  return m;
}

function SeloCusto({ custo, modelo }: { custo: Custo; modelo?: unknown }) {
  const c = CUSTO[custo];
  return (
    <span
      className={cn(
        "whitespace-nowrap rounded-full border px-1.5 py-px text-2xs",
        c.classe,
      )}
    >
      {modelo ? `IA · ${nomeModelo(modelo)}` : c.rotulo}
    </span>
  );
}

function Legenda() {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-2xs text-tinta-3">
      <span className="flex items-center gap-1.5">
        <SeloCusto custo="gratis" /> funcionário comum: regras fixas, não custa
        nada
      </span>
      <span className="flex items-center gap-1.5">
        <SeloCusto custo="ia" /> usa IA (custa); o selo mostra o modelo, escolhido em “Modelos de IA”
      </span>
    </div>
  );
}

// ================================================================== caminho de um item ==
type Caminho = components["schemas"]["CaminhoOut"];
type Passo = components["schemas"]["PassoOut"];

type Situacao = { rotulo: string; ponto: string; cartao: string };
const SITUACAO = {
  feito: {
    rotulo: "passou aqui",
    ponto: "border-conferido bg-conferido text-white",
    cartao: "border-regua bg-superficie",
  },
  atual: {
    rotulo: "está aqui agora",
    ponto: "border-caneta bg-caneta text-white animate-pulse",
    cartao: "border-caneta bg-caneta-suave shadow-sm",
  },
  falhou: {
    rotulo: "não conseguiu",
    ponto: "border-perigo bg-perigo text-white",
    cartao: "border-perigo/40 bg-perigo-suave",
  },
  pulado: {
    rotulo: "pulou",
    ponto: "border-dashed border-regua-forte bg-superficie text-tinta-3",
    cartao: "border-dashed border-regua bg-transparent opacity-70",
  },
  aguardando: {
    rotulo: "ainda não chegou",
    ponto: "border-regua bg-superficie text-tinta-3",
    cartao: "border-regua bg-transparent opacity-60",
  },
} satisfies Record<string, Situacao>;

/** O caminho do item pelos agentes: por onde passou, onde pulou e o que cada um fez. */
export function CaminhoItem({ itemId }: { itemId: string }) {
  const q = useQuery({
    queryKey: ["caminho", itemId],
    queryFn: () =>
      ok(
        api.GET("/api/itens/{item_id}/caminho", {
          params: { path: { item_id: itemId } },
        }),
      ),
    refetchInterval: (qq) => (qq.state.data?.em_andamento ? 2000 : false),
  });
  if (q.isError)
    return <EstadoErro erro={q.error} aoTentar={() => void q.refetch()} />;
  if (!q.data) return <Skeleton className="h-[32rem]" />;
  const c: Caminho = q.data;
  const passaram = c.passos.filter(
    (p) => p.situacao === "feito" || p.situacao === "falhou",
  ).length;
  const indice = new Map(c.passos.map((p, i) => [p.caixa, i]));
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-tinta-2">
        {c.em_andamento ? (
          <span className="inline-flex items-center gap-1.5 font-medium text-caneta">
            <span
              className="size-2 animate-ping rounded-full bg-caneta"
              aria-hidden
            />{" "}
            {c.status === "pendente"
              ? "Na fila: aguardando um agente livre para começar"
              : `Ao vivo: o item está com ${AGENTES[c.caixa_atual ?? ""]?.nome ?? "o próximo agente"}`}
          </span>
        ) : (
          <span>
            Passou por <b className="num">{passaram}</b> de {c.passos.length}{" "}
            agentes
          </span>
        )}
        <span>
          Custo deste item: <b className="num">{fmtUSD(c.custo_usd)}</b>
        </span>
      </div>
      <Legenda />
      <ol className="relative mt-1">
        <li className="flex gap-3 pb-3">
          <Trilho
            ativo
            ponto={<Inbox className="size-3.5" />}
            classePonto="border-conferido bg-conferido text-white"
          />
          <p className="pt-1 text-2xs text-tinta-3">
            Antes daqui, a planilha inteira passou pelo Recepcionista,
            Conferente, Orçamentista, por você (confirmar o custo) e pelo
            Distribuidor. Veja na aba <b>Fluxo dos agentes</b> da auditoria.
          </p>
        </li>
        {c.passos.map((p, i) => {
          // O trilho abaixo da caixa i fica verde se o item passou por ali, mesmo pulando caixas no meio.
          const ativo = c.passos.some(
            (a, j) =>
              j <= i &&
              (a.situacao === "feito" || a.situacao === "falhou") &&
              !!a.proximo &&
              (a.proximo === "resultado" || (indice.get(a.proximo) ?? -1) > i),
          );
          return (
            <PassoCartao
              key={p.caixa}
              passo={p}
              numero={i + 1}
              trilhoAtivo={ativo}
            />
          );
        })}
        <li className="flex gap-3">
          <Trilho
            ponto={<ArrowDown className="size-3.5" />}
            classePonto="border-tinta bg-tinta text-papel"
            fim
          />
          <div className="pt-0.5">
            <p className="text-2xs text-tinta-3">Resultado</p>
            {c.em_andamento ? (
              <p className="text-sm text-tinta-3">Ainda processando…</p>
            ) : (
              <SeloResultado status={c.status} />
            )}
          </div>
        </li>
      </ol>
    </div>
  );
}

function Trilho({
  ponto,
  classePonto,
  ativo,
  fim,
}: {
  ponto: ReactNode;
  classePonto: string;
  ativo?: boolean;
  fim?: boolean;
}) {
  return (
    <div className="relative flex w-7 shrink-0 flex-col items-center">
      <span
        className={cn(
          "z-10 grid size-7 place-items-center rounded-full border-2 text-2xs font-semibold",
          classePonto,
        )}
      >
        {ponto}
      </span>
      {!fim ? (
        <span
          className={cn(
            "absolute top-7 bottom-0 w-0.5",
            ativo ? "bg-conferido" : "bg-regua",
          )}
          aria-hidden
        />
      ) : null}
    </div>
  );
}

function PassoCartao({
  passo,
  numero,
  trilhoAtivo,
}: {
  passo: Passo;
  numero: number;
  trilhoAtivo: boolean;
}) {
  const ag = AGENTES[passo.caixa];
  const s: Situacao =
    SITUACAO[passo.situacao as keyof typeof SITUACAO] ?? SITUACAO.aguardando;
  const [aberto, setAberto] = useState(
    passo.situacao === "atual" || passo.situacao === "falhou",
  );
  const Icone = ag?.icone ?? CircleHelp;
  const temDetalhes = passo.detalhes.length > 0;
  const destino =
    passo.proximo === "resultado"
      ? "resultado"
      : passo.proximo
        ? AGENTES[passo.proximo]?.nome
        : null;
  return (
    <li className="flex gap-3 pb-3">
      <Trilho
        ponto={<span className="num">{numero}</span>}
        classePonto={s.ponto}
        ativo={trilhoAtivo}
      />
      <div
        className={cn("min-w-0 flex-1 rounded-lg border px-3 py-2", s.cartao)}
      >
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <Icone className="size-4 text-tinta-2" aria-hidden />
          <span className="text-sm font-semibold">
            {ag?.nome ?? passo.caixa}
          </span>
          <span className="text-2xs text-tinta-3">{ag?.papel}</span>
          {ag ? <SeloCusto custo={ag.custo} modelo={passo.ia?.modelo} /> : null}
          <span
            className={cn(
              "ml-auto text-2xs font-medium",
              passo.situacao === "atual"
                ? "text-caneta"
                : passo.situacao === "falhou"
                  ? "text-perigo"
                  : "text-tinta-3",
            )}
          >
            {s.rotulo}
          </span>
        </div>
        <p
          className={cn(
            "mt-1 text-sm",
            passo.situacao === "pulado" || passo.situacao === "aguardando"
              ? "text-tinta-3"
              : "text-tinta",
          )}
        >
          {passo.resumo}
        </p>
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-2xs text-tinta-3">
          {passo.ia ? <InfoIA ia={passo.ia} /> : null}
          {destino && passo.situacao !== "pulado" ? (
            <span className="inline-flex items-center gap-1">
              <ArrowRight className="size-3" aria-hidden /> entregou para:{" "}
              <b className="text-tinta-2">{destino}</b>
            </span>
          ) : null}
          {temDetalhes ? (
            <button
              className="ml-auto inline-flex items-center gap-1 text-caneta hover:underline"
              onClick={() => setAberto((v) => !v)}
              aria-expanded={aberto}
            >
              {aberto ? "esconder" : "ver o que fez"}{" "}
              <ChevronDown
                className={cn(
                  "size-3 transition-transform",
                  aberto && "rotate-180",
                )}
                aria-hidden
              />
            </button>
          ) : null}
        </div>
        {aberto && temDetalhes ? (
          <dl className="mt-2 grid gap-1 border-t border-regua pt-2 text-xs">
            {passo.detalhes.map((d, i) => (
              <div key={i} className="grid gap-x-3 sm:grid-cols-[11rem_1fr]">
                <dt className="text-tinta-3">{d.rotulo}</dt>
                <dd className="break-words text-tinta-2">{d.valor}</dd>
              </div>
            ))}
          </dl>
        ) : null}
        {passo.situacao !== "pulado" && ag ? (
          <p className="mt-1 hidden text-2xs text-tinta-3 sm:block">{ag.faz}</p>
        ) : null}
      </div>
    </li>
  );
}

function InfoIA({ ia }: { ia: Record<string, unknown> }) {
  const nome = nomeModelo(ia.modelo);
  if (ia.reaproveitada)
    return (
      <span className="text-conferido">
        {nome}: resposta reaproveitada, grátis (valia{" "}
        {fmtUSD(Number(ia.custo_original_usd ?? 0))})
      </span>
    );
  if (ia.status === "enviada" || ia.status === "pendente")
    return (
      <span className="text-caneta">{nome}: aguardando a resposta da IA…</span>
    );
  return (
    <span>
      {nome}:{" "}
      <b className="num text-tinta-2">{fmtUSD(Number(ia.custo_usd ?? 0))}</b>
      {ia.compartilhada ? " (parte deste item no parecer da família)" : ""}
    </span>
  );
}

function SeloResultado({ status }: { status: string }) {
  const s = STATUS[status as StatusItem] ?? STATUS.pendente;
  const Icone = s.icone;
  return (
    <span
      className={cn(
        "mt-0.5 inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-sm font-medium",
        s.cor,
        s.fundo,
        s.borda,
      )}
    >
      <Icone className="size-4" aria-hidden /> {s.rotulo}
    </span>
  );
}

// =============================================================== visão geral (auditoria) ==
type Fluxo = components["schemas"]["FluxoOut"];
type CaixaResumo = components["schemas"]["CaixaResumo"];

/** O escritório inteiro: quantos itens passaram por cada agente, quantos estão lá agora e quanto custou. */
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
  if (q.isError)
    return <EstadoErro erro={q.error} aoTentar={() => void q.refetch()} />;
  if (!q.data) return <Skeleton className="h-[40rem]" />;
  const f: Fluxo = q.data;
  const cx = (k: string): CaixaResumo =>
    f.caixas[k] ?? {
      passaram: 0,
      agora: 0,
      custo_usd: 0,
      chamadas: 0,
      destaques: [],
    };
  const alternar = (k: string) => setAberta((v) => (v === k ? null : k));

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
        {f.ao_vivo ? (
          <span className="inline-flex items-center gap-1.5 font-medium text-caneta">
            <span
              className="size-2 animate-ping rounded-full bg-caneta"
              aria-hidden
            />{" "}
            Ao vivo · atualiza a cada 3 segundos
          </span>
        ) : null}
        <span>
          <b className="num">{fmtNum(f.concluidos)}</b> de{" "}
          <b className="num">{fmtNum(f.total)}</b> itens concluídos
        </span>
        <span>
          Custo total: <b className="num">{fmtUSD(f.custo_usd)}</b>
        </span>
        <span className="text-2xs text-tinta-3">
          Clique numa caixa para ver os números dela. Para ver o caminho de um
          item, abra o item e escolha “Caminho pelos agentes”.
        </span>
      </div>
      <Legenda />

      <section>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-tinta-3">
          1 · A planilha inteira (uma vez por arquivo)
        </h3>
        <div className="flex flex-col items-stretch gap-2 xl:flex-row xl:items-start">
          {PLANILHA.map((k, i) => (
            <div
              key={k}
              className="flex flex-col items-center gap-2 xl:flex-1 xl:flex-row"
            >
              <CaixaGeral
                chave={k}
                dados={cx(k)}
                aberta={aberta === k}
                aoClicar={() => alternar(k)}
                total={f.total}
              />
              {i < PLANILHA.length - 1 ? <Seta horizontal /> : null}
            </div>
          ))}
        </div>
      </section>

      <div className="flex justify-center">
        <span className="inline-flex items-center gap-1.5 rounded-full border border-regua bg-superficie-2 px-3 py-1 text-2xs text-tinta-2">
          <ArrowDown className="size-3" aria-hidden /> cada ficha segue sozinha
          pelo roteiro abaixo
        </span>
      </div>

      <section>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-tinta-3">
          2 · Cada item (o roteiro do Gerente)
        </h3>
        <div className="mx-auto flex max-w-3xl flex-col items-stretch">
          {POR_ITEM.map((k, i) => (
            <div key={k} className="flex flex-col items-stretch">
              <div
                className={cn(
                  k === "segundo_parecer" && "sm:ml-12",
                  k === "secretario" && "sm:ml-12",
                  k === "navegador" && "sm:ml-12",
                )}
              >
                {k === "segundo_parecer" ? (
                  <Desvio texto="só quando toca um alarme" />
                ) : null}
                {k === "secretario" ? (
                  <Desvio texto="só quando falta informação" />
                ) : null}
                {k === "navegador" ? (
                  <Desvio texto="só quando o item ficou sem NCM" />
                ) : null}
                <CaixaGeral
                  chave={k}
                  dados={cx(k)}
                  aberta={aberta === k}
                  aoClicar={() => alternar(k)}
                  total={f.total}
                  modelo={f.modelos?.[k]}
                />
              </div>
              {i < POR_ITEM.length - 1 ? <Atalhos chave={k} f={f} /> : null}
            </div>
          ))}
        </div>
      </section>

      <section>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-tinta-3">
          3 · Onde cada item terminou
        </h3>
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          {RESULTADOS.map((st) => {
            const s = STATUS[st];
            const Icone = s.icone;
            return (
              <div
                key={st}
                className={cn("rounded-lg border px-3 py-2", s.fundo, s.borda)}
              >
                <p
                  className={cn(
                    "flex items-center gap-1.5 text-sm font-medium",
                    s.cor,
                  )}
                >
                  <Icone className="size-4" aria-hidden /> {s.rotulo}
                </p>
                <p className="num mt-1 text-2xl font-semibold">
                  {fmtNum(f.resultados[st] ?? 0)}
                </p>
                <p className="text-2xs text-tinta-3">{QUEM_RESOLVE[st]}</p>
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}

const QUEM_RESOLVE: Record<string, string> = {
  classificado: "ninguém precisa fazer nada",
  aguardando_informacao: "você responde na aba Perguntas",
  revisao_contador: "o contador confere",
  revisao_especialista: "o especialista tributário decide",
};

function Seta({ horizontal }: { horizontal?: boolean }) {
  return horizontal ? (
    <>
      <ArrowDown
        className="size-4 shrink-0 text-regua-forte xl:hidden"
        aria-hidden
      />
      <ArrowRight
        className="hidden size-4 shrink-0 text-regua-forte xl:block"
        aria-hidden
      />
    </>
  ) : (
    <ArrowDown className="mx-auto my-1 size-4 text-regua-forte" aria-hidden />
  );
}

function Desvio({ texto }: { texto: string }) {
  return <p className="mb-1 text-2xs italic text-tinta-3">↳ desvio: {texto}</p>;
}

/** Setas entre as caixas, com os atalhos do roteiro (quantos itens pularam caixas). */
function Atalhos({ chave, f }: { chave: string; f: Fluxo }) {
  const d = (k: string, rotulo: string) =>
    Number(
      f.caixas[k]?.destaques
        ?.find((x) => x.rotulo === rotulo)
        ?.valor?.replace(/\./g, "") ?? 0,
    );
  const atalhos: string[] = [];
  if (chave === "arquivista") {
    const n = d("arquivista", "Achou no caderno (pula a identificação)");
    if (n) atalhos.push(`${fmtNum(n)} já conhecidos pularam direto ao Jurista`);
  }
  if (chave === "pesquisador") {
    const n = d("pesquisador", "Atalho: confirmados sem IA");
    if (n)
      atalhos.push(`${fmtNum(n)} confirmados sem IA pularam direto ao Jurista`);
  }
  if (chave === "fiscal") {
    const n = d("fiscal", "Base oficial incompleta");
    if (n)
      atalhos.push(
        `${fmtNum(n)} foram direto ao Juiz (base oficial incompleta)`,
      );
  }
  return (
    <div className="flex items-center justify-center gap-2 py-1">
      <ArrowDown className="size-4 text-regua-forte" aria-hidden />
      {atalhos.map((a) => (
        <span
          key={a}
          className="rounded-full border border-dashed border-conferido/50 px-2 py-px text-2xs text-conferido"
        >
          atalho: {a}
        </span>
      ))}
    </div>
  );
}

function CaixaGeral({
  chave,
  dados,
  aberta,
  aoClicar,
  total,
  modelo,
}: {
  chave: string;
  dados: CaixaResumo;
  aberta: boolean;
  aoClicar: () => void;
  total: number;
  modelo?: string;
}) {
  const ag = AGENTES[chave];
  const Icone = ag?.icone ?? UserRound;
  const agora = dados.agora ?? 0;
  const parcela = total
    ? Math.min(100, Math.round(((dados.passaram ?? 0) / total) * 100))
    : 0;
  return (
    <button
      onClick={aoClicar}
      aria-expanded={aberta}
      className={cn(
        "relative w-full min-w-0 rounded-lg border bg-superficie px-3 py-2 text-left transition-colors hover:border-regua-forte",
        agora > 0 ? "border-caneta shadow-sm" : "border-regua",
        aberta && "ring-2 ring-foco",
      )}
    >
      {agora > 0 ? (
        <span className="absolute -top-2 right-2 inline-flex items-center gap-1 rounded-full bg-caneta px-2 py-px text-2xs font-semibold text-white">
          <span
            className="size-1.5 animate-ping rounded-full bg-white"
            aria-hidden
          />{" "}
          {fmtNum(agora)} aqui agora
        </span>
      ) : null}
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <Icone className="size-4 text-tinta-2" aria-hidden />
        <span className="text-sm font-semibold">{ag?.nome ?? chave}</span>
        <span className="text-2xs text-tinta-3">{ag?.papel}</span>
        {ag ? <SeloCusto custo={ag.custo} modelo={modelo} /> : null}
      </div>
      <p className="mt-1 text-xs text-tinta-2">{ag?.faz}</p>
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-2xs text-tinta-3">
        <span>
          <b className="num text-sm text-tinta">
            {fmtNum(dados.passaram ?? 0)}
          </b>{" "}
          {chave === "jurista" ? "itens com parecer" : "passaram"}
        </span>
        {dados.chamadas ? (
          <span>
            <b className="num text-tinta-2">{fmtNum(dados.chamadas)}</b>{" "}
            chamadas de IA ·{" "}
            <b className="num text-tinta-2">{fmtUSD(dados.custo_usd ?? 0)}</b>
          </span>
        ) : null}
      </div>
      <div
        className="mt-1.5 h-1 overflow-hidden rounded-full bg-superficie-3"
        aria-hidden
      >
        <div
          className={cn(
            "h-full rounded-full",
            ag?.custo === "ia"
              ? "bg-caneta"
              : "bg-conferido",
          )}
          style={{ width: `${parcela}%` }}
        />
      </div>
      {aberta && dados.destaques?.length ? (
        <dl className="mt-2 grid gap-1 border-t border-regua pt-2 text-xs">
          {dados.destaques.map((x, i) => (
            <div key={i} className="flex justify-between gap-3">
              <dt className="text-tinta-3">{x.rotulo}</dt>
              <dd className="num text-right font-medium text-tinta-2">
                {x.valor}
              </dd>
            </div>
          ))}
        </dl>
      ) : null}
    </button>
  );
}
