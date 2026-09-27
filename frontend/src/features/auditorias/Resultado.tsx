import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
  type SortingState,
} from "@tanstack/react-table";
import { useVirtualizer } from "@tanstack/react-virtual";
import { ArrowDownUp, CheckCheck, Search, Stamp } from "lucide-react";
import { useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { api, ok } from "@/api/client";
import { useAuth } from "@/auth/auth";
import { Confianca, EstadoErro, EstadoVazio, mensagemErro, SeloStatus, STATUS } from "@/components/dominio";
import { Aviso, Button, Dialog, DialogContent, Input, Painel, Select, Skeleton } from "@/components/ui/primitives";
import { fmtCodigo, fmtNum, fmtPct } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useItens, type Auditoria, type LinhaItem } from "./comum";
import { DetalheItem } from "./DetalheItem";

const col = createColumnHelper<LinhaItem>();

export interface Filtros {
  busca: string;
  status: string[];
  motivo: string;
  confiancaMax: string;
  anexo: string;
  capitulo: string;
  revisao: string;
  agrupar: "" | "status" | "capitulo" | "anexo" | "motivo";
}

export const FILTROS_INICIAIS: Filtros = { busca: "", status: [], motivo: "", confiancaMax: "", anexo: "", capitulo: "", revisao: "", agrupar: "" };

export function filtrarItens(itens: LinhaItem[], f: Filtros): LinhaItem[] {
  const termo = f.busca.trim().toLowerCase();
  const digitos = termo.replace(/\D/g, "");
  return itens.filter((i) => {
    if (f.status.length && !f.status.includes(i.status)) return false;
    if (f.motivo && !i.motivos.includes(f.motivo)) return false;
    if (f.revisao && i.revisao_status !== f.revisao) return false;
    if (f.anexo && (i.anexo ?? "sem") !== f.anexo) return false;
    if (f.capitulo && (i.codigo_sugerido ?? i.codigo_atual ?? "").slice(0, 2) !== f.capitulo) return false;
    if (f.confiancaMax && (i.confianca ?? 0) >= Number(f.confiancaMax)) return false;
    if (termo) {
      const alvo = `${i.descricao} ${i.codigo_interno}`.toLowerCase();
      const codigos = `${i.codigo_atual ?? ""} ${i.codigo_sugerido ?? ""} ${i.cclasstrib_sugerido ?? ""}`;
      if (!alvo.includes(termo) && !(digitos.length >= 2 && codigos.includes(digitos))) return false;
    }
    return true;
  });
}

type Linha = { tipo: "grupo"; chave: string; rotulo: string; n: number } | { tipo: "item"; item: LinhaItem; indice: number };

