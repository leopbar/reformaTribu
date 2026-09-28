import { Link, useParams } from "@tanstack/react-router";
import { ArrowLeft, CheckCircle2, Keyboard } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Cabecalho, EstadoVazio, SeloStatus } from "@/components/dominio";
import { Button, Dialog, DialogContent, Kbd, Painel, Progresso, Select, Skeleton } from "@/components/ui/primitives";
import { fmtCodigo, fmtNum } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useAuditoria, useItens, type LinhaItem } from "./comum";
import { DetalheItem } from "./DetalheItem";

type Ordem = "incertos" | "linha" | "analise";

const REVISAVEIS = ["classificado", "aguardando_informacao", "revisao_contador", "revisao_especialista"];
const PESO_CONFIANCA: Record<string, number> = { baixa: 0, incompleta: 1, media: 2, alta: 3 };

export function ordenarFila(itens: LinhaItem[], filtro: string, ordem: Ordem): LinhaItem[] {
  const fila = itens.filter(
    (i) => i.revisao_status === "pendente" && REVISAVEIS.includes(i.status) && (filtro === "todos" || i.status === filtro),
  );
  const peso: Record<string, number> = { revisao_especialista: 0, revisao_contador: 1, aguardando_informacao: 2, classificado: 3 };
  if (ordem === "incertos")
    return fila.sort((a, b) => (PESO_CONFIANCA[a.confianca_global ?? ""] ?? 0) - (PESO_CONFIANCA[b.confianca_global ?? ""] ?? 0) || a.linha - b.linha);
  if (ordem === "analise") return fila.sort((a, b) => (peso[a.status] ?? 3) - (peso[b.status] ?? 3) || a.linha - b.linha);
  return fila.sort((a, b) => a.linha - b.linha);
}

export function FilaRevisaoPage() {
  const { id } = useParams({ strict: false }) as { id: string };
  const aud = useAuditoria(id);
  const itens = useItens(id);
  if (!aud.data || !itens.data) return <Skeleton className="h-[70vh]" />;
  return <Fila id={id} nome={aud.data.nome} itens={itens.data} />;
}

