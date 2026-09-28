import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpenText, Check, ChevronDown, CircleHelp, FileSearch, History, Lightbulb, ListChecks, Pencil, RotateCcw, Scale, ShieldCheck, Undo2, X } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { toast } from "sonner";
import { api, ok } from "@/api/client";
import { useAuth } from "@/auth/auth";
import { Codigo, ConfiancaGlobal, EstadoErro, mensagemErro, Motivo, ORIGEM_FATO, RelatorioConfianca, SeloRevisao, SeloStatus } from "@/components/dominio";
import { ReguaConferencia, type CodigoInfo } from "@/components/ReguaConferencia";
import { Aviso, Button, Dialog, DialogContent, Input, Kbd, Skeleton, Textarea } from "@/components/ui/primitives";
import { fmtData, fmtDataHora, fmtUSD } from "@/lib/format";
import { cn } from "@/lib/utils";
import { TRATAMENTO, useDossieItem, useItemDetalhe } from "./comum";
import { DetalheTese } from "./FamiliasPainel";
import { useResponder } from "./PerguntasPainel";

const ACOES_HIST: Record<string, string> = {
  aprovar: "Aprovou",
  editar: "Editou",
  responder: "Informou fatos",
  rejeitar: "Rejeitou",
  desfazer: "Desfez a decisão",
};

const IS: Record<string, string> = { sujeito: "Sujeito", nao_sujeito: "Não sujeito", indefinido: "A confirmar" };
const HIPOTESE_SITUACAO: Record<string, { rotulo: string; cor: string }> = {
  escolhida: { rotulo: "aplicada", cor: "text-conferido" },
  afastada: { rotulo: "afastada", cor: "text-tinta-3" },
  possivel: { rotulo: "em aberto", cor: "text-ocre" },
};

export function useAcoesItem(itemId: string | null, auditId: string, aoConcluir?: (acao: string) => void) {
  const qc = useQueryClient();
  const atualizar = () => {
    void qc.invalidateQueries({ queryKey: ["item", itemId] });
    void qc.invalidateQueries({ queryKey: ["dossie-item", itemId] });
    void qc.invalidateQueries({ queryKey: ["itens", auditId] });
    void qc.invalidateQueries({ queryKey: ["auditoria", auditId] });
    void qc.invalidateQueries({ queryKey: ["pendencias", auditId] });
  };
  const opcoes = (acao: string, msg: string) => ({
    onSuccess: (r: { mensagem?: string }) => {
      atualizar();
      toast.success(r?.mensagem ?? msg, acao === "aprovar" ? { action: { label: "Desfazer", onClick: () => desfazer.mutate() } } : undefined);
      aoConcluir?.(acao);
    },
    onError: (e: unknown) => toast.error(mensagemErro(e)),
  });
  const aprovar = useMutation({
    mutationFn: (comentario?: string) => ok(api.POST("/api/itens/{item_id}/aprovar", { params: { path: { item_id: itemId! } }, body: { comentario } })),
    ...opcoes("aprovar", "Aprovado"),
  });
  const rejeitar = useMutation({
    mutationFn: (comentario: string) => ok(api.POST("/api/itens/{item_id}/rejeitar", { params: { path: { item_id: itemId! } }, body: { comentario } })),
    ...opcoes("rejeitar", "Rejeitado"),
  });
  const desfazer = useMutation({
    mutationFn: () => ok(api.POST("/api/itens/{item_id}/desfazer", { params: { path: { item_id: itemId! } } })),
    onSuccess: () => {
      atualizar();
      toast.success("Decisão desfeita");
    },
    onError: (e: unknown) => toast.error(mensagemErro(e)),
  });
  const editar = useMutation({
    mutationFn: (corpo: { tipo_codigo?: string; codigo?: string; respostas?: Record<string, string>; cst?: string; cclasstrib?: string; comentario?: string; aprovar?: boolean }) =>
      ok(api.POST("/api/itens/{item_id}/editar", { params: { path: { item_id: itemId! } }, body: { respostas: {}, aprovar: false, ...corpo } })),
    ...opcoes("editar", "Alteração salva"),
  });
  const reprocessar = useMutation({
    mutationFn: () => ok(api.POST("/api/itens/{item_id}/reprocessar", { params: { path: { item_id: itemId! } } })),
    ...opcoes("reprocessar", "Reprocessamento iniciado"),
  });
  return { aprovar, rejeitar, desfazer, editar, reprocessar };
}