export function Resultado({ auditoria }: { auditoria: Auditoria }) {
  const itens = useItens(auditoria.id);
  const { pode } = useAuth();
  const [f, setF] = useState<Filtros>(FILTROS_INICIAIS);
  const fAdiado = useDeferredValue(f);
  const [sorting, setSorting] = useState<SortingState>([]);
  const [aberto, setAberto] = useState<string | null>(null);
  const [cursor, setCursor] = useState(0);
  const [lote, setLote] = useState(false);
  const textos = auditoria.textos_motivos;

  const dados = useMemo(() => filtrarItens(itens.data ?? [], fAdiado), [itens.data, fAdiado]);
  const colunas = useMemo(
    () => [
      col.accessor("linha", { header: "Linha", size: 64, cell: (c) => <span className="num text-tinta-3">{c.getValue()}</span> }),
      col.accessor("codigo_interno", { header: "Código", size: 110, cell: (c) => <span className="codigo text-xs">{c.getValue()}</span> }),
      col.accessor("descricao", { header: "Descrição", size: 360, cell: (c) => <span className="truncate">{c.getValue()}</span> }),
      col.accessor("codigo_atual", {
        header: "Atual",
        size: 118,
        cell: (c) => {
          const i = c.row.original;
          const mudou = i.codigo_sugerido && i.codigo_atual !== i.codigo_sugerido;
          return <span className={cn("codigo text-xs", mudou && "text-ocre line-through decoration-ocre/70")}>{fmtCodigo(i.tipo_codigo, c.getValue())}</span>;
        },
      }),
      col.accessor("codigo_sugerido", {
        header: "Sugerido",
        size: 118,
        cell: (c) => {
          const i = c.row.original;
          const mudou = c.getValue() && i.codigo_atual !== c.getValue();
          return <span className={cn("codigo text-xs", mudou && "font-medium text-caneta")}>{fmtCodigo(i.tipo_codigo, c.getValue())}</span>;
        },
      }),
      col.accessor("cclasstrib_sugerido", { header: "cClassTrib", size: 96, cell: (c) => <span className="codigo text-xs">{c.getValue() ?? "—"}</span> }),
      col.accessor("confianca", { header: "Confiança", size: 110, sortUndefined: "last", cell: (c) => <Confianca valor={c.getValue()} /> }),
      col.accessor("status", { header: "Resultado", size: 150, cell: (c) => <SeloStatus status={c.getValue()} /> }),
      col.accessor("revisao_status", {
        header: "Revisão",
        size: 100,
        cell: (c) =>
          c.getValue() === "aprovado" ? (
            <span className="inline-flex items-center gap-1 text-2xs font-semibold text-conferido"><Stamp className="size-3.5" aria-hidden />Aprovado</span>
          ) : c.getValue() === "rejeitado" ? (
            <span className="text-2xs text-perigo">Rejeitado</span>
          ) : (
            <span className="text-2xs text-tinta-3">Pendente</span>
          ),
      }),
      col.accessor((r) => r.motivos.length, {
        id: "motivos",
        header: "Motivos",
        size: 170,
        cell: (c) => {
          const m = c.row.original.motivos;
          return m.length ? <span className="truncate text-2xs text-tinta-2">{m.map((x) => textos[x]?.[0] ?? x).join(" · ")}</span> : null;
        },
      }),
    ],
    [textos],
  );
  const tabela = useReactTable({
    data: dados,
    columns: colunas,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });
  const rowModel = tabela.getRowModel();
  const linhasOrdenadas = useMemo(() => rowModel.rows.map((r) => r.original), [rowModel]);
  const rowPorId = useMemo(() => new Map(rowModel.rows.map((r) => [r.original.id, r])), [rowModel]);

  // Agrupamento: cabeçalhos de grupo intercalados na lista virtual.
  const linhas: Linha[] = useMemo(() => {
    if (!f.agrupar) return linhasOrdenadas.map((item, indice) => ({ tipo: "item", item, indice }));
    const chaveDe = (i: LinhaItem): [string, string] => {
      if (f.agrupar === "status") return [i.status, STATUS[i.status as keyof typeof STATUS]?.rotulo ?? i.status];
      if (f.agrupar === "anexo") return [i.anexo ?? "sem", i.anexo ? `Anexo ${i.anexo}` : "Sem anexo (tributação integral ou indefinido)"];
      if (f.agrupar === "motivo") return [i.motivos[0] ?? "nenhum", i.motivos[0] ? textos[i.motivos[0]]?.[0] ?? i.motivos[0] : "Sem motivo"];
      const cap = (i.codigo_sugerido ?? i.codigo_atual ?? "").slice(0, 2) || "--";
      return [cap, `Capítulo ${cap}`];
    };
    const grupos = new Map<string, { rotulo: string; itens: LinhaItem[] }>();
    for (const i of linhasOrdenadas) {
      const [k, r] = chaveDe(i);
      if (!grupos.has(k)) grupos.set(k, { rotulo: r, itens: [] });
      grupos.get(k)!.itens.push(i);
    }
    const saida: Linha[] = [];
    let indice = 0;
    for (const [k, g] of [...grupos.entries()].sort((a, b) => a[0].localeCompare(b[0]))) {
      saida.push({ tipo: "grupo", chave: k, rotulo: g.rotulo, n: g.itens.length });
      for (const item of g.itens) saida.push({ tipo: "item", item, indice: indice++ });
    }
    return saida;
  }, [linhasOrdenadas, f.agrupar, textos]);

  const itensVisiveis = useMemo(() => linhas.filter((l): l is Extract<Linha, { tipo: "item" }> => l.tipo === "item").map((l) => l.item), [linhas]);
  const container = useRef<HTMLDivElement>(null);
  const virtual = useVirtualizer({ count: linhas.length, getScrollElement: () => container.current, estimateSize: (i) => (linhas[i]?.tipo === "grupo" ? 34 : 44), overscan: 12 });

  // Navegação por teclado na tabela: ↑/↓ ou J/K move, Enter abre o detalhe.
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (aberto || lote) return;
      const alvo = e.target as HTMLElement;
      if (alvo.closest("input, textarea, select, [role=combobox], [role=dialog]")) return;
      if (e.key === "ArrowDown" || e.key === "j") {
        e.preventDefault();
        setCursor((c) => Math.min(itensVisiveis.length - 1, c + 1));
      } else if (e.key === "ArrowUp" || e.key === "k") {
        e.preventDefault();
        setCursor((c) => Math.max(0, c - 1));
      } else if (e.key === "Enter" && itensVisiveis[cursor]) {
        e.preventDefault();
        setAberto(itensVisiveis[cursor]!.id);
      }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [aberto, lote, itensVisiveis, cursor]);
  useEffect(() => {
    const pos = linhas.findIndex((l) => l.tipo === "item" && l.indice === cursor);
    if (pos >= 0) virtual.scrollToIndex(pos, { align: "auto" });
  }, [cursor, linhas, virtual]);

  const todos = useMemo(() => itens.data ?? [], [itens.data]);
  const contagem = useMemo(() => {
    const c: Record<string, number> = {};
    const m: Record<string, number> = {};
    const anexos = new Set<string>();
    const caps = new Set<string>();
    let aprovados = 0;
    for (const i of todos) {
      c[i.status] = (c[i.status] ?? 0) + 1;
      for (const x of i.motivos) m[x] = (m[x] ?? 0) + 1;
      anexos.add(i.anexo ?? "sem");
      const cap = (i.codigo_sugerido ?? i.codigo_atual ?? "").slice(0, 2);
      if (cap) caps.add(cap);
      if (i.revisao_status === "aprovado") aprovados++;
    }
    return { c, m, anexos: [...anexos].sort(), caps: [...caps].sort(), aprovados };
  }, [todos]);

  if (itens.isError) return <EstadoErro erro={itens.error} aoTentar={() => void itens.refetch()} />;
  if (itens.isLoading) return <Skeleton className="h-[60vh]" />;
  if (todos.length === 0) return <EstadoVazio titulo="Nenhum item concluído ainda" descricao="Os itens aparecem aqui à medida que são analisados." />;

  const larguraTotal = tabela.getTotalSize();
  const alternarStatus = (s: string) => setF((x) => ({ ...x, status: x.status.includes(s) ? x.status.filter((y) => y !== s) : [...x.status, s] }));

  return (
    <div className="grid gap-4">
      {/* Resumo: os totais também são filtros */}
      <div className="grid gap-3 lg:grid-cols-[repeat(3,minmax(0,1fr))_minmax(0,1.3fr)]">
        {(["confirmado", "corrigido", "analise_humana"] as const).map((s) => {
          const S = STATUS[s];
          const I = S.icone;
          const ativo = f.status.includes(s);
          return (
            <button key={s} onClick={() => alternarStatus(s)} aria-pressed={ativo} className={cn("rounded-lg border bg-superficie px-4 py-3 text-left transition-colors hover:border-regua-forte", ativo ? cn(S.borda, S.fundo) : "border-regua")}>
              <span className={cn("flex items-center gap-1.5 text-xs", S.cor)}>
                <I className="size-3.5" aria-hidden /> {S.rotulo}
              </span>
              <span className="num mt-1 block text-2xl font-semibold">{fmtNum(contagem.c[s] ?? 0)}</span>
              <span className="text-2xs text-tinta-3">{fmtPct((contagem.c[s] ?? 0) / todos.length)} dos itens</span>
            </button>
          );
        })}
        <Painel className="px-4 py-3">
          <p className="text-xs text-tinta-3">Principais motivos de análise</p>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {Object.entries(contagem.m)
              .sort((a, b) => b[1] - a[1])
              .slice(0, 6)
              .map(([m, n]) => (
                <button key={m} onClick={() => setF((x) => ({ ...x, motivo: x.motivo === m ? "" : m }))} className={cn("rounded border px-1.5 py-0.5 text-2xs", f.motivo === m ? "border-tinta bg-tinta text-papel" : "border-regua bg-superficie-2 text-tinta-2 hover:border-regua-forte")}>
                  {textos[m]?.[0] ?? m} <span className="num">{fmtNum(n)}</span>
                </button>
              ))}
          </div>
          <p className="mt-2 text-2xs text-tinta-3">
            Revisão: <span className="num font-medium text-tinta">{fmtNum(contagem.aprovados)}</span> de <span className="num">{fmtNum(todos.length)}</span> aprovados
          </p>
        </Painel>
      </div>

      {/* Filtros */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative w-72">
          <Search className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-tinta-3" aria-hidden />
          <Input value={f.busca} onChange={(e) => setF((x) => ({ ...x, busca: e.target.value }))} placeholder="Buscar descrição, código ou NCM" className="pl-8" aria-label="Buscar itens" />
        </div>
        <Select aria-label="Filtrar por motivo" className="w-56" valor={f.motivo || "_"} aoMudar={(v) => setF((x) => ({ ...x, motivo: v === "_" ? "" : v }))} opcoes={[{ valor: "_", rotulo: "Todos os motivos" }, ...Object.keys(contagem.m).map((m) => ({ valor: m, rotulo: textos[m]?.[0] ?? m }))]} />
        <Select aria-label="Filtrar por confiança" className="w-44" valor={f.confiancaMax || "_"} aoMudar={(v) => setF((x) => ({ ...x, confiancaMax: v === "_" ? "" : v }))} opcoes={[{ valor: "_", rotulo: "Qualquer confiança" }, { valor: "0.9", rotulo: "Abaixo de 90%" }, { valor: "0.75", rotulo: "Abaixo de 75%" }, { valor: "0.5", rotulo: "Abaixo de 50%" }]} />
        <Select aria-label="Filtrar por anexo" className="w-40" valor={f.anexo || "_"} aoMudar={(v) => setF((x) => ({ ...x, anexo: v === "_" ? "" : v }))} opcoes={[{ valor: "_", rotulo: "Todos os anexos" }, ...contagem.anexos.map((a) => ({ valor: a, rotulo: a === "sem" ? "Sem anexo" : `Anexo ${a}` }))]} />
        <Select aria-label="Filtrar por capítulo" className="w-40" valor={f.capitulo || "_"} aoMudar={(v) => setF((x) => ({ ...x, capitulo: v === "_" ? "" : v }))} opcoes={[{ valor: "_", rotulo: "Todos os capítulos" }, ...contagem.caps.map((c) => ({ valor: c, rotulo: `Capítulo ${c}` }))]} />
        <Select aria-label="Filtrar por revisão" className="w-40" valor={f.revisao || "_"} aoMudar={(v) => setF((x) => ({ ...x, revisao: v === "_" ? "" : v }))} opcoes={[{ valor: "_", rotulo: "Toda revisão" }, { valor: "pendente", rotulo: "Pendentes" }, { valor: "aprovado", rotulo: "Aprovados" }, { valor: "rejeitado", rotulo: "Rejeitados" }]} />
        <Select aria-label="Agrupar" className="w-40" valor={f.agrupar || "_"} aoMudar={(v) => setF((x) => ({ ...x, agrupar: (v === "_" ? "" : v) as Filtros["agrupar"] }))} opcoes={[{ valor: "_", rotulo: "Sem agrupar" }, { valor: "status", rotulo: "Agrupar: resultado" }, { valor: "anexo", rotulo: "Agrupar: anexo" }, { valor: "capitulo", rotulo: "Agrupar: capítulo" }, { valor: "motivo", rotulo: "Agrupar: motivo" }]} />
        {JSON.stringify(f) !== JSON.stringify(FILTROS_INICIAIS) ? (
          <Button variant="fantasma" tamanho="sm" onClick={() => setF(FILTROS_INICIAIS)}>
            Limpar filtros
          </Button>
        ) : null}
        <span className="num ml-auto text-xs text-tinta-3">{fmtNum(dados.length)} de {fmtNum(todos.length)} itens</span>
        {pode("revisar") ? (
          <Button variant="secundario" onClick={() => setLote(true)}>
            <CheckCheck /> Aprovar em lote
          </Button>
        ) : null}
      </div>

      {/* Tabela virtualizada */}
      <Painel className="overflow-hidden">
        <div ref={container} className="h-[64vh] overflow-auto" role="grid" aria-rowcount={dados.length} aria-label="Itens da auditoria">
          <div style={{ minWidth: larguraTotal }}>
            <div className="sticky top-0 z-10 flex border-b border-regua bg-superficie-2 text-2xs text-tinta-3" role="row">
              {tabela.getHeaderGroups()[0]!.headers.map((h) => (
                <button key={h.id} role="columnheader" style={{ width: h.getSize() }} className="flex shrink-0 items-center gap-1 px-3 py-2 text-left font-medium hover:text-tinta" onClick={h.column.getToggleSortingHandler()} aria-sort={h.column.getIsSorted() === "asc" ? "ascending" : h.column.getIsSorted() === "desc" ? "descending" : "none"}>
                  {flexRender(h.column.columnDef.header, h.getContext())}
                  {h.column.getIsSorted() ? <ArrowDownUp className="size-3" aria-hidden /> : null}
                </button>
              ))}
            </div>
            <div style={{ height: virtual.getTotalSize(), position: "relative" }}>
              {virtual.getVirtualItems().map((v) => {
                const l = linhas[v.index]!;
                if (l.tipo === "grupo")
                  return (
                    <div key={`g-${l.chave}`} style={{ transform: `translateY(${v.start}px)`, height: v.size }} className="absolute inset-x-0 flex items-center gap-2 border-b border-regua bg-papel px-3 text-xs font-medium">
                      {l.rotulo} <span className="num text-tinta-3">{fmtNum(l.n)}</span>
                    </div>
                  );
                const row = rowPorId.get(l.item.id);
                if (!row) return null;
                const selecionada = l.indice === cursor;
                return (
                  <div
                    key={l.item.id}
                    role="row"
                    aria-selected={selecionada}
                    onClick={() => {
                      setCursor(l.indice);
                      setAberto(l.item.id);
                    }}
                    style={{ transform: `translateY(${v.start}px)`, height: v.size }}
                    className={cn("absolute inset-x-0 flex cursor-pointer items-center border-b border-regua text-sm hover:bg-superficie-2", selecionada && "bg-caneta-suave/60 shadow-[inset_3px_0_0_var(--caneta)]")}
                  >
                    {row.getVisibleCells().map((c) => (
                      <div key={c.id} role="gridcell" style={{ width: c.column.getSize() }} className="flex shrink-0 items-center overflow-hidden px-3">
                        {flexRender(c.column.columnDef.cell, c.getContext())}
                      </div>
                    ))}
                  </div>
                );
              })}
            </div>
          </div>
        </div>
        <p className="border-t border-regua px-4 py-2 text-2xs text-tinta-3">
          <kbd className="codigo">↑ ↓</kbd> navegar · <kbd className="codigo">Enter</kbd> abrir detalhe · clique no cabeçalho para ordenar
        </p>
      </Painel>

      <Dialog open={!!aberto} onOpenChange={(o) => !o && setAberto(null)}>
        {aberto ? (
          <DialogContent lateral titulo="Detalhe do item" className="max-w-2xl">
            <DetalheItem itemId={aberto} auditId={auditoria.id} />
          </DialogContent>
        ) : null}
      </Dialog>
      <AprovacaoLote aberto={lote} aoFechar={() => setLote(false)} auditId={auditoria.id} />
    </div>
  );
}

