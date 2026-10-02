import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "@tanstack/react-router";
import { ArrowLeft, Download, Keyboard, Loader2, PauseCircle, Play, Radio, RefreshCcw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { api, ok, tokenValido } from "@/api/client";
import { useAuth } from "@/auth/auth";
import { Cabecalho, EstadoErro, mensagemErro, STATUS } from "@/components/dominio";
import { Aviso, Button, Painel, Progresso, Skeleton, Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/primitives";
import { assinarSSE } from "@/lib/sse";
import { fmtData, fmtNum, fmtUSD, plural } from "@/lib/format";
import { cn } from "@/lib/utils";
import { ETAPAS, ROTULO_STATUS_AUDITORIA, useAuditoria, type Auditoria } from "./comum";
import { AjustesCadastroPainel } from "./AjustesCadastroPainel";
import { Passos } from "./NovaAuditoriaPage";
import { FamiliasPainel } from "./FamiliasPainel";
import { FluxoAuditoria } from "./FluxoDiagrama";
import { PerguntasPainel } from "./PerguntasPainel";
import { Resultado } from "./Resultado";

export function AuditoriaPage() {
  const { id } = useParams({ strict: false }) as { id: string };
  const qc = useQueryClient();
  const a = useAuditoria(id, (q) => (q.state.data?.status === "preparando" ? 2000 : false));
  const status = a.data?.status;
  const aoVivo = status === "processando" || status === "aguardando_lote";

  // Progresso em tempo real (SSE). Atualiza os contadores e, periodicamente, a lista de itens.
  useEffect(() => {
    if (!aoVivo && status !== "preparando") return;
    let ultimoRefetch = 0;
    return assinarSSE(`/api/auditorias/${id}/eventos`, tokenValido, (ev) => {
      if (ev.event === "ping") return;
      try {
        const dados = JSON.parse(ev.data);
        if (ev.event === "progresso") {
          qc.setQueryData(["auditoria", id], (antigo: Auditoria | undefined) =>
            antigo ? { ...antigo, contadores: dados.contadores, custo_usd: dados.custo_usd } : antigo,
          );
        }
        if (ev.event === "status") void qc.invalidateQueries({ queryKey: ["auditoria", id] });
        const agora = Date.now();
        if ((ev.event === "item" || ev.event === "status") && agora - ultimoRefetch > 5000) {
          ultimoRefetch = agora;
          void qc.invalidateQueries({ queryKey: ["itens", id] });
        }
      } catch {
        /* evento malformado: ignora */
      }
    });
  }, [id, aoVivo, status, qc]);

  if (a.isError) return <EstadoErro erro={a.error} aoTentar={() => void a.refetch()} />;
  if (!a.data) return <Skeleton className="h-96" />;
  const d = a.data;

  const voltar = (
    <Link to="/auditorias" className="inline-flex items-center gap-1 text-xs text-tinta-3 hover:text-tinta">
      <ArrowLeft className="size-3.5" /> Auditorias
    </Link>
  );
  const subtitulo = (
    <span>
      {d.empresa} · vigência {fmtData(d.data_referencia)} · {ROTULO_STATUS_AUDITORIA[d.status] ?? d.status}
    </span>
  );

  if (d.status === "preparando") {
    return (
      <>
        <Cabecalho voltar={voltar} titulo={d.nome} subtitulo={subtitulo} />
        <Passos atual={2} />
        <Painel className="flex items-center gap-3 p-6">
          <Loader2 className="size-5 animate-spin text-tinta-3" aria-hidden />
          <p>Lendo a planilha, limpando os dados e conferindo os códigos na tabela oficial. Nenhuma IA é usada nesta etapa.</p>
        </Painel>
      </>
    );
  }
  if (["pronta", "pausada_orcamento", "pausada_ia", "falhou", "rascunho"].includes(d.status) && !(d.contadores as { concluidos?: number })?.concluidos) {
    return (
      <>
        <Cabecalho voltar={voltar} titulo={d.nome} subtitulo={subtitulo} />
        <Passos atual={3} />
        <PreviaInicio auditoria={d} />
      </>
    );
  }
  return (
    <>
      <Cabecalho
        voltar={voltar}
        titulo={d.nome}
        subtitulo={subtitulo}
        acoes={
          <>
            {d.status === "pausada_orcamento" || d.status === "pausada_ia" ? <Retomar auditoria={d} /> : null}
            {d.status === "concluida" ? <Reaplicar auditoria={d} /> : null}
            <Button asChild variant="secundario">
              <Link to="/auditorias/$id/revisar" params={{ id }}>
                <Keyboard /> Fila de revisão
              </Link>
            </Button>
            <Button asChild variant="secundario">
              <Link to="/auditorias/$id/exportar" params={{ id }}>
                <Download /> Exportar
              </Link>
            </Button>
          </>
        }
      />
      {aoVivo ? <Acompanhamento auditoria={d} /> : null}
      {d.status === "pausada_orcamento" ? (
        <Aviso tom="atencao" titulo="Auditoria pausada: orçamento mensal de IA atingido" className="mb-4">
          {d.erro} Os itens já analisados continuam disponíveis para revisão.
        </Aviso>
      ) : null}
      {d.status === "pausada_ia" ? (
        <Aviso tom="atencao" titulo="Auditoria pausada: a plataforma de IA não respondeu" className="mb-4">
          {d.erro} Nenhum item foi mandado para revisão por isso: a análise continua sozinha quando a plataforma voltar. Se
          preferir, troque o modelo em Modelos de IA e clique em Retomar.
        </Aviso>
      ) : null}
      <Abas auditoria={d} />
    </>
  );
}

/** Itens, perguntas decisivas e famílias investigadas: o trabalho do analista em três visões. */
function Abas({ auditoria }: { auditoria: Auditoria }) {
  const c = auditoria.contadores as { perguntas_abertas?: number; itens_em_perguntas?: number; familias?: number; ajustes_cadastro?: number };
  const [aba, setAba] = useState(() => {
    try {
      return sessionStorage.getItem(`aba:${auditoria.id}`) ?? "itens";
    } catch {
      return "itens";
    }
  });
  const mudar = (v: string) => {
    setAba(v);
    try {
      sessionStorage.setItem(`aba:${auditoria.id}`, v);
    } catch {
      /* armazenamento indisponível */
    }
  };
  return (
    <Tabs value={aba} onValueChange={mudar}>
      <TabsList className="mb-4">
        <TabsTrigger value="itens">Itens</TabsTrigger>
        <TabsTrigger value="perguntas">
          Perguntas
          {c.perguntas_abertas ? (
            <span className="num ml-1.5 rounded-full bg-ocre px-1.5 text-2xs font-semibold text-white">{fmtNum(c.perguntas_abertas)}</span>
          ) : null}
        </TabsTrigger>
        <TabsTrigger value="cadastro">
          Ajustes de cadastro
          {c.ajustes_cadastro ? <span className="num ml-1.5 rounded-full bg-caneta px-1.5 text-2xs font-semibold text-white">{fmtNum(c.ajustes_cadastro)}</span> : null}
        </TabsTrigger>
        <TabsTrigger value="familias">
          Famílias investigadas {c.familias ? <span className="num text-tinta-3">({fmtNum(c.familias)})</span> : null}
        </TabsTrigger>
        <TabsTrigger value="fluxo">Fluxo dos agentes</TabsTrigger>
      </TabsList>
      <TabsContent value="itens">
        {c.perguntas_abertas ? (
          <Aviso tom="atencao" className="mb-4" titulo={`${plural(c.perguntas_abertas, "pergunta destrava", "perguntas destravam")} ${plural(c.itens_em_perguntas ?? 0, "item", "itens")}`}>
            <button className="underline" onClick={() => mudar("perguntas")}>
              Responder agora
            </button>{" "}
            — cada resposta vale para o grupo inteiro e reclassifica os itens na hora.
          </Aviso>
        ) : null}
        <Resultado auditoria={auditoria} />
      </TabsContent>
      <TabsContent value="perguntas">
        <PerguntasPainel auditId={auditoria.id} />
      </TabsContent>
      <TabsContent value="cadastro">
        <AjustesCadastroPainel auditId={auditoria.id} />
      </TabsContent>
      <TabsContent value="familias">
        <FamiliasPainel auditId={auditoria.id} />
      </TabsContent>
      <TabsContent value="fluxo">
        <FluxoAuditoria auditId={auditoria.id} />
      </TabsContent>
    </Tabs>
  );
}

function Retomar({ auditoria }: { auditoria: Auditoria }) {
  const qc = useQueryClient();
  const m = useMutation({
    mutationFn: () => ok(api.POST("/api/auditorias/{audit_id}/iniciar", { params: { path: { audit_id: auditoria.id } }, body: { modo: auditoria.modo, confirmar_custo_usd: 0 } })),
    onSuccess: () => {
      toast.success("Auditoria retomada");
      void qc.invalidateQueries({ queryKey: ["auditoria", auditoria.id] });
    },
    onError: (e) => toast.error(mensagemErro(e)),
  });
  return (
    <Button variant="primario" onClick={() => m.mutate()} disabled={m.isPending}>
      <Play /> Retomar
    </Button>
  );
}

/** Refaz a decisão dos itens com as regras atuais, a partir das respostas da IA já gravadas: sem IA e sem custo. */
function Reaplicar({ auditoria }: { auditoria: Auditoria }) {
  const qc = useQueryClient();
  const m = useMutation({
    mutationFn: (reanalisar_falhas: boolean) =>
      ok(api.POST("/api/auditorias/{audit_id}/reaplicar", { params: { path: { audit_id: auditoria.id } }, body: { reanalisar_falhas } })),
    onSuccess: (r, reanalisar) => {
      const acao =
        r.falhas_de_ia && !reanalisar
          ? { action: { label: `Reanalisar os ${fmtNum(r.falhas_de_ia)}`, onClick: () => m.mutate(true) }, duration: 15000 }
          : undefined;
      toast.success(r.mensagem, acao);
      for (const k of ["auditoria", "itens", "pendencias", "grupos-revisao", "ajustes-cadastro"]) void qc.invalidateQueries({ queryKey: [k, auditoria.id] });
    },
    onError: (e) => toast.error(mensagemErro(e)),
  });
  return (
    <Button variant="secundario" onClick={() => m.mutate(false)} disabled={m.isPending} title="Refaz a decisão dos itens com as regras atuais, sem chamar a IA e sem custo">
      <RefreshCcw /> {m.isPending ? "Reaplicando…" : "Reaplicar regras (sem IA)"}
    </Button>
  );
}

// ------------------------------------------------------------------ prévia e estimativa --
function PreviaInicio({ auditoria }: { auditoria: Auditoria }) {
  const { pode } = useAuth();
  const qc = useQueryClient();
  const [filtro, setFiltro] = useState<string | undefined>();
  const prob = auditoria.problemas_resumo as {
    total_linhas?: number;
    itens_validos?: number;
    ignorados?: number;
    com_problemas?: number;
    por_problema?: Record<string, number>;
    descricoes?: Record<string, string>;
    provaveis_da_memoria?: number;
    base_referencia?: { ncm: boolean; nbs: boolean };
  };
  const est = auditoria.estimativa as Record<string, Record<string, unknown>> & { modo_recomendado?: string };
  const [modo, setModo] = useState<string>(est.modo_recomendado ?? "tempo_real");
  const linhas = useQuery({
    queryKey: ["previa", auditoria.id, filtro],
    queryFn: () => ok(api.GET("/api/auditorias/{audit_id}/previa", { params: { path: { audit_id: auditoria.id }, query: { problema: filtro, limite: 200 } } })),
  });
  const escolhida = est[modo] ?? {};
  const iniciar = useMutation({
    mutationFn: () =>
      ok(
        api.POST("/api/auditorias/{audit_id}/iniciar", {
          params: { path: { audit_id: auditoria.id } },
          body: { modo, confirmar_custo_usd: Number(escolhida.custo_usd_estimado ?? 0) },
        }),
      ),
    onSuccess: () => {
      toast.success("Auditoria iniciada");
      void qc.invalidateQueries({ queryKey: ["auditoria", auditoria.id] });
    },
    onError: (e) => toast.error(mensagemErro(e)),
  });

  const orc = auditoria.orcamento as { limite_usd?: number | null; gasto_mes_usd?: number };
  return (
    <div className="grid gap-6 xl:grid-cols-[1fr_24rem]">
      <div className="grid min-w-0 gap-6">
        {auditoria.status === "falhou" ? <Aviso tom="erro" titulo="Não foi possível processar">{auditoria.erro}</Aviso> : null}
        {prob.base_referencia && (!prob.base_referencia.ncm || !prob.base_referencia.nbs) ? (
          <Aviso tom="atencao" titulo="Base de referência incompleta">
            {!prob.base_referencia.ncm ? "A tabela NCM oficial ainda não foi importada. " : ""}
            {!prob.base_referencia.nbs ? "A tabela NBS oficial ainda não foi importada. " : ""}
            Os itens que dependem dela irão para revisão do contador.
          </Aviso>
        ) : null}
        <div className="grid gap-3 sm:grid-cols-4">
          <Mini rotulo="Linhas lidas" valor={fmtNum(prob.total_linhas ?? 0)} />
          <Mini rotulo="Itens válidos" valor={fmtNum(prob.itens_validos ?? 0)} />
          <Mini rotulo="Com algum problema" valor={fmtNum(prob.com_problemas ?? 0)} tom="ocre" />
          <Mini rotulo="Já na memória aprovada" valor={fmtNum(prob.provaveis_da_memoria ?? 0)} tom="conferido" />
        </div>
        <Painel>
          <div className="flex flex-wrap items-center gap-2 border-b border-regua px-5 py-3">
            <h2 className="mr-2 text-base">Problemas nos dados</h2>
            <button className={cn("rounded-full border px-2.5 py-0.5 text-2xs", !filtro ? "border-tinta bg-tinta text-papel" : "border-regua")} onClick={() => setFiltro(undefined)}>
              Todos
            </button>
            {Object.entries(prob.por_problema ?? {}).map(([k, n]) => (
              <button
                key={k}
                onClick={() => setFiltro(k)}
                className={cn("rounded-full border px-2.5 py-0.5 text-2xs", filtro === k ? "border-tinta bg-tinta text-papel" : "border-regua hover:border-regua-forte")}
                title={prob.descricoes?.[k]}
              >
                {prob.descricoes?.[k]?.split(";")[0]?.split(".")[0] ?? k} · <span className="num">{fmtNum(n)}</span>
              </button>
            ))}
          </div>
          <div className="max-h-[28rem] overflow-y-auto">
            {(linhas.data ?? []).length === 0 ? (
              <p className="px-5 py-8 text-center text-sm text-tinta-3">Nenhum problema de dados encontrado.</p>
            ) : (
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-superficie">
                  <tr className="border-b border-regua text-left text-2xs text-tinta-3">
                    <th className="px-5 py-2 font-medium">Linha</th>
                    <th className="px-3 py-2 font-medium">Descrição</th>
                    <th className="px-3 py-2 font-medium">NCM/NBS informado</th>
                    <th className="px-5 py-2 font-medium">Problemas</th>
                  </tr>
                </thead>
                <tbody>
                  {linhas.data!.map((l) => (
                    <tr key={l.linha} className="border-b border-regua align-top last:border-0">
                      <td className="num px-5 py-2 text-tinta-3">{l.linha}</td>
                      <td className="px-3 py-2">{l.descricao || <span className="text-tinta-3">(vazia)</span>}</td>
                      <td className="codigo px-3 py-2 text-xs">{l.ncm_informado ?? l.nbs_informado ?? "—"}</td>
                      <td className="px-5 py-2 text-xs text-tinta-2">
                        {l.problemas.map((p) => (
                          <p key={p.codigo}>{p.mensagem}</p>
                        ))}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </Painel>
      </div>

      <Painel className="h-fit p-5">
        <h2 className="text-base">Estimativa de custo e tempo</h2>
        <p className="mt-1 text-xs text-tinta-3">{String(escolhida.observacao ?? "")}</p>
        <div className="mt-4 grid grid-cols-2 gap-2" role="radiogroup" aria-label="Modo de processamento">
          {(["tempo_real", "lote"] as const).map((m) => (
            <button
              key={m}
              role="radio"
              aria-checked={modo === m}
              onClick={() => setModo(m)}
              className={cn("rounded-md border px-3 py-2 text-left text-sm", modo === m ? "border-tinta bg-superficie-2" : "border-regua hover:border-regua-forte")}
            >
              <span className="font-medium">{m === "lote" ? "Em lote" : "Tempo real"}</span>
              <span className="block text-2xs text-tinta-3">{m === "lote" ? "50% mais barato nos modelos Claude, até 24 h" : "Mais rápido"}</span>
            </button>
          ))}
        </div>
        <dl className="mt-4 grid gap-2 text-sm">
          <Economia previsao={(escolhida.previsao ?? {}) as Record<string, number>} />
          <Linha rotulo="Itens analisados por IA" valor={fmtNum(Number(escolhida.itens_com_ia ?? 0))} />
          <Linha rotulo="Segundos pareceres (estimados)" valor={fmtNum(Number(escolhida.escalonamentos_estimados ?? 0))} />
          <Linha rotulo="Famílias a investigar na lei" valor={fmtNum(Number(escolhida.familias_estimadas ?? 0))} />
          <Linha rotulo="Tokens de entrada / saída" valor={`${fmtNum(Number(escolhida.tokens_entrada_estimados ?? 0))} / ${fmtNum(Number(escolhida.tokens_saida_estimados ?? 0))}`} />
          <Linha rotulo="Tempo" valor={String(escolhida.tempo_texto ?? "")} />
          <CustoPorAgente agentes={(escolhida.agentes ?? []) as AgenteCusto[]} semLote={(escolhida.sem_lote ?? []) as string[]} />
          <div className="mt-2 border-t border-regua pt-3">
            <dt className="text-xs text-tinta-3">Custo estimado</dt>
            <dd className="num text-2xl font-semibold">{fmtUSD(Number(escolhida.custo_usd_estimado ?? 0))}</dd>
            <dd className="text-2xs text-tinta-3">
              faixa provável {fmtUSD((escolhida.custo_usd_faixa as number[] | undefined)?.[0])} a {fmtUSD((escolhida.custo_usd_faixa as number[] | undefined)?.[1])}
            </dd>
          </div>
          {orc.limite_usd != null ? (
            <p className="text-2xs text-tinta-3">
              Gasto do mês: {fmtUSD(orc.gasto_mes_usd)} de {fmtUSD(orc.limite_usd)}.
            </p>
          ) : null}
        </dl>
        {pode("criar_auditoria") ? (
          <Button variant="primario" className="mt-5 w-full" disabled={iniciar.isPending || !prob.itens_validos} onClick={() => iniciar.mutate()}>
            <Play /> {iniciar.isPending ? "Iniciando…" : `Confirmar ${fmtUSD(Number(escolhida.custo_usd_estimado ?? 0))} e iniciar`}
          </Button>
        ) : (
          <p className="mt-4 text-xs text-tinta-3">Seu papel não permite iniciar auditorias.</p>
        )}
      </Painel>
    </div>
  );
}

type AgenteCusto = { agente: string; nome: string; modelo_nome: string; chamadas: number; custo_usd: number; lote: boolean };

/** Custo previsto de cada agente, com o modelo escolhido em "Modelos de IA". */
function CustoPorAgente({ agentes, semLote }: { agentes: AgenteCusto[]; semLote: string[] }) {
  if (!agentes.length) return null;
  return (
    <div className="mt-2 rounded-md border border-regua">
      <p className="border-b border-regua px-3 py-1.5 text-2xs font-medium text-tinta-3">Custo por agente (modelo atual)</p>
      <ul className="divide-y divide-regua text-xs">
        {agentes.map((a) => (
          <li key={a.agente} className="flex items-baseline gap-2 px-3 py-1.5">
            <span className="min-w-0 flex-1">
              <span className="font-medium">{a.nome}</span> <span className="text-tinta-3">· {a.modelo_nome}</span>
              <span className="block text-2xs text-tinta-3">
                {fmtNum(a.chamadas)} chamada(s){a.lote ? " · lote −50%" : ""}
              </span>
            </span>
            <span className="num">{fmtUSD(a.custo_usd)}</span>
          </li>
        ))}
      </ul>
      {semLote.length ? (
        <p className="border-t border-regua px-3 py-1.5 text-2xs text-ocre">Sem lote (preço cheio, em tempo real): {semLote.join(", ")}.</p>
      ) : null}
    </div>
  );
}

function Mini({ rotulo, valor, tom }: { rotulo: string; valor: string; tom?: "ocre" | "conferido" }) {
  return (
    <Painel className="px-4 py-3">
      <p className="text-2xs text-tinta-3">{rotulo}</p>
      <p className={cn("num mt-0.5 text-xl font-semibold", tom === "ocre" && "text-ocre", tom === "conferido" && "text-conferido")}>{valor}</p>
    </Painel>
  );
}

function Linha({ rotulo, valor }: { rotulo: string; valor: string }) {
  return (
    <div className="flex justify-between gap-4">
      <dt className="text-tinta-3">{rotulo}</dt>
      <dd className="num text-right">{valor}</dd>
    </div>
  );
}

// ------------------------------------------------------------------------ acompanhamento --
function Acompanhamento({ auditoria }: { auditoria: Auditoria }) {
  const c = auditoria.contadores as { por_status?: Record<string, number>; por_etapa?: Record<string, number>; concluidos?: number; total?: number };
  const total = c.total || auditoria.total_itens || 0;
  const concl = c.concluidos ?? 0;
  const etapas = useMemo(() => Object.entries(c.por_etapa ?? {}).sort((a, b) => b[1] - a[1]), [c.por_etapa]);
  return (
    <Painel className="mb-6 p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="flex items-center gap-2 text-sm font-medium">
          {auditoria.status === "aguardando_lote" ? <PauseCircle className="size-4 text-tinta-3" /> : <Radio className="size-4 animate-pulse text-conferido" />}
          {auditoria.status === "aguardando_lote" ? "Aguardando o lote da IA (você pode fechar esta tela e voltar depois)" : "Processando ao vivo"}
        </p>
        <p className="num text-sm text-tinta-2">
          {fmtNum(concl)} de {fmtNum(total)} · custo até agora {fmtUSD(auditoria.custo_usd)}
        </p>
      </div>
      <Progresso className="mt-3" valor={total ? (concl / total) * 100 : 0} rotulo="Progresso da auditoria" />
      <div className="mt-4 flex flex-wrap gap-x-6 gap-y-2 text-xs">
        {(["classificado", "aguardando_informacao", "revisao_contador", "revisao_especialista", "erro"] as const).map((s) => (
          <span key={s} className={cn("flex items-center gap-1.5", STATUS[s].cor)}>
            {(() => {
              const I = STATUS[s].icone;
              return <I className="size-3.5" aria-hidden />;
            })()}
            {STATUS[s].rotulo} <span className="num font-medium">{fmtNum(c.por_status?.[s] ?? 0)}</span>
          </span>
        ))}
        {etapas.map(([e, n]) => (
          <span key={e} className="text-tinta-3">
            {ETAPAS[e] ?? e}: <span className="num">{fmtNum(n)}</span>
          </span>
        ))}
      </div>
    </Painel>
  );
}

/** De onde vem a economia: o que o analista resolve sem chamar a IA. */
function Economia({ previsao }: { previsao: Record<string, number> }) {
  if (!previsao.itens) return null;
  const linhas: [string, number][] = [
    ["NCM informado confirmado sem IA (estimado)", previsao.confirmaveis_sem_ia ?? 0],
    ["Linhas repetidas (uma análise vale para todas)", previsao.repetidos ?? 0],
    ["Já aprovados antes (memória da empresa)", previsao.na_memoria ?? 0],
    ["Famílias já investigadas (reaproveitadas)", previsao.familias_reaproveitadas ?? 0],
  ];
  return (
    <div className="rounded-md border border-conferido/30 bg-conferido-suave/40 px-3 py-2">
      <p className="text-2xs font-medium text-conferido">Economia do analista</p>
      {linhas.map(([r, n]) => (
        <div key={r} className="flex justify-between gap-4 text-2xs">
          <span className="text-tinta-2">{r}</span>
          <span className="num">{fmtNum(n)}</span>
        </div>
      ))}
    </div>
  );
}