type Pergunta = {
  pendencia_id: string;
  atributo: string;
  pergunta: string;
  grupo: string;
  escopo: string;
  motivo: string;
  opcoes: { valor: string; rotulo?: string; efeito?: string }[];
  sugestao?: { valor: string; evidencia: string } | null;
};
type Fundamento = { ref: string; trecho?: string; tipo?: string; norma?: string; local?: string; nome?: string; texto_integral?: string };
type Fato = { atributo: string; valor: string; origem: string; origem_rotulo?: string; evidencia?: string | null; autor?: string | null; escopo?: string; grupo?: string | null };

/** Dossiê de decisão do item: o que é, que fatos sustentam, que norma foi aplicada e com que confiança. */
export function DetalheItem({
  itemId,
  auditId,
  aoConcluir,
  compacto,
}: {
  itemId: string;
  auditId: string;
  aoConcluir?: (acao: string) => void;
  compacto?: boolean;
}) {
  const { pode } = useAuth();
  const q = useDossieItem(itemId);
  const ident = useItemDetalhe(itemId);
  const acoes = useAcoesItem(itemId, auditId, aoConcluir);
  const responder = useResponder(auditId);
  const [editando, setEditando] = useState(false);
  const [rejeitando, setRejeitando] = useState(false);
  const [teseAberta, setTeseAberta] = useState(false);

  if (q.isError) return <EstadoErro erro={q.error} aoTentar={() => void q.refetch()} />;
  if (!q.data) return <Skeleton className="h-[32rem]" />;
  const d = q.data;
  const it = d.item as {
    linha: number;
    codigo_interno: string;
    descricao: string;
    categoria?: string;
    marca?: string;
    unidade?: string;
    gtin?: string;
    status: string;
    nivel_revisao?: string;
    revisao_status: string;
    aprovado_automaticamente: boolean;
    motivos: string[];
    erro?: string;
    data_referencia: string;
    cst_atual?: string;
    cclasstrib_atual?: string;
  };
  const res = d.resultado as {
    hipotese?: string;
    conclusao?: string;
    cst?: string;
    cclasstrib?: string;
    perc_red_ibs?: number;
    perc_red_cbs?: number;
    imposto_seletivo?: string;
    tratamento?: string;
    dispositivo?: string;
    confianca_global?: string;
    perfil_versao?: number;
  };
  const idt = d.identidade as { situacao?: string; entendimento?: string; problemas_cadastro?: string[]; descricao_normalizada?: string };
  const perguntas = (d.perguntas ?? []) as Pergunta[];
  const podeRevisar = pode("revisar");
  const aprovadoHumano = it.revisao_status === "aprovado" && !it.aprovado_automaticamente;
  const completa = !!(res.cclasstrib && !perguntas.length);
  const textos = ident.data?.textos_motivos;

  return (
    <div className="flex flex-col gap-5">
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <SeloStatus status={it.status} />
          <SeloRevisao status={it.revisao_status} automatico={it.aprovado_automaticamente} />
          <span className="ml-auto text-2xs text-tinta-3">
            Linha <span className="num">{it.linha}</span> · código <span className="codigo">{it.codigo_interno}</span>
          </span>
        </div>
        <h2 className="mt-2 text-lg leading-snug">{it.descricao}</h2>
        <p className="mt-1 flex flex-wrap gap-x-3 text-2xs text-tinta-3">
          {it.categoria ? <span>Categoria: {it.categoria}</span> : null}
          {it.marca ? <span>Marca: {it.marca}</span> : null}
          {it.unidade ? <span>Unidade: {it.unidade}</span> : null}
          {it.gtin ? <span className="codigo">GTIN {it.gtin}</span> : null}
          <span>
            Venda ao consumidor · vigência {fmtData(it.data_referencia)} ({d.transicao.periodo})
          </span>
        </p>
      </div>

      {/* Resultado */}
      <section className="rounded-lg border border-regua bg-superficie-2 p-4">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="text-sm font-semibold">Enquadramento</h3>
          <ConfiancaGlobal valor={res.confianca_global} className="ml-auto" />
        </div>
        <div className="mt-3 grid gap-3 sm:grid-cols-4">
          <Dado rotulo="CST IBS/CBS" valor={<span className="codigo">{res.cst ?? "—"}</span>} antes={it.cst_atual && it.cst_atual !== res.cst ? it.cst_atual : undefined} />
          <Dado rotulo="cClassTrib" valor={<span className="codigo">{res.cclasstrib ?? "—"}</span>} antes={it.cclasstrib_atual && it.cclasstrib_atual !== res.cclasstrib ? it.cclasstrib_atual : undefined} />
          <Dado rotulo="Redução IBS / CBS" valor={res.perc_red_cbs != null ? `${res.perc_red_ibs ?? 0}% / ${res.perc_red_cbs}%` : "—"} />
          <Dado rotulo="Imposto Seletivo" valor={IS[res.imposto_seletivo ?? ""] ?? "—"} />
        </div>
        {res.conclusao ? <p className="mt-3 text-sm">{res.conclusao}</p> : null}
        {res.dispositivo ? <p className="mt-1 text-2xs text-tinta-3">Fundamento: {res.dispositivo}</p> : null}
        {res.tratamento ? <p className="text-2xs text-tinta-3">Tratamento: {TRATAMENTO[res.tratamento] ?? res.tratamento}</p> : null}
        {it.erro ? <p className="mt-2 text-xs text-perigo">{it.erro}</p> : null}
      </section>

      {/* Perguntas decisivas */}
      {perguntas.length ? (
        <Aviso tom="atencao" titulo="Falta uma informação que muda o enquadramento">
          <ul className="mt-2 grid gap-3">
            {perguntas.map((p) => (
              <li key={p.pendencia_id}>
                <p className="flex items-start gap-1.5 font-medium">
                  <CircleHelp className="mt-0.5 size-4 shrink-0 text-ocre" aria-hidden /> {p.pergunta}
                </p>
                <p className="pl-5.5 text-2xs text-tinta-3">
                  Pergunta do grupo: {p.grupo}. {p.opcoes.map((o) => `Se “${o.rotulo ?? o.valor}” → ${o.efeito ?? ""}`).join(" · ")}
                </p>
                {p.sugestao ? (
                  <p className="flex items-center gap-1 pl-5.5 text-2xs text-caneta">
                    <Lightbulb className="size-3" aria-hidden /> A IA supõe “{p.sugestao.valor}” ({p.sugestao.evidencia}), mas precisa de confirmação.
                  </p>
                ) : null}
                {pode("responder") && !aprovadoHumano ? (
                  <span className="mt-1.5 flex flex-wrap gap-1 pl-5.5">
                    {p.opcoes.map((o) => (
                      <Button key={o.valor} tamanho="sm" disabled={responder.isPending} onClick={() => responder.mutate({ id: p.pendencia_id, respostas_itens: { [itemId]: o.valor } })}>
                        {o.rotulo ?? o.valor} <span className="text-tinta-3">(só este item)</span>
                      </Button>
                    ))}
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        </Aviso>
      ) : null}

      <Secao titulo="Relatório de confiança" icone={<ShieldCheck className="size-4" />}>
        <RelatorioConfianca dimensoes={d.dimensoes as { chave: string; rotulo: string; situacao: string; texto: string }[]} />
        {it.motivos?.length ? (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {it.motivos.map((m) => (
              <Motivo key={m} codigo={m} textos={textos} />
            ))}
          </div>
        ) : null}
      </Secao>

      <Secao titulo="Identificação do item" icone={<FileSearch className="size-4" />}>
        {ident.data ? <ReguaConferencia atual={ident.data.codigo_atual as CodigoInfo | null} sugerido={ident.data.codigo_sugerido as CodigoInfo | null} /> : <Skeleton className="h-24" />}
        {idt.entendimento ? <p className="mt-2 text-sm text-tinta-2">{idt.entendimento}</p> : null}
        {idt.problemas_cadastro?.length ? (
          <p className="mt-2 text-xs text-ocre">Problemas no cadastro legado: {idt.problemas_cadastro.map((m) => textos?.[m]?.[0] ?? m).join(" · ")}</p>
        ) : null}
      </Secao>

      <Secao titulo="Fatos considerados" icone={<ListChecks className="size-4" />}>
        <ListaFatos usados={d.fatos_usados as Fato[]} outros={d.fatos_do_item as unknown as Fato[]} />
      </Secao>

      <Secao titulo="Fundamentação" icone={<Scale className="size-4" />}>
        <Fundamentos itens={d.fundamentos as Fundamento[]} />
        {d.tese ? (
          <Button variant="fantasma" tamanho="sm" className="mt-2" onClick={() => setTeseAberta(true)}>
            <BookOpenText /> Ver o raciocínio completo da família {String((d.tese as { codigo?: string }).codigo ?? "")}
          </Button>
        ) : null}
      </Secao>

      {!compacto ? (
        <Colapsavel titulo={`Hipóteses testadas (${d.hipoteses.length})`}>
          <ol className="grid gap-1.5 text-sm">
            {(d.hipoteses as { id: string; titulo: string; cclasstrib: string; situacao: string; motivo: string }[]).map((h) => (
              <li key={h.id} className="flex flex-wrap gap-2">
                <span className={cn("w-20 shrink-0 text-2xs font-medium uppercase", HIPOTESE_SITUACAO[h.situacao]?.cor)}>{HIPOTESE_SITUACAO[h.situacao]?.rotulo ?? h.situacao}</span>
                <span className="flex-1">
                  {h.titulo} <span className="codigo text-2xs text-tinta-3">{h.cclasstrib}</span>
                  <span className="block text-2xs text-tinta-3">{h.motivo}</span>
                </span>
              </li>
            ))}
            {d.hipoteses.length === 0 ? <li className="text-tinta-3">Nenhuma hipótese avaliada.</li> : null}
          </ol>
        </Colapsavel>
      ) : null}

      {!compacto && ident.data?.candidatos.length ? (
        <Colapsavel titulo={`Códigos candidatos considerados (${ident.data.candidatos.length})`}>
          <ul className="divide-y divide-regua text-sm">
            {ident.data.candidatos.map((c) => (
              <li key={c.codigo as string} className="flex items-start gap-3 py-2">
                <span className="num w-5 text-2xs text-tinta-3">{String(c.posicao)}</span>
                <span className="codigo w-24 shrink-0">{String(c.formatado)}</span>
                <span className="flex-1 text-xs text-tinta-2">{String(c.descricao_completa)}</span>
                {podeRevisar && !aprovadoHumano && c.codigo !== (ident.data.codigo_sugerido as { codigo?: string } | null)?.codigo ? (
                  <Button tamanho="sm" variant="fantasma" onClick={() => acoes.editar.mutate({ tipo_codigo: String(c.tipo), codigo: String(c.codigo) })}>
                    Usar
                  </Button>
                ) : null}
              </li>
            ))}
          </ul>
        </Colapsavel>
      ) : null}

      {!compacto ? (
        <Colapsavel titulo="Histórico e rastreabilidade" icone={<History className="size-4" />}>
          <p className="text-2xs font-medium text-tinta-3">Versões do perfil tributário</p>
          <ol className="mt-1 space-y-1 text-xs">
            {(d.versoes_perfil as { versao: number; ativo: boolean; status: string; cclasstrib?: string; motivo?: string; em: string }[]).map((v) => (
              <li key={v.versao} className={cn(!v.ativo && "text-tinta-3")}>
                v{v.versao} {v.ativo ? "(vigente)" : ""} · <span className="codigo">{v.cclasstrib ?? "—"}</span> · {v.status.replaceAll("_", " ")} · {v.motivo} · {fmtDataHora(v.em)}
              </li>
            ))}
          </ol>
          <p className="mt-3 text-2xs font-medium text-tinta-3">Decisões de pessoas</p>
          <ol className="mt-1 space-y-1 text-sm">
            {d.revisoes.length === 0 ? <li className="text-tinta-3">Nenhuma decisão registrada.</li> : null}
            {(d.revisoes as { acao: string; usuario: string; comentario?: string; em: string }[]).map((h, i) => (
              <li key={i}>
                <span className="font-medium">{ACOES_HIST[h.acao] ?? h.acao}</span> — {h.usuario} · {fmtDataHora(h.em)}
                {h.comentario ? <p className="text-xs text-tinta-2">“{h.comentario}”</p> : null}
              </li>
            ))}
          </ol>
          <p className="mt-3 text-2xs font-medium text-tinta-3">Base normativa e tabelas usadas</p>
          <ul className="mt-1 space-y-0.5 text-2xs text-tinta-2">
            {(d.base_normativa as { fonte: string; rotulo: string; coletado_em: string; sha256: string }[]).map((b, i) => (
              <li key={i}>
                {b.fonte.toUpperCase()} · {b.rotulo} · coletada em {fmtData(b.coletado_em)} · <span className="codigo">{b.sha256}</span>
              </li>
            ))}
          </ul>
          <p className="mt-3 text-2xs font-medium text-tinta-3">Chamadas de IA</p>
          <ul className="mt-1 space-y-1 text-2xs text-tinta-2">
            {(d.chamadas_ia as { no: string; modelo: string; prompt: string; tokens_entrada: number; tokens_saida: number; custo_usd: number; compartilhada: boolean }[]).map((c, i) => (
              <li key={i} className="codigo">
                {c.no} · {c.modelo} · {c.prompt} · {c.tokens_entrada}+{c.tokens_saida} tokens · {fmtUSD(c.custo_usd)}
                {c.compartilhada ? " · compartilhada com a família" : ""}
              </li>
            ))}
            {d.chamadas_ia.length === 0 ? <li>Nenhuma (resolvido sem IA).</li> : null}
          </ul>
        </Colapsavel>
      ) : null}

      {podeRevisar ? (
        <div className="sticky bottom-0 -mx-6 flex flex-wrap items-center gap-2 border-t border-regua bg-superficie px-6 py-3">
          {aprovadoHumano || it.revisao_status === "rejeitado" ? (
            <>
              {aprovadoHumano ? (
                <span className="animar-carimbo mr-auto inline-flex -rotate-3 items-center gap-1 rounded border-2 border-conferido px-2 py-0.5 text-xs font-bold uppercase tracking-widest text-conferido">
                  Aprovado
                </span>
              ) : (
                <span className="mr-auto text-sm text-perigo">Rejeitado</span>
              )}
              <Button variant="secundario" onClick={() => acoes.desfazer.mutate()} disabled={acoes.desfazer.isPending}>
                <Undo2 /> Desfazer <Kbd>U</Kbd>
              </Button>
            </>
          ) : (
            <>
              <Button variant="confirmar" onClick={() => acoes.aprovar.mutate(undefined)} disabled={!completa || acoes.aprovar.isPending} title={!completa ? "Responda às perguntas ou corrija o código antes de aprovar" : undefined}>
                <Check /> {it.aprovado_automaticamente ? "Confirmar" : "Aprovar"} <Kbd className="border-white/30 bg-white/10 text-white">A</Kbd>
              </Button>
              <Button variant="secundario" onClick={() => setEditando(true)}>
                <Pencil /> Corrigir <Kbd>E</Kbd>
              </Button>
              <Button variant="fantasma" onClick={() => setRejeitando(true)}>
                <X /> Rejeitar <Kbd>R</Kbd>
              </Button>
              <Button variant="fantasma" className="ml-auto" onClick={() => acoes.reprocessar.mutate()} disabled={acoes.reprocessar.isPending}>
                <RotateCcw /> Reanalisar
              </Button>
            </>
          )}
        </div>
      ) : null}

      <EdicaoAssistida
        aberto={editando}
        aoFechar={() => setEditando(false)}
        tipo={(ident.data?.codigo_sugerido as { tipo?: string } | null)?.tipo ?? "ncm"}
        aoSalvar={(corpo) => {
          acoes.editar.mutate(corpo, { onSuccess: () => setEditando(false) });
        }}
        salvando={acoes.editar.isPending}
      />
      <Dialog open={rejeitando} onOpenChange={setRejeitando}>
        <DialogContent titulo="Rejeitar sugestão" descricao="O item não entrará na exportação final. Explique o motivo para o histórico.">
          <Rejeicao aoConfirmar={(c) => acoes.rejeitar.mutate(c, { onSuccess: () => setRejeitando(false) })} enviando={acoes.rejeitar.isPending} />
        </DialogContent>
      </Dialog>
      <Dialog open={teseAberta} onOpenChange={setTeseAberta}>
        {teseAberta && d.tese ? (
          <DialogContent lateral titulo="Raciocínio da família" className="max-w-3xl">
            <DetalheTese id={String((d.tese as { id: string }).id)} auditId={auditId} />
          </DialogContent>
        ) : null}
      </Dialog>
      <AtalhosDetalhe
        ativo={podeRevisar && !editando && !rejeitando && !teseAberta}
        aprovar={() => completa && !aprovadoHumano && acoes.aprovar.mutate(undefined)}
        editar={() => !aprovadoHumano && setEditando(true)}
        rejeitar={() => !aprovadoHumano && setRejeitando(true)}
        desfazer={() => (aprovadoHumano || it.revisao_status === "rejeitado") && acoes.desfazer.mutate()}
      />
    </div>
  );
}

function ListaFatos({ usados, outros }: { usados: Fato[]; outros: Fato[] }) {
  const chaves = new Set(usados.map((f) => f.atributo));
  const extras = outros.filter((f) => !chaves.has(f.atributo));
  if (!usados.length && !extras.length)
    return <p className="text-sm text-tinta-3">Nenhum fato específico foi necessário: o próprio código define o enquadramento.</p>;
  return (
    <ul className="grid gap-1.5 text-sm">
      {usados.map((f) => (
        <LinhaFato key={`u-${f.atributo}`} f={f} decisivo />
      ))}
      {extras.map((f) => (
        <LinhaFato key={`o-${f.atributo}-${f.valor}`} f={f} />
      ))}
    </ul>
  );
}

function LinhaFato({ f, decisivo }: { f: Fato; decisivo?: boolean }) {
  return (
    <li className="flex flex-wrap items-baseline gap-x-2">
      <span className={cn("font-medium", !decisivo && "text-tinta-2")}>
        {f.atributo.replaceAll("_", " ")} = {f.valor}
      </span>
      <span className="text-2xs text-tinta-3">
        {f.origem_rotulo ?? ORIGEM_FATO[f.origem] ?? f.origem}
        {f.autor ? ` · ${f.autor}` : ""}
        {f.evidencia ? ` · “${f.evidencia}”` : ""}
        {decisivo ? " · decisivo" : ""}
      </span>
    </li>
  );
}

function Fundamentos({ itens }: { itens: Fundamento[] }) {
  if (!itens.length) return <p className="text-sm text-tinta-3">Sem fundamentação verificável (o item não foi enquadrado).</p>;
  return (
    <ul className="grid gap-2">
      {itens.map((f) => (
        <li key={f.ref} className="border-l-2 border-regua-forte pl-3 text-sm">
          <p className="text-2xs font-medium text-tinta-3">
            {f.tipo === "trecho" ? `${f.norma ?? ""} — ${f.local ?? ""}` : f.tipo === "correlacao" ? "Correlação oficial cClassTrib × NCM" : f.tipo === "cclasstrib" ? `Tabela cClassTrib — ${f.nome ?? ""}` : "Precedente aprovado"}
          </p>
          {f.trecho ? <p className="text-tinta-2">“{f.trecho}”</p> : null}
          {f.texto_integral ? (
            <details className="mt-1 text-xs">
              <summary className="cursor-pointer text-tinta-3">Texto integral</summary>
              <p className="mt-1 whitespace-pre-line text-tinta-2">{f.texto_integral}</p>
            </details>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

function AtalhosDetalhe({ ativo, aprovar, editar, rejeitar, desfazer }: { ativo: boolean; aprovar: () => void; editar: () => void; rejeitar: () => void; desfazer: () => void }) {
  useEffect(() => {
    if (!ativo) return;
    const h = (e: KeyboardEvent) => {
      const alvo = e.target as HTMLElement;
      if (alvo.closest("input, textarea, [contenteditable], [role=dialog] input") || e.ctrlKey || e.metaKey || e.altKey) return;
      const acoes: Record<string, () => void> = { a: aprovar, e: editar, r: rejeitar, u: desfazer };
      const acao = acoes[e.key.toLowerCase()];
      if (acao) {
        e.preventDefault();
        acao();
      }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [ativo, aprovar, editar, rejeitar, desfazer]);
  return null;
}

function Secao({ titulo, icone, children }: { titulo: string; icone?: ReactNode; children: ReactNode }) {
  return (
    <section>
      <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-tinta">
        {icone}
        {titulo}
      </h3>
      {children}
    </section>
  );
}

function Colapsavel({ titulo, icone, children }: { titulo: string; icone?: ReactNode; children: ReactNode }) {
  return (
    <details className="group rounded-md border border-regua">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-sm font-medium">
        {icone}
        {titulo}
        <ChevronDown className="ml-auto size-4 transition-transform group-open:rotate-180" aria-hidden />
      </summary>
      <div className="border-t border-regua px-3 py-3">{children}</div>
    </details>
  );
}

function Dado({ rotulo, valor, antes }: { rotulo: string; valor: ReactNode; antes?: string }) {
  return (
    <div className="rounded-md border border-regua px-3 py-2">
      <p className="text-2xs text-tinta-3">{rotulo}</p>
      <p className="text-sm">
        {antes ? <span className="codigo mr-2 text-ocre line-through">{antes}</span> : null}
        {valor}
      </p>
    </div>
  );
}

function Rejeicao({ aoConfirmar, enviando }: { aoConfirmar: (c: string) => void; enviando: boolean }) {
  const [c, setC] = useState("");
  return (
    <div className="grid gap-3">
      <Textarea autoFocus value={c} onChange={(e) => setC(e.target.value)} placeholder="Ex.: item descontinuado; será excluído do cadastro." />
      <Button variant="perigo" disabled={c.trim().length < 3 || enviando} onClick={() => aoConfirmar(c.trim())}>
        Rejeitar
      </Button>
    </div>
  );
}

/** Edição assistida: busca na tabela oficial com autocompletar e hierarquia completa. */
export function EdicaoAssistida({
  aberto,
  aoFechar,
  tipo: tipoInicial,
  aoSalvar,
  salvando,
}: {
  aberto: boolean;
  aoFechar: () => void;
  tipo: string;
  aoSalvar: (c: { tipo_codigo: string; codigo: string; comentario?: string; aprovar?: boolean }) => void;
  salvando: boolean;
}) {
  return (
    <Dialog open={aberto} onOpenChange={(o) => !o && aoFechar()}>
      <DialogContent titulo="Editar classificação" descricao="Busque pelo código ou pela descrição na tabela oficial vigente. Com o código corrigido, o analista reinvestiga o item (a correção vale também para as próximas auditorias da empresa)." className="max-w-2xl">
        {/* Montado a cada abertura (o Radix desmonta o conteúdo ao fechar): o formulário começa limpo. */}
        <FormEdicao tipoInicial={tipoInicial} aoSalvar={aoSalvar} salvando={salvando} />
      </DialogContent>
    </Dialog>
  );
}

function FormEdicao({
  tipoInicial,
  aoSalvar,
  salvando,
}: {
  tipoInicial: string;
  aoSalvar: (c: { tipo_codigo: string; codigo: string; comentario?: string; aprovar?: boolean }) => void;
  salvando: boolean;
}) {
  const [tipo, setTipo] = useState(tipoInicial);
  const [termo, setTermo] = useState("");
  const [escolhido, setEscolhido] = useState<{ codigo: string; descricao_completa: string } | null>(null);
  const [comentario, setComentario] = useState("");
  const [atraso, setAtraso] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setAtraso(termo), 250);
    return () => clearTimeout(t);
  }, [termo]);
  const busca = useQuery({
    queryKey: ["busca-codigo", tipo, atraso],
    queryFn: () => ok(api.GET("/api/codigos/busca", { params: { query: { q: atraso, tipo } } })),
    enabled: atraso.trim().length >= 2,
  });
  return (
    <>
        <div className="flex gap-2">
          {["ncm", "nbs"].map((t) => (
            <Button key={t} tamanho="sm" variant={tipo === t ? "primario" : "secundario"} onClick={() => setTipo(t)}>
              {t.toUpperCase()}
            </Button>
          ))}
          <Input autoFocus value={termo} onChange={(e) => setTermo(e.target.value)} placeholder={tipo === "ncm" ? "Ex.: 3401 ou sabonete líquido" : "Ex.: 1.1401 ou consultoria"} aria-label="Buscar código" />
        </div>
        <ul className="max-h-80 overflow-y-auto rounded-md border border-regua" role="listbox" aria-label="Resultados">
          {busca.isFetching ? <li className="px-3 py-2 text-sm text-tinta-3">Buscando…</li> : null}
          {busca.error ? <li className="px-3 py-2 text-sm text-perigo">{mensagemErro(busca.error)}</li> : null}
          {(busca.data ?? []).map((r) => (
            <li key={r.codigo}>
              <button
                role="option"
                aria-selected={escolhido?.codigo === r.codigo}
                disabled={!r.folha}
                onClick={() => setEscolhido({ codigo: r.codigo, descricao_completa: r.descricao_completa })}
                className={cn(
                  "flex w-full gap-3 border-b border-regua px-3 py-2 text-left last:border-0 hover:bg-superficie-2 disabled:opacity-60",
                  escolhido?.codigo === r.codigo && "bg-caneta-suave",
                )}
              >
                <span className="codigo w-28 shrink-0 text-sm">{r.formatado}</span>
                <span className="text-xs text-tinta-2">
                  {r.descricao_completa}
                  {!r.folha ? <span className="block text-2xs text-tinta-3">nível intermediário — escolha um código completo</span> : null}
                </span>
              </button>
            </li>
          ))}
          {!busca.isFetching && atraso.length >= 2 && busca.data?.length === 0 ? <li className="px-3 py-2 text-sm text-tinta-3">Nenhum código encontrado.</li> : null}
        </ul>
        {escolhido ? (
          <p className="text-sm">
            Selecionado: <Codigo tipo={tipo} valor={escolhido.codigo} /> — <span className="text-tinta-2">{escolhido.descricao_completa}</span>
          </p>
        ) : null}
        <Input value={comentario} onChange={(e) => setComentario(e.target.value)} placeholder="Comentário para o histórico (opcional)" aria-label="Comentário" />
        <div className="flex justify-end gap-2">
          <Button variant="primario" disabled={!escolhido || salvando} onClick={() => escolhido && aoSalvar({ tipo_codigo: tipo, codigo: escolhido.codigo, comentario: comentario || undefined })}>
            Corrigir e reanalisar
          </Button>
        </div>
        <p className="text-2xs text-tinta-3">
          Se o novo código depender de algum fato (ex.: adição de açúcar), a pergunta aparecerá no item antes da aprovação.
        </p>
    </>
  );
}