function AprovacaoLote({ aberto, aoFechar, auditId }: { aberto: boolean; aoFechar: () => void; auditId: string }) {
  const qc = useQueryClient();
  const [status, setStatus] = useState("confirmado");
  const [conf, setConf] = useState("0.95");
  const [previa, setPrevia] = useState<{ total: number; amostra: Record<string, unknown>[] } | null>(null);
  const corpo = { status: status === "todos" ? ["confirmado", "corrigido"] : [status], confianca_min: Number(conf), motivos_excluir: ["SUJEITO_A_IMPOSTO_SELETIVO"] };
  const ver = useMutation({
    mutationFn: () => ok(api.POST("/api/auditorias/{audit_id}/aprovar-lote", { params: { path: { audit_id: auditId } }, body: { ...corpo, confirmar: false } })),
    onSuccess: (r) => setPrevia({ total: r.total, amostra: r.amostra }),
    onError: (e) => toast.error(mensagemErro(e)),
  });
  const desfazer = useMutation({
    mutationFn: (loteId: string) => ok(api.POST("/api/auditorias/{audit_id}/lotes/{lote_id}/desfazer", { params: { path: { audit_id: auditId, lote_id: loteId } } })),
    onSuccess: (r) => {
      toast.success(r.mensagem);
      void qc.invalidateQueries({ queryKey: ["itens", auditId] });
    },
  });
  const confirmar = useMutation({
    mutationFn: () => ok(api.POST("/api/auditorias/{audit_id}/aprovar-lote", { params: { path: { audit_id: auditId } }, body: { ...corpo, confirmar: true, total_esperado: previa?.total } })),
    onSuccess: (r) => {
      toast.success(r.mensagem, r.lote_id ? { action: { label: "Desfazer", onClick: () => desfazer.mutate(r.lote_id!) }, duration: 12000 } : undefined);
      void qc.invalidateQueries({ queryKey: ["itens", auditId] });
      void qc.invalidateQueries({ queryKey: ["auditoria", auditId] });
      setPrevia(null);
      aoFechar();
    },
    onError: (e) => toast.error(mensagemErro(e)),
  });
  useEffect(() => {
    if (aberto) ver.mutate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [aberto, status, conf]);
  return (
    <Dialog open={aberto} onOpenChange={(o) => !o && aoFechar()}>
      <DialogContent titulo="Aprovar em lote" descricao="Aprova de uma vez itens com classificação completa, sem perguntas pendentes. Itens sujeitos ao Imposto Seletivo ficam de fora.">
        <div className="grid grid-cols-2 gap-3">
          <Select aria-label="Resultado" valor={status} aoMudar={setStatus} opcoes={[{ valor: "confirmado", rotulo: "Confirmados" }, { valor: "corrigido", rotulo: "Corrigidos" }, { valor: "todos", rotulo: "Confirmados e corrigidos" }]} />
          <Select aria-label="Confiança mínima" valor={conf} aoMudar={setConf} opcoes={[{ valor: "0.98", rotulo: "Confiança ≥ 98%" }, { valor: "0.95", rotulo: "Confiança ≥ 95%" }, { valor: "0.9", rotulo: "Confiança ≥ 90%" }]} />
        </div>
        {previa ? (
          <Aviso tom={previa.total ? "info" : "atencao"} titulo={`${fmtNum(previa.total)} itens serão aprovados`}>
            {previa.amostra.length ? (
              <ul className="mt-1 space-y-0.5 text-xs">
                {previa.amostra.slice(0, 5).map((a, i) => (
                  <li key={i} className="truncate">
                    <span className="codigo">{String(a.codigo)}</span> · {String(a.descricao)}
                  </li>
                ))}
                {previa.total > 5 ? <li className="text-tinta-3">e mais {fmtNum(previa.total - 5)}…</li> : null}
              </ul>
            ) : (
              "Nenhum item atende a esses critérios."
            )}
          </Aviso>
        ) : (
          <Skeleton className="h-16" />
        )}
        <div className="flex justify-end gap-2">
          <Button variant="fantasma" onClick={aoFechar}>
            Cancelar
          </Button>
          <Button variant="confirmar" disabled={!previa?.total || confirmar.isPending} onClick={() => confirmar.mutate()}>
            <CheckCheck /> Aprovar {previa ? fmtNum(previa.total) : ""} itens
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
