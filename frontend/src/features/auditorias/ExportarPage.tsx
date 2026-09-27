import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "@tanstack/react-router";
import { ArrowDown, ArrowLeft, ArrowUp, Download, FileSpreadsheet, FileText, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { api, baixarArquivo, ok } from "@/api/client";
import { useAuth } from "@/auth/auth";
import { Cabecalho, mensagemErro } from "@/components/dominio";
import { Aviso, Button, Campo, Checkbox, Dialog, DialogContent, Input, Painel, Select, Skeleton } from "@/components/ui/primitives";
import { fmtDataHora, fmtNum } from "@/lib/format";
import { useAuditoria, useItens } from "./comum";

export function ExportarPage() {
  const { id } = useParams({ strict: false }) as { id: string };
  const { pode } = useAuth();
  const qc = useQueryClient();
  const aud = useAuditoria(id);
  const itens = useItens(id);
  const [layout, setLayout] = useState<string>("padrao");
  const layouts = useQuery({ queryKey: ["layouts"], queryFn: () => ok(api.GET("/api/layouts-exportacao")) });
  const jobs = useQuery({
    queryKey: ["exportacoes", id],
    queryFn: () => ok(api.GET("/api/auditorias/{audit_id}/exportacoes", { params: { path: { audit_id: id } } })),
    refetchInterval: (q) => (q.state.data?.some((j) => j.status === "na_fila" || j.status === "gerando") ? 2000 : false),
  });
  const gerar = useMutation({
    mutationFn: (formato: "xlsx" | "csv" | "pdf") =>
      ok(api.POST("/api/auditorias/{audit_id}/exportacoes", { params: { path: { audit_id: id } }, body: { formato, layout_id: layout === "padrao" ? null : layout } })),
    onSuccess: () => {
      toast.success("Gerando o arquivo…");
      void qc.invalidateQueries({ queryKey: ["exportacoes", id] });
    },
    onError: (e) => toast.error(mensagemErro(e)),
  });
  const total = itens.data?.length ?? 0;
  const aprovados = itens.data?.filter((i) => i.revisao_status === "aprovado").length ?? 0;
  if (!aud.data) return <Skeleton className="h-64" />;
  return (
    <>
      <Cabecalho
        voltar={
          <Link to="/auditorias/$id" params={{ id }} className="inline-flex items-center gap-1 text-xs text-tinta-3 hover:text-tinta">
            <ArrowLeft className="size-3.5" /> {aud.data.nome}
          </Link>
        }
        titulo="Exportar"
        subtitulo="Somente itens aprovados entram na exportação final para o sistema de gestão."
      />
      <div className="grid gap-6 lg:grid-cols-[1fr_24rem]">
        <div className="grid gap-6">
          {aprovados < total ? (
            <Aviso tom="atencao" titulo={`${fmtNum(total - aprovados)} itens ainda não foram aprovados`}>
              Eles não entram na planilha exportada. <Link to="/auditorias/$id/revisar" params={{ id }} className="text-caneta underline">Continuar a revisão</Link>
            </Aviso>
          ) : (
            <Aviso tom="ok" titulo="Todos os itens foram revisados" />
          )}
          <Painel className="p-5">
            <h2 className="text-base">Planilha para o sistema de gestão</h2>
            <p className="mt-1 text-sm text-tinta-3">{fmtNum(aprovados)} itens aprovados serão exportados com o layout escolhido.</p>
            <div className="mt-4 flex flex-wrap items-end gap-3">
              <Campo rotulo="Layout" className="w-64">
                <Select aria-label="Layout" valor={layout} aoMudar={setLayout} opcoes={[{ valor: "padrao", rotulo: "Layout padrão" }, ...(layouts.data?.layouts ?? []).map((l) => ({ valor: l.id, rotulo: l.nome }))]} />
              </Campo>
              {pode("exportar") ? <EditorLayout /> : null}
              <Button variant="primario" disabled={!aprovados || gerar.isPending || !pode("exportar")} onClick={() => gerar.mutate("xlsx")}>
                <FileSpreadsheet /> Gerar XLSX
              </Button>
              <Button variant="secundario" disabled={!aprovados || gerar.isPending || !pode("exportar")} onClick={() => gerar.mutate("csv")}>
                Gerar CSV
              </Button>
            </div>
          </Painel>
          <Painel className="p-5">
            <h2 className="text-base">Relatório de auditoria (PDF)</h2>
            <p className="mt-1 text-sm text-tinta-3">Resumo, metodologia, versões da base legal usada, itens alterados e trilha de aprovação.</p>
            <Button className="mt-4" variant="secundario" disabled={gerar.isPending || !pode("exportar")} onClick={() => gerar.mutate("pdf")}>
              <FileText /> Gerar relatório PDF
            </Button>
          </Painel>
        </div>
        <Painel className="h-fit">
          <h2 className="border-b border-regua px-5 py-3 text-base">Arquivos gerados</h2>
          <ul>
            {(jobs.data ?? []).length === 0 ? <li className="px-5 py-6 text-center text-sm text-tinta-3">Nenhum arquivo gerado ainda.</li> : null}
            {(jobs.data ?? []).map((j) => (
              <li key={j.id} className="flex items-center gap-3 border-b border-regua px-5 py-3 last:border-0">
                <span className="flex-1">
                  <span className="block text-sm font-medium">{j.arquivo_nome ?? j.formato.toUpperCase()}</span>
                  <span className="text-2xs text-tinta-3">
                    {fmtDataHora(j.created_at)} · {j.status === "concluida" ? (j.formato === "pdf" ? "pronto" : `${fmtNum(j.total_itens)} itens`) : j.status === "falhou" ? "falhou" : "gerando…"}
                  </span>
                  {j.erro ? <span className="block text-2xs text-perigo">{j.erro}</span> : null}
                </span>
                {j.status === "concluida" ? (
                  <Button tamanho="iconeSm" variant="fantasma" aria-label="Baixar" onClick={() => void baixarArquivo(`/api/exportacoes/${j.id}/arquivo`, j.arquivo_nome ?? "exportacao").catch((e) => toast.error(mensagemErro(e)))}>
                    <Download />
                  </Button>
                ) : null}
              </li>
            ))}
          </ul>
        </Painel>
      </div>
    </>
  );
}

function EditorLayout() {
  const qc = useQueryClient();
  const [aberto, setAberto] = useState(false);
  const op = useQuery({ queryKey: ["layouts"], queryFn: () => ok(api.GET("/api/layouts-exportacao")) });
  const [nome, setNome] = useState("");
  const [sep, setSep] = useState(";");
  const [fmt, setFmt] = useState(false);
  const [cols, setCols] = useState<{ campo: string; titulo: string }[]>([]);
  const abrir = () => {
    const c = op.data;
    if (c) setCols(c.padrao.map((k) => ({ campo: k, titulo: c.campos[k] ?? k })));
    setNome("");
    setAberto(true);
  };
  const salvar = useMutation({
    mutationFn: () => ok(api.POST("/api/layouts-exportacao", { body: { nome, colunas: cols, separador_csv: sep, ncm_formatado: fmt } })),
    onSuccess: () => {
      toast.success("Layout salvo");
      void qc.invalidateQueries({ queryKey: ["layouts"] });
      setAberto(false);
    },
    onError: (e) => toast.error(mensagemErro(e)),
  });
  const mover = (i: number, d: number) => setCols((c) => {
    const n = [...c];
    const [x] = n.splice(i, 1);
    n.splice(i + d, 0, x!);
    return n;
  });
  const disponiveis = Object.entries(op.data?.campos ?? {}).filter(([k]) => !cols.some((c) => c.campo === k));
  return (
    <>
      <Button variant="fantasma" onClick={abrir}>
        <Plus /> Novo layout
      </Button>
      <Dialog open={aberto} onOpenChange={setAberto}>
        <DialogContent titulo="Novo layout de exportação" descricao="Escolha as colunas, a ordem e os títulos esperados pelo sistema de gestão do cliente." className="max-w-2xl">
          <Campo rotulo="Nome do layout" htmlFor="ln">
            <Input id="ln" value={nome} onChange={(e) => setNome(e.target.value)} placeholder="Ex.: Importação ERP da loja" />
          </Campo>
          <ol className="grid max-h-72 gap-1 overflow-y-auto">
            {cols.map((c, i) => (
              <li key={c.campo} className="flex items-center gap-2">
                <span className="w-40 text-xs text-tinta-3">{op.data?.campos[c.campo]}</span>
                <Input value={c.titulo} onChange={(e) => setCols((x) => x.map((y, j) => (j === i ? { ...y, titulo: e.target.value } : y)))} className="h-8" aria-label={`Título da coluna ${op.data?.campos[c.campo]}`} />
                <Button tamanho="iconeSm" variant="fantasma" aria-label="Subir" disabled={i === 0} onClick={() => mover(i, -1)}><ArrowUp /></Button>
                <Button tamanho="iconeSm" variant="fantasma" aria-label="Descer" disabled={i === cols.length - 1} onClick={() => mover(i, 1)}><ArrowDown /></Button>
                <Button tamanho="iconeSm" variant="fantasma" aria-label="Remover" onClick={() => setCols((x) => x.filter((_, j) => j !== i))}><Trash2 /></Button>
              </li>
            ))}
          </ol>
          {disponiveis.length ? (
            <Select aria-label="Adicionar coluna" valor={undefined} placeholder="Adicionar coluna…" aoMudar={(k) => setCols((c) => [...c, { campo: k, titulo: op.data?.campos[k] ?? k }])} opcoes={disponiveis.map(([k, v]) => ({ valor: k, rotulo: v }))} />
          ) : null}
          <div className="flex flex-wrap items-center gap-4 text-sm">
            <label className="flex items-center gap-2">
              Separador CSV
              <Select aria-label="Separador" className="w-28" valor={sep} aoMudar={setSep} opcoes={[{ valor: ";", rotulo: "; (ponto e vírgula)" }, { valor: ",", rotulo: ", (vírgula)" }, { valor: "|", rotulo: "| (barra)" }]} />
            </label>
            <label className="flex items-center gap-2">
              <Checkbox checked={fmt} onCheckedChange={(v) => setFmt(v === true)} /> NCM com pontos (3401.11.90)
            </label>
          </div>
          <div className="flex justify-end">
            <Button variant="primario" disabled={nome.trim().length < 2 || !cols.length || salvar.isPending} onClick={() => salvar.mutate()}>
              Salvar layout
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