function Fila({ id, nome, itens }: { id: string; nome: string; itens: LinhaItem[] }) {
  const [filtro, setFiltroEstado] = useState("todos");
  const [ordem, setOrdemEstado] = useState<Ordem>("analise");
  // A fila é "congelada" ao abrir e ao mudar filtros, para que itens aprovados não sumam sob o cursor.
  const [fila, setFila] = useState<LinhaItem[]>(() => ordenarFila([...itens], "todos", "analise"));
  const [atualId, setAtualId] = useState<string | null>(() => fila[0]?.id ?? null);
  const [ajuda, setAjuda] = useState(false);
  const [revisadosSessao, setRevisadosSessao] = useState(0);
  const refazer = (f: string, o: Ordem) => {
    const nova = ordenarFila([...itens], f, o);
    setFila(nova);
    setAtualId(nova[0]?.id ?? null);
  };
  const setFiltro = (f: string) => {
    setFiltroEstado(f);
    refazer(f, ordem);
  };
  const setOrdem = (o: Ordem) => {
    setOrdemEstado(o);
    refazer(filtro, o);
  };
  const status = useMemo(() => new Map(itens.map((i) => [i.id, i])), [itens]);
  const pos = Math.max(0, fila.findIndex((i) => i.id === atualId));

  const ir = useCallback(
    (delta: number) => {
      const n = Math.min(fila.length - 1, Math.max(0, pos + delta));
      if (fila[n]) setAtualId(fila[n]!.id);
    },
    [fila, pos],
  );
  const proximoPendente = useCallback(() => {
    for (let i = pos + 1; i < fila.length; i++) {
      if (status.get(fila[i]!.id)?.revisao_status === "pendente") return setAtualId(fila[i]!.id);
    }
    ir(1);
  }, [fila, pos, status, ir]);

  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      const alvo = e.target as HTMLElement;
      if (alvo.closest("input, textarea, [role=dialog]") || e.ctrlKey || e.metaKey || e.altKey) return;
      const acoes: Record<string, () => void> = {
        j: () => ir(1), ArrowDown: () => ir(1), ArrowRight: () => ir(1),
        k: () => ir(-1), ArrowUp: () => ir(-1), ArrowLeft: () => ir(-1),
        "?": () => setAjuda(true),
      };
      const acao = acoes[e.key];
      if (acao) {
        e.preventDefault();
        acao();
      }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [ir]);

  const listaRef = useRef<HTMLOListElement>(null);
  useEffect(() => {
    listaRef.current?.querySelector(`[data-id="${atualId}"]`)?.scrollIntoView({ block: "nearest" });
  }, [atualId]);

  const revisados = fila.filter((i) => status.get(i.id)?.revisao_status !== "pendente").length;

  return (
    <>
      <Cabecalho
        voltar={
          <Link to="/auditorias/$id" params={{ id }} className="inline-flex items-center gap-1 text-xs text-tinta-3 hover:text-tinta">
            <ArrowLeft className="size-3.5" /> {nome}
          </Link>
        }
        titulo="Fila de revisão"
        subtitulo={`${fmtNum(revisados)} de ${fmtNum(fila.length)} revisados nesta fila · ${fmtNum(revisadosSessao)} decisões nesta sessão`}
        acoes={
          <>
            <Select aria-label="Filtrar fila" className="w-48" valor={filtro} aoMudar={setFiltro} opcoes={[{ valor: "todos", rotulo: "Todos os níveis" }, { valor: "revisao_especialista", rotulo: "Revisão do especialista" }, { valor: "revisao_contador", rotulo: "Revisão do contador" }, { valor: "aguardando_informacao", rotulo: "Aguardando informação" }, { valor: "classificado", rotulo: "Classificados" }]} />
            <Select aria-label="Ordem" className="w-52" valor={ordem} aoMudar={(v) => setOrdem(v as Ordem)} opcoes={[{ valor: "analise", rotulo: "Especialista, depois contador" }, { valor: "incertos", rotulo: "Menor confiança primeiro" }, { valor: "linha", rotulo: "Ordem da planilha" }]} />
            <Button variant="fantasma" onClick={() => setAjuda(true)}>
              <Keyboard /> Atalhos <Kbd>?</Kbd>
            </Button>
          </>
        }
      />
      <Progresso valor={fila.length ? (revisados / fila.length) * 100 : 0} rotulo="Progresso da revisão" className="mb-4" />
      {fila.length === 0 ? (
        <EstadoVazio icone={<CheckCircle2 className="size-8 text-conferido" />} titulo="Nada pendente nesta fila" descricao="Todos os itens deste filtro já foram revisados. Mude o filtro ou vá para a exportação." acao={<Button asChild variant="primario"><Link to="/auditorias/$id/exportar" params={{ id }}>Ir para exportação</Link></Button>} />
      ) : (
        <div className="grid gap-4 lg:grid-cols-[20rem_1fr]">
          <Painel className="hidden h-[calc(100dvh-15rem)] overflow-hidden lg:block">
            <ol ref={listaRef} className="h-full overflow-y-auto" aria-label="Itens da fila">
              {fila.map((i, n) => {
                const atual = status.get(i.id) ?? i;
                return (
                  <li key={i.id} data-id={i.id}>
                    <button
                      onClick={() => setAtualId(i.id)}
                      aria-current={i.id === atualId}
                      className={cn("flex w-full flex-col gap-1 border-b border-regua px-3 py-2 text-left hover:bg-superficie-2", i.id === atualId && "bg-caneta-suave shadow-[inset_3px_0_0_var(--caneta)]", atual.revisao_status !== "pendente" && "opacity-55")}
                    >
                      <span className="flex items-center gap-2">
                        <span className="num text-2xs text-tinta-3">{n + 1}</span>
                        <SeloStatus status={atual.status} compacto />
                        <span className="truncate text-sm">{i.descricao}</span>
                      </span>
                      <span className="codigo pl-6 text-2xs text-tinta-3">
                        {fmtCodigo(i.tipo_codigo, i.codigo_atual)} → {fmtCodigo(i.tipo_codigo, atual.codigo_sugerido)}
                        {atual.revisao_status === "aprovado" ? <span className="ml-2 font-sans text-conferido">aprovado</span> : null}
                        {atual.revisao_status === "rejeitado" ? <span className="ml-2 font-sans text-perigo">rejeitado</span> : null}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ol>
          </Painel>
          <Painel className="p-6">
            {atualId ? (
              <DetalheItem
                key={atualId}
                itemId={atualId}
                auditId={id}
                aoConcluir={(acao) => {
                  if (acao === "aprovar" || acao === "rejeitar") {
                    setRevisadosSessao((n) => n + 1);
                    setTimeout(proximoPendente, 180);
                  }
                }}
              />
            ) : null}
            <p className="mt-4 text-2xs text-tinta-3">
              Item {fmtNum(pos + 1)} de {fmtNum(fila.length)} · <Kbd>J</Kbd>/<Kbd>K</Kbd> próximo/anterior
            </p>
          </Painel>
        </div>
      )}
      <Dialog open={ajuda} onOpenChange={setAjuda}>
        <DialogContent titulo="Atalhos de teclado">
          <dl className="grid grid-cols-[8rem_1fr] gap-y-2 text-sm">
            {[
              ["J ou ↓", "Próximo item"],
              ["K ou ↑", "Item anterior"],
              ["A", "Aprovar o enquadramento (e ir para o próximo)"],
              ["E", "Corrigir o código (o item é reanalisado)"],
              ["R", "Rejeitar sugestão"],
              ["U", "Desfazer a última decisão do item"],
              ["Ctrl + K", "Paleta de comandos"],
              ["?", "Mostrar estes atalhos"],
            ].map(([k, d]) => (
              <div key={k} className="contents">
                <dt><Kbd>{k}</Kbd></dt>
                <dd>{d}</dd>
              </div>
            ))}
          </dl>
        </DialogContent>
      </Dialog>
    </>
  );
}
