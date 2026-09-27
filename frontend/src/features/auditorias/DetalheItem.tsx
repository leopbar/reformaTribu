import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ChevronDown, History, Pencil, RotateCcw, Scale, Sparkles, Undo2, X } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { toast } from "sonner";
import { api, ok } from "@/api/client";
import { useAuth } from "@/auth/auth";
import { Codigo, Confianca, EstadoErro, mensagemErro, Motivo, SeloRevisao, SeloStatus } from "@/components/dominio";
import { ReguaConferencia, type CodigoInfo } from "@/components/ReguaConferencia";
import { Aviso, Button, Dialog, DialogContent, Input, Kbd, Skeleton, Textarea } from "@/components/ui/primitives";
import { fmtDataHora, fmtUSD } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useItemDetalhe } from "./comum";

const ACOES_HIST: Record<string, string> = {
  aprovar: "Aprovou",
  editar: "Editou",
  responder: "Respondeu perguntas",
  rejeitar: "Rejeitou",
  desfazer: "Desfez a decisão",
};

export function useAcoesItem(itemId: string | null, auditId: string, aoConcluir?: (acao: string) => void) {
  const qc = useQueryClient();
  const atualizar = () => {
    void qc.invalidateQueries({ queryKey: ["item", itemId] });
    void qc.invalidateQueries({ queryKey: ["itens", auditId] });
    void qc.invalidateQueries({ queryKey: ["auditoria", auditId] });
  };
  const opcoes = (acao: string, msg: string) => ({
    onSuccess: () => {
      atualizar();
      toast.success(msg, acao === "aprovar" ? { action: { label: "Desfazer", onClick: () => desfazer.mutate() } } : undefined);
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
  const q = useItemDetalhe(itemId);
  const acoes = useAcoesItem(itemId, auditId, aoConcluir);
  const [editando, setEditando] = useState(false);
  const [rejeitando, setRejeitando] = useState(false);

  if (q.isError) return <EstadoErro erro={q.error} aoTentar={() => void q.refetch()} />;
  if (!q.data) return <Skeleton className="h-[32rem]" />;
  const d = q.data;
  const it = d.item as Record<string, unknown> & {
    status: string;
    revisao_status: string;
    descricao: string;
    descricao_normalizada?: string;
    linha: number;
    codigo_interno: string;
    motivos: string[];
    perguntas: { atributo: string; pergunta: string; fonte: string; regra: string }[];
    confianca?: number;
    confianca_componentes?: Record<string, number>;
    cst_sugerido?: string;
    cclasstrib_sugerido?: string;
    final_cst?: string;
    final_cclasstrib?: string;
    dispositivo_legal?: string;
    final_dispositivo?: string;
    tipo_tratamento?: string;
    cst_atual?: string;
    cclasstrib_atual?: string;
    julgamento?: { justificativa?: string; sinais_de_duvida?: string[]; _modelo?: string };
    escalonamento?: { justificativa?: string; concorda_com_analise_anterior?: boolean; _modelo?: string };
    origem?: string;
    atributos?: Record<string, string>;
    imposto_seletivo?: boolean;
    marca?: string;
    unidade?: string;
    categoria?: string;
    gtin?: string;
    erro?: string;
  };
  const podeRevisar = pode("revisar");
  const aprovado = it.revisao_status === "aprovado";
  const cst = it.final_cst ?? it.cst_sugerido;
  const cct = it.final_cclasstrib ?? it.cclasstrib_sugerido;
  const completa = !!(d.codigo_sugerido && cct && !(it.perguntas?.length));

  return (
    <div className="flex flex-col gap-5">
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <SeloStatus status={it.status} />
          <SeloRevisao status={it.revisao_status} />
          {it.origem === "memoria_aprovada" ? (
            <span className="text-2xs text-conferido">Reaproveitado da memória aprovada</span>
          ) : null}
          <span className="ml-auto text-2xs text-tinta-3">
            Linha <span className="num">{it.linha}</span> · código <span className="codigo">{it.codigo_interno}</span>
          </span>
        </div>
        <h2 className="mt-2 text-lg leading-snug">{it.descricao}</h2>
        {it.descricao_normalizada && it.descricao_normalizada !== it.descricao.toLowerCase() ? (
          <p className="text-xs text-tinta-3">Normalizada: {it.descricao_normalizada}</p>
        ) : null}
        <p className="mt-1 flex flex-wrap gap-x-3 text-2xs text-tinta-3">
          {it.marca ? <span>Marca: {it.marca}</span> : null}
          {it.unidade ? <span>Unidade: {it.unidade}</span> : null}
          {it.categoria ? <span>Categoria: {it.categoria}</span> : null}
          {it.gtin ? <span className="codigo">GTIN {it.gtin}</span> : null}
        </p>
      </div>

      <ReguaConferencia atual={d.codigo_atual as CodigoInfo | null} sugerido={d.codigo_sugerido as CodigoInfo | null} />

      {it.perguntas?.length ? <Perguntas perguntas={it.perguntas} podeResponder={podeRevisar && !aprovado} onResponder={(r) => acoes.editar.mutate({ respostas: r })} /> : null}

      <Secao titulo="Enquadramento na LC 214/2025" icone={<Scale className="size-4" />}>
        <div className="grid gap-3 sm:grid-cols-3">
          <Dado rotulo="CST IBS/CBS" valor={<span className="codigo">{cst ?? "—"}</span>} antes={it.cst_atual && it.cst_atual !== cst ? it.cst_atual : undefined} />
          <Dado rotulo="cClassTrib" valor={<span className="codigo">{cct ?? "—"}</span>} antes={it.cclasstrib_atual && it.cclasstrib_atual !== cct ? it.cclasstrib_atual : undefined} />
          <Dado rotulo="Tratamento" valor={(it.tipo_tratamento ?? "—").replaceAll("_", " ")} />
        </div>
        {d.cclasstrib ? (
          <p className="mt-2 text-xs text-tinta-2">
            {String(d.cclasstrib.nome)}
            {Number(d.cclasstrib.perc_red_cbs) > 0 ? ` · redução de ${d.cclasstrib.perc_red_cbs}% (CBS) e ${d.cclasstrib.perc_red_ibs}% (IBS)` : ""}
          </p>
        ) : null}
        {it.final_dispositivo ?? it.dispositivo_legal ? <p className="mt-2 text-sm font-medium">{it.final_dispositivo ?? it.dispositivo_legal}</p> : null}
        {d.trecho_legal ? (
          <blockquote className="mt-2 border-l-2 border-regua-forte pl-3 text-sm text-tinta-2">
            <p className="text-2xs text-tinta-3">
              Anexo {String(d.trecho_legal.anexo)}, item {String(d.trecho_legal.item)} — {String(d.trecho_legal.titulo_anexo ?? "")}
            </p>
            <p className="mt-1 whitespace-pre-line">{String(d.trecho_legal.texto)}</p>
          </blockquote>
        ) : d.regra ? (
          <p className="mt-2 text-sm text-tinta-2">{String(d.regra.descricao_legal)}</p>
        ) : null}
        {it.imposto_seletivo ? <Aviso tom="atencao" className="mt-3">Item sujeito ao Imposto Seletivo (LC 214/2025, Anexo XVII).</Aviso> : null}
      </Secao>

      <Secao titulo="Por que este resultado" icone={<Sparkles className="size-4" />}>
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-xs text-tinta-3">Confiança</span>
          <Confianca valor={it.confianca ?? null} componentes={it.confianca_componentes} />
        </div>
        {it.motivos?.length ? (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {it.motivos.map((m) => (
              <Motivo key={m} codigo={m} textos={d.textos_motivos} />
            ))}
          </div>
        ) : null}
        {it.julgamento?.justificativa ? (
          <p className="mt-3 text-sm">
            <span className="text-2xs text-tinta-3">Análise ({it.julgamento._modelo}): </span>
            {it.julgamento.justificativa}
          </p>
        ) : null}
        {it.escalonamento?.justificativa ? (
          <p className="mt-2 text-sm">
            <span className="text-2xs text-tinta-3">
              Segundo parecer ({it.escalonamento._modelo}, {it.escalonamento.concorda_com_analise_anterior ? "concorda" : "discorda"}):{" "}
            </span>
            {it.escalonamento.justificativa}
          </p>
        ) : null}
        {it.julgamento?.sinais_de_duvida?.length ? (
          <ul className="mt-2 list-disc pl-5 text-xs text-tinta-2">
            {it.julgamento.sinais_de_duvida.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
        ) : null}
        {it.atributos && Object.keys(it.atributos).length ? (
          <p className="mt-2 flex flex-wrap gap-x-3 text-2xs text-tinta-3">
            {Object.entries(it.atributos).map(([k, v]) => (
              <span key={k}>
                {k.replaceAll("_", " ")}: <span className={cn(v === "desconhecido" && "text-ocre")}>{v}</span>
              </span>
            ))}
          </p>
        ) : null}
        {it.erro ? <p className="mt-2 text-xs text-perigo">{it.erro}</p> : null}
      </Secao>

      {!compacto ? (
        <Colapsavel titulo={`Candidatos considerados (${d.candidatos.length})`}>
          <ul className="divide-y divide-regua text-sm">
            {d.candidatos.map((c) => (
              <li key={c.codigo as string} className="flex items-start gap-3 py-2">
                <span className="num w-5 text-2xs text-tinta-3">{String(c.posicao)}</span>
                <span className="codigo w-24 shrink-0">{String(c.formatado)}</span>
                <span className="flex-1 text-xs text-tinta-2">{String(c.descricao_completa)}</span>
                {podeRevisar && !aprovado && c.codigo !== (d.codigo_sugerido as { codigo?: string } | null)?.codigo ? (
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
          <ol className="space-y-2 text-sm">
            {d.historico.length === 0 ? <li className="text-tinta-3">Nenhuma decisão registrada.</li> : null}
            {d.historico.map((h) => (
              <li key={String(h.id)}>
                <span className="font-medium">{ACOES_HIST[String(h.acao)] ?? String(h.acao)}</span> — {String(h.usuario)} · {fmtDataHora(String(h.em))}
                {h.comentario ? <p className="text-xs text-tinta-2">“{String(h.comentario)}”</p> : null}
              </li>
            ))}
          </ol>
          <p className="mt-3 text-2xs text-tinta-3">Chamadas de IA</p>
          <ul className="mt-1 space-y-1 text-2xs text-tinta-2">
            {d.chamadas_ia.map((c, i) => (
              <li key={i} className="codigo">
                {String(c.no)} · {String(c.modelo)} · {String(c.prompt)} · {String(c.modo)} · {String(c.tokens_entrada)}+{String(c.tokens_saida)} tokens · {fmtUSD(Number(c.custo_usd))}
              </li>
            ))}
            {d.chamadas_ia.length === 0 ? <li>Nenhuma (resolvido sem IA).</li> : null}
          </ul>
        </Colapsavel>
      ) : null}

      {podeRevisar ? (
        <div className="sticky bottom-0 -mx-6 flex flex-wrap items-center gap-2 border-t border-regua bg-superficie px-6 py-3">
          {aprovado || it.revisao_status === "rejeitado" ? (
            <>
              {aprovado ? (
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
              <Button variant="confirmar" onClick={() => acoes.aprovar.mutate(undefined)} disabled={!completa || acoes.aprovar.isPending} title={!completa ? "Responda às perguntas ou edite o código antes de aprovar" : undefined}>
                <Check /> Aprovar <Kbd className="border-white/30 bg-white/10 text-white">A</Kbd>
              </Button>
              <Button variant="secundario" onClick={() => setEditando(true)}>
                <Pencil /> Editar <Kbd>E</Kbd>
              </Button>
              <Button variant="fantasma" onClick={() => setRejeitando(true)}>
                <X /> Rejeitar <Kbd>R</Kbd>
              </Button>
              <Button variant="fantasma" className="ml-auto" onClick={() => acoes.reprocessar.mutate()} disabled={acoes.reprocessar.isPending}>
                <RotateCcw /> Reprocessar
              </Button>
            </>
          )}
        </div>
      ) : null}

      <EdicaoAssistida
        aberto={editando}
        aoFechar={() => setEditando(false)}
        tipo={(d.codigo_sugerido as { tipo?: string } | null)?.tipo ?? (d.codigo_atual as { tipo?: string } | null)?.tipo ?? "ncm"}
        aoSalvar={(corpo) => {
          acoes.editar.mutate(corpo, { onSuccess: () => setEditando(false) });
        }}
        salvando={acoes.editar.isPending}
      />
      <Dialog open={rejeitando} onOpenChange={setRejeitando}>
        <DialogContent titulo="Rejeitar sugestão" descricao="O item não entrará na exportação final. Explique o motivo para o histórico.">
          <Rejeicao
            aoConfirmar={(c) => acoes.rejeitar.mutate(c, { onSuccess: () => setRejeitando(false) })}
            enviando={acoes.rejeitar.isPending}
          />
        </DialogContent>
      </Dialog>
      {/* Atalhos do painel (também usados na fila de revisão) */}
      <AtalhosDetalhe
        ativo={podeRevisar && !editando && !rejeitando}
        aprovar={() => completa && !aprovado && acoes.aprovar.mutate(undefined)}
        editar={() => !aprovado && setEditando(true)}
        rejeitar={() => !aprovado && setRejeitando(true)}
        desfazer={() => (aprovado || it.revisao_status === "rejeitado") && acoes.desfazer.mutate()}
      />
    </div>
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

function Perguntas({
  perguntas,
  podeResponder,
  onResponder,
}: {
  perguntas: { atributo: string; pergunta: string; fonte: string }[];
  podeResponder: boolean;
  onResponder: (r: Record<string, string>) => void;
}) {
  return (
    <Aviso tom="atencao" titulo="Perguntas para concluir o enquadramento">
      <ul className="mt-2 space-y-2">
        {perguntas.map((p) => (
          <li key={p.atributo + p.pergunta} className="flex flex-wrap items-center gap-2">
            <span className="flex-1">{p.pergunta}</span>
            {podeResponder && p.atributo !== "regra_aplicavel" ? (
              <span className="flex gap-1">
                <Button tamanho="sm" onClick={() => onResponder({ [p.atributo]: "sim" })}>
                  Sim
                </Button>
                <Button tamanho="sm" onClick={() => onResponder({ [p.atributo]: "nao" })}>
                  Não
                </Button>
              </span>
            ) : null}
          </li>
        ))}
      </ul>
    </Aviso>
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
      <DialogContent titulo="Editar classificação" descricao="Busque pelo código ou pela descrição na tabela oficial vigente. O enquadramento é recalculado na hora." className="max-w-2xl">
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
          <Button variant="secundario" disabled={!escolhido || salvando} onClick={() => escolhido && aoSalvar({ tipo_codigo: tipo, codigo: escolhido.codigo, comentario: comentario || undefined })}>
            Salvar alteração
          </Button>
          <Button variant="confirmar" disabled={!escolhido || salvando} onClick={() => escolhido && aoSalvar({ tipo_codigo: tipo, codigo: escolhido.codigo, comentario: comentario || undefined, aprovar: true })}>
            Salvar e aprovar
          </Button>
        </div>
        <p className="text-2xs text-tinta-3">
          Se o novo código depender de condição legal, as perguntas aparecerão no item antes da aprovação.
        </p>
    </>
  );
}
