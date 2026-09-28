import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "@tanstack/react-router";
import { AlertTriangle, ArrowLeft, Check, Download, Plus, RefreshCw, Sparkles, Trash2, Upload, X } from "lucide-react";
import { useRef, useState } from "react";
import { toast } from "sonner";
import { api, baixarArquivo, ok, requisicao, type Schemas } from "@/api/client";
import { Cabecalho, EstadoErro, mensagemErro } from "@/components/dominio";
import { Aviso, Button, Campo, Checkbox, Input, Painel, Select, Skeleton, Textarea } from "@/components/ui/primitives";
import { fmtCodigo, fmtDataHora, fmtNum, soDigitos } from "@/lib/format";
import { cn } from "@/lib/utils";

const FONTES: Record<string, string> = { ncm: "Tabela NCM", nbs: "Tabela NBS", cclasstrib: "CST e cClassTrib (IBS/CBS)", lc214: "LC 214/2025 (texto e anexos)", normas: "Atos normativos" };
const STATUS_REGRA: Record<string, { rotulo: string; cor: string }> = {
  pendente_revisao: { rotulo: "Pendente de revisão", cor: "text-ocre" },
  aprovada: { rotulo: "Aprovada", cor: "text-conferido" },
  invalida: { rotulo: "Inválida", cor: "text-perigo" },
  rejeitada: { rotulo: "Rejeitada", cor: "text-tinta-3" },
  substituida: { rotulo: "Substituída", cor: "text-tinta-3" },
};

export function BaseReferenciaPage() {
  const qc = useQueryClient();
  const st = useQuery({ queryKey: ["ref-status"], queryFn: () => ok(api.GET("/api/referencia/status")), refetchInterval: 10_000 });
  const versoes = useQuery({ queryKey: ["ref-versoes"], queryFn: () => ok(api.GET("/api/referencia/versoes", { params: { query: {} } })), refetchInterval: 10_000 });
  const importar = useMutation({
    mutationFn: (fonte: string) => ok(api.POST("/api/referencia/importar", { body: { fonte: fonte as "ncm" } })),
    onSuccess: (r) => {
      toast.success(r.mensagem);
      setTimeout(() => void qc.invalidateQueries({ queryKey: ["ref-versoes"] }), 3000);
    },
    onError: (e) => toast.error(mensagemErro(e)),
  });
  const importarAto = useMutation({
    mutationFn: (chave: string) => ok(api.POST("/api/referencia/importar-ato", { body: { chave } })),
    onSuccess: (r) => {
      toast.success(r.mensagem);
      setTimeout(() => void qc.invalidateQueries({ queryKey: ["ref-status"] }), 5000);
    },
    onError: (e) => toast.error(mensagemErro(e)),
  });
  const arquivo = useRef<HTMLInputElement>(null);
  const [fonteUpload, setFonteUpload] = useState("ncm");
  const enviar = useMutation({
    mutationFn: async (f: File) => {
      const fd = new FormData();
      fd.append("fonte", fonteUpload);
      fd.append("arquivo", f);
      return (await requisicao("/api/referencia/upload", { method: "POST", body: fd })).json();
    },
    onSuccess: () => toast.success("Arquivo recebido; importação iniciada."),
    onError: (e) => toast.error(mensagemErro(e)),
  });
  if (st.isError) return <EstadoErro erro={st.error} />;
  if (!st.data) return <Skeleton className="h-64" />;
  return (
    <>
      <Cabecalho titulo="Base normativa e tabelas oficiais" subtitulo="Global e compartilhada por todas as organizações. Cada importação cria uma versão nova com data e hash; nada é sobrescrito. É daqui que o analista cita a lei." acoes={<Button asChild variant="secundario"><Link to="/referencia/regras">Regras curadas (opcional)</Link></Button>} />
      {!st.data.completa ? <Aviso tom="atencao" titulo="Base incompleta" className="mb-4">Faltando: {st.data.faltando.map((f) => FONTES[f] ?? f).join(", ")}. Sem elas o analista não consegue investigar: os itens vão para revisão do contador.</Aviso> : null}
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        {Object.entries(FONTES).filter(([f]) => f !== "normas").map(([f, rotulo]) => {
          const v = st.data.fontes[f];
          return (
            <Painel key={f} className="flex flex-col gap-2 p-4">
              <p className="text-sm font-medium">{rotulo}</p>
              {v ? (
                <>
                  <p className="text-xs text-tinta-2">{v.rotulo}</p>
                  <p className="text-2xs text-tinta-3">Coletada em {fmtDataHora(v.coletado_em)} ({v.modo_coleta === "download" ? "download" : "envio manual"})</p>
                  <p className="codigo text-2xs text-tinta-3">sha256 {v.sha256.slice(0, 16)}…</p>
                  {["ncm", "nbs", "lc214"].includes(f) ? <p className={cn("text-2xs", v.embeddings_status === "concluido" ? "text-conferido" : "text-ocre")}>Busca semântica: {v.embeddings_status === "concluido" ? `pronta (${v.embeddings_modelo})` : v.embeddings_status}</p> : null}
                </>
              ) : (
                <p className="text-xs text-perigo">Não importada</p>
              )}
              <Button tamanho="sm" className="mt-auto" onClick={() => importar.mutate(f)} disabled={importar.isPending}><RefreshCw /> Baixar da fonte oficial</Button>
            </Painel>
          );
        })}
      </div>
      <Painel className="mt-6">
        <h2 className="border-b border-regua px-5 py-3 text-base">Atos normativos da reforma</h2>
        <p className="px-5 pt-3 text-sm text-tinta-3">Além da LC 214/2025, o analista consulta estes atos (artigos vigentes na data da classificação), com busca por significado.</p>
        <ul className="divide-y divide-regua">
          {st.data.atos_normativos.map((a) => (
            <li key={a.chave} className="flex flex-wrap items-center gap-3 px-5 py-3 text-sm">
              <span className="min-w-0 flex-1">
                <span className="font-medium">{a.rotulo}</span> — <span className="text-tinta-2">{a.ementa}</span>
                <span className="block text-2xs text-tinta-3">
                  {a.versao ? `Importado em ${fmtDataHora(a.versao.coletado_em)} · busca semântica: ${a.versao.embeddings_status === "concluido" ? "pronta" : a.versao.embeddings_status}` : "Não importado"} ·{" "}
                  <a href={a.url} target="_blank" rel="noreferrer" className="underline">fonte oficial</a>
                </span>
              </span>
              <Button tamanho="sm" onClick={() => importarAto.mutate(a.chave)} disabled={importarAto.isPending}>
                <RefreshCw /> {a.versao ? "Atualizar" : "Importar"}
              </Button>
            </li>
          ))}
        </ul>
      </Painel>
      <Painel className="mt-6 p-5">
        <h2 className="text-base">Envio manual</h2>
        <p className="mt-1 text-sm text-tinta-3">Use quando o download automático não estiver disponível ou a fonte mudar de formato.</p>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <Select aria-label="Fonte" className="w-72" valor={fonteUpload} aoMudar={setFonteUpload} opcoes={Object.entries(FONTES).filter(([k]) => k !== "normas").map(([k, v]) => ({ valor: k, rotulo: v }))} />
          <input ref={arquivo} type="file" className="sr-only" onChange={(e) => e.target.files?.[0] && enviar.mutate(e.target.files[0])} />
          <Button onClick={() => arquivo.current?.click()} disabled={enviar.isPending}><Upload /> Enviar arquivo</Button>
        </div>
        <p className="mt-2 text-xs text-tinta-3">Onde obter: {st.data.instrucoes[fonteUpload]}</p>
      </Painel>
      <Painel className="mt-6">
        <h2 className="border-b border-regua px-5 py-3 text-base">Histórico de versões</h2>
        <table className="w-full text-sm">
          <thead><tr className="border-b border-regua text-left text-2xs text-tinta-3"><th className="px-5 py-2 font-medium">Fonte</th><th className="px-3 py-2 font-medium">Versão</th><th className="px-3 py-2 font-medium">Situação</th><th className="px-3 py-2 font-medium">Coleta</th><th className="px-3 py-2 font-medium">Por</th><th className="px-5 py-2 font-medium">Estatísticas</th></tr></thead>
          <tbody>
            {(versoes.data ?? []).map((v) => (
              <tr key={v.id} className="border-b border-regua align-top last:border-0">
                <td className="px-5 py-2">{FONTES[v.fonte]}</td>
                <td className="px-3 py-2 text-xs">{v.rotulo}{v.erro ? <span className="block text-perigo">{v.erro}</span> : null}</td>
                <td className="px-3 py-2">{v.status}</td>
                <td className="px-3 py-2 text-xs">{fmtDataHora(v.coletado_em)}<span className="block text-2xs text-tinta-3 break-all">{v.url_origem ?? v.arquivo_nome}</span></td>
                <td className="px-3 py-2 text-xs">{v.importado_por_email ?? "agendado"}</td>
                <td className="codigo px-5 py-2 text-2xs text-tinta-3">{Object.entries(v.estatisticas).filter(([, x]) => typeof x !== "object").map(([k, x]) => `${k}: ${x}`).join(" · ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Painel>
    </>
  );
}

export function RegrasPage() {
  const qc = useQueryClient();
  const navegar = useNavigate();
  const [status, setStatus] = useState("pendente_revisao");
  const [anexo, setAnexo] = useState("_");
  const [busca, setBusca] = useState("");
  const [pagina, setPagina] = useState(1);
  const [soDivergentes, setSoDivergentes] = useState(false);
  const [sel, setSel] = useState<string[]>([]);
  const q = useQuery({
    queryKey: ["regras", status, anexo, busca, pagina, soDivergentes],
    queryFn: () => ok(api.GET("/api/regras", { params: { query: { status: status === "_" ? undefined : status, anexo: anexo === "_" ? undefined : anexo, busca: busca || undefined, com_divergencias: soDivergentes || undefined, pagina, por_pagina: 100 } } })),
  });
  const lote = useMutation({
    mutationFn: (confirmar: boolean) => ok(api.POST("/api/regras/aprovar-lote", { body: { ids: sel, confirmar } })),
    onSuccess: (r, confirmar) => {
      if (!confirmar) {
        if (confirm(`${r.aprovaveis} regras podem ser aprovadas${r.bloqueadas.length ? ` (${r.bloqueadas.length} bloqueadas por erros, divergências com a lei ou condições textuais não estruturadas — revise-as individualmente)` : ""}. Você revisou o texto legal de cada uma? Confirmar a aprovação?`)) lote.mutate(true);
        return;
      }
      toast.success(`${r.aprovadas} regras aprovadas`);
      setSel([]);
      void qc.invalidateQueries({ queryKey: ["regras"] });
    },
    onError: (e) => toast.error(mensagemErro(e)),
  });
  const sugerir = useMutation({
    mutationFn: () => ok(api.POST("/api/regras/sugerir-condicoes", { body: { ids: sel } })),
    onSuccess: (r) => toast.success(r.mensagem),
    onError: (e) => toast.error(mensagemErro(e)),
  });
  const importarYaml = useRef<HTMLInputElement>(null);
  const itens = q.data?.itens ?? [];
  return (
    <>
      <Cabecalho
        voltar={<Link to="/referencia" className="inline-flex items-center gap-1 text-xs text-tinta-3 hover:text-tinta"><ArrowLeft className="size-3.5" /> Base de referência</Link>}
        titulo="Regras legais (LC 214/2025)"
        subtitulo="Opcional. O analista raciocina a partir do texto legal e das tabelas oficiais; uma regra aprovada aqui vira precedente: aumenta a confiança quando confirma a conclusão e aponta conflito quando diverge."
        acoes={
          <>
            <Button variant="fantasma" onClick={() => void baixarArquivo("/api/regras-yaml", "regras.yaml").catch((e) => toast.error(mensagemErro(e)))}><Download /> Exportar YAML</Button>
            <input ref={importarYaml} type="file" accept=".yaml,.yml" className="sr-only" onChange={async (e) => {
              const f = e.target.files?.[0];
              if (!f) return;
              const fd = new FormData();
              fd.append("arquivo", f);
              try {
                const r = await (await requisicao("/api/regras-yaml", { method: "POST", body: fd })).json();
                toast.success(`${r.importadas} regras importadas como pendentes`);
                void qc.invalidateQueries({ queryKey: ["regras"] });
              } catch (err) {
                toast.error(mensagemErro(err));
              }
            }} />
            <Button variant="fantasma" onClick={() => importarYaml.current?.click()}><Upload /> Importar YAML</Button>
          </>
        }
      />
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Select aria-label="Situação" className="w-56" valor={status} aoMudar={(v) => { setStatus(v); setPagina(1); }} opcoes={[{ valor: "_", rotulo: "Todas (exceto substituídas)" }, ...Object.entries(STATUS_REGRA).map(([k, v]) => ({ valor: k, rotulo: `${v.rotulo} (${fmtNum(q.data?.por_status[k] ?? 0)})` }))]} />
        <Select aria-label="Anexo" className="w-40" valor={anexo} aoMudar={(v) => { setAnexo(v); setPagina(1); }} opcoes={[{ valor: "_", rotulo: "Todos os anexos" }, ...(q.data?.anexos ?? []).map((a) => ({ valor: a, rotulo: `Anexo ${a}` }))]} />
        <Input className="w-72" placeholder="Buscar texto, cClassTrib ou dispositivo" value={busca} onChange={(e) => { setBusca(e.target.value); setPagina(1); }} aria-label="Buscar regras" />
        <label className="flex items-center gap-2 text-sm">
          <Checkbox checked={soDivergentes} onCheckedChange={(v) => { setSoDivergentes(!!v); setPagina(1); }} />
          Só com divergências
        </label>
        {sel.length ? (
          <span className="ml-auto flex gap-2">
            <Button variant="secundario" onClick={() => sugerir.mutate()} disabled={sugerir.isPending}><Sparkles /> Sugerir condições com IA ({sel.length})</Button>
            <Button variant="confirmar" onClick={() => lote.mutate(false)} disabled={lote.isPending}><Check /> Aprovar selecionadas ({sel.length})</Button>
          </span>
        ) : null}
      </div>
      {q.isLoading ? <Skeleton className="h-64" /> : null}
      <Painel className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-regua text-left text-2xs text-tinta-3">
              <th className="w-10 px-3 py-2"><Checkbox aria-label="Selecionar todas" checked={itens.length > 0 && sel.length === itens.length} onCheckedChange={(v) => setSel(v ? itens.map((i) => i.id) : [])} /></th>
              <th className="px-3 py-2 font-medium">Dispositivo</th>
              <th className="px-3 py-2 font-medium">Descrição legal</th>
              <th className="px-3 py-2 font-medium">cClassTrib</th>
              <th className="px-3 py-2 text-right font-medium">Códigos</th>
              <th className="px-3 py-2 font-medium">Situação</th>
            </tr>
          </thead>
          <tbody>
            {itens.map((r) => (
              <tr key={r.id} className="cursor-pointer border-b border-regua align-top last:border-0 hover:bg-superficie-2" onClick={() => void navegar({ to: "/referencia/regras/$id", params: { id: r.id } })}>
                <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}><Checkbox aria-label={`Selecionar ${r.slug}`} checked={sel.includes(r.id)} onCheckedChange={(v) => setSel((s) => (v ? [...s, r.id] : s.filter((x) => x !== r.id)))} /></td>
                <td className="px-3 py-2 text-xs">{r.dispositivo_legal}<span className="codigo block text-2xs text-tinta-3">{r.slug} v{r.versao}</span></td>
                <td className="max-w-lg px-3 py-2 text-xs text-tinta-2">{r.descricao_legal}</td>
                <td className="codigo px-3 py-2 text-xs">{r.cclasstrib ?? "—"}</td>
                <td className="num px-3 py-2 text-right text-xs">{fmtNum(r.total_codigos)}</td>
                <td className="px-3 py-2 text-xs">
                  <span className={STATUS_REGRA[r.status]?.cor}>{STATUS_REGRA[r.status]?.rotulo ?? r.status}</span>
                  {r.erros ? <span className="block text-2xs text-perigo">{r.erros} erro(s)</span> : null}
                  {r.divergencias ? <span className="block text-2xs font-medium text-perigo">{r.divergencias} divergência(s) com a lei</span> : null}
                  {r.avisos - r.divergencias > 0 ? <span className="block text-2xs text-ocre">{r.avisos - r.divergencias} aviso(s)</span> : null}
                  {r.total_condicoes ? <span className="block text-2xs text-tinta-3">{r.total_condicoes} condição(ões)</span> : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="flex items-center justify-between border-t border-regua px-5 py-2 text-xs text-tinta-3">
          <span>{fmtNum(q.data?.total ?? 0)} regras</span>
          <span className="flex gap-2">
            <Button tamanho="sm" disabled={pagina === 1} onClick={() => setPagina((p) => p - 1)}>Anterior</Button>
            <Button tamanho="sm" disabled={pagina * 100 >= (q.data?.total ?? 0)} onClick={() => setPagina((p) => p + 1)}>Próxima</Button>
          </span>
        </div>
      </Painel>
    </>
  );
}

type Condicao = Schemas["CondicaoIn"];

export function RegraRevisaoPage() {
  const { id } = useParams({ strict: false }) as { id: string };
  const q = useQuery({ queryKey: ["regra", id], queryFn: () => ok(api.GET("/api/regras/{regra_id}", { params: { path: { regra_id: id } } })) });
  if (q.isError) return <EstadoErro erro={q.error} />;
  if (!q.data) return <Skeleton className="h-96" />;
  return <RevisaoRegra key={`${id}-${q.dataUpdatedAt}`} id={id} dados={q.data} />;
}

function RevisaoRegra({ id, dados }: { id: string; dados: Schemas["RegraDetalhe"] }) {
  const qc = useQueryClient();
  const navegar = useNavigate();
  const q = { data: dados };
  const inicial = dados.regra as Record<string, unknown>;
  const [cond, setCond] = useState<Condicao[]>(() => (inicial.condicoes as Condicao[]) ?? []);
  const [cst, setCst] = useState(() => (inicial.cst_ibs_cbs as string) ?? "");
  const [cct, setCct] = useState(() => (inicial.cclasstrib as string) ?? "");
  const [nota, setNota] = useState("");
  const [controverso, setControverso] = useState(() => !!inicial.controverso);
  const [notaContro, setNotaContro] = useState(() => (inicial.nota_controversia as string) ?? "");
  const tipo = (inicial.tipo_codigo as string | null) ?? "ncm";
  const codigosIniciais = dados.codigos.map((c) => String(c.codigo));
  const excecoesIniciais = dados.excecoes.filter((e) => e.codigo).map((e) => String(e.codigo));
  const [codigos, setCodigos] = useState<string[]>(codigosIniciais);
  const [excCod, setExcCod] = useState<string[]>(excecoesIniciais);
  const excTexto = dados.excecoes.filter((e) => !e.codigo).map((e) => ({ descricao: (e.descricao as string | null) ?? null, trecho_legal: (e.trecho_legal as string | null) ?? null }));
  const alterouCodigos = codigos.join() !== codigosIniciais.join() || excCod.join() !== excecoesIniciais.join();
  const descricoes: Record<string, string> = { ...dados.descricoes };
  for (const c of dados.codigos) if (c.descricao) descricoes[String(c.codigo)] = String(c.descricao);
  for (const e of dados.excecoes) if (e.codigo && e.descricao_oficial) descricoes[String(e.codigo)] = String(e.descricao_oficial);
  const item = (c: string): ItemCodigo => ({ codigo: c, formatado: fmtCodigo(tipo, c), descricao: descricoes[c] ?? null });
  const unir = (lista: string[], novos: string[]) => [...lista, ...novos.filter((c) => !lista.includes(c))].sort();
  const aplicar = (acao: string, cods: string[]) => {
    if (acao === "incluir_na_abrangencia") {
      setCodigos((l) => unir(l, cods));
      setExcCod((l) => l.filter((c) => !cods.includes(c)));
      const presos = cods.filter((c) => excCod.some((e) => e !== c && c.startsWith(e)));
      if (presos.length) toast.warning(`${presos.length} código(s) continuam cobertos por uma exceção mais ampla (ex.: ${fmtCodigo(tipo, excCod.find((e) => presos[0]?.startsWith(e)) ?? "")}). Remova-a nas exceções, se for o caso.`);
    } else if (acao === "remover_da_abrangencia") {
      const exatos = cods.filter((c) => codigos.includes(c));
      setCodigos((l) => l.filter((c) => !exatos.includes(c)));
      const viaPrefixo = cods.filter((c) => !exatos.includes(c));
      if (viaPrefixo.length) setExcCod((l) => unir(l, viaPrefixo));
    } else if (acao === "adicionar_excecao") {
      setExcCod((l) => unir(l, cods));
    }
    toast.info("Alteração aplicada na regra. Clique em “Salvar e revalidar” para conferir de novo.");
  };
  const salvar = useMutation({
    mutationFn: () => ok(api.PATCH("/api/regras/{regra_id}", { params: { path: { regra_id: id } }, body: { condicoes: cond, cst_ibs_cbs: cst || null, cclasstrib: cct || null, controverso, nota_controversia: notaContro || null, ...(alterouCodigos ? { codigos, excecoes: [...excCod.map((codigo) => ({ codigo })), ...excTexto] } : {}) } })),
    onSuccess: (d) => {
      toast.success("Regra salva e revalidada");
      const novoId = String((d.regra as Record<string, unknown>).id);
      if (novoId !== id) void navegar({ to: "/referencia/regras/$id", params: { id: novoId } });
      else void qc.invalidateQueries({ queryKey: ["regra", id] });
    },
    onError: (e) => toast.error(mensagemErro(e)),
  });
  const decidir = useMutation({
    mutationFn: (acao: "aprovar" | "rejeitar") =>
      acao === "aprovar"
        ? ok(api.POST("/api/regras/{regra_id}/aprovar", { params: { path: { regra_id: id } }, body: { nota: nota || null } }))
        : ok(api.POST("/api/regras/{regra_id}/rejeitar", { params: { path: { regra_id: id } }, body: { nota: nota || null } })),
    onSuccess: (_, acao) => {
      toast.success(acao === "aprovar" ? "Regra aprovada" : "Regra rejeitada");
      void qc.invalidateQueries({ queryKey: ["regra", id] });
      void qc.invalidateQueries({ queryKey: ["regras"] });
    },
    onError: (e) => toast.error(mensagemErro(e)),
  });
  const sugerir = useMutation({
    mutationFn: () => ok(api.POST("/api/regras/sugerir-condicoes", { body: { ids: [id] } })),
    onSuccess: () => {
      toast.success("Sugestão em andamento; recarregando em alguns segundos…");
      setTimeout(() => void qc.invalidateQueries({ queryKey: ["regra", id] }), 15000);
    },
    onError: (e) => toast.error(mensagemErro(e)),
  });
  const r = q.data.regra as Record<string, unknown> & { status: string; erros_validacao: { mensagem: string }[]; avisos: Divergencia[] };
  const editavel = ["pendente_revisao", "invalida", "aprovada"].includes(r.status);
  const decidivel = r.status === "pendente_revisao" || r.status === "invalida";
  const divergencias = (r.avisos ?? []).filter((a) => a.divergencia);
  const outrosAvisos = (r.avisos ?? []).filter((a) => !a.divergencia);
  const exigemJustificativa = divergencias.filter((a) => a.gravidade !== "info").length;
  const faltaJustificativa = exigemJustificativa > 0 && nota.trim().length < 15;
  return (
    <>
      <Cabecalho
        voltar={<Link to="/referencia/regras" className="inline-flex items-center gap-1 text-xs text-tinta-3 hover:text-tinta"><ArrowLeft className="size-3.5" /> Regras</Link>}
        titulo={String(r.dispositivo_legal)}
        subtitulo={<span><span className="codigo">{String(r.slug)} v{String(r.versao)}</span> · <span className={STATUS_REGRA[r.status]?.cor}>{STATUS_REGRA[r.status]?.rotulo}</span> · origem: {String(r.origem).replaceAll("_", " ")}</span>}
      />
      {r.erros_validacao?.length ? <Aviso tom="erro" titulo="Erros de validação (a regra não pode ser aprovada)" className="mb-4"><ul className="list-disc pl-5">{r.erros_validacao.map((e, i) => <li key={i}>{e.mensagem}</li>)}</ul></Aviso> : null}
      {divergencias.length ? <PainelDivergencias itens={divergencias} item={item} editavel={editavel} aoAplicar={aplicar} /> : null}
      {outrosAvisos.length ? <Aviso tom="atencao" titulo="Avisos" className="mb-4"><ul className="list-disc pl-5">{outrosAvisos.map((a, i) => <li key={i}>{a.mensagem}</li>)}</ul></Aviso> : null}
      <div className="grid gap-6 xl:grid-cols-2">
        <Painel className="p-5">
          <p className="text-2xs font-medium text-tinta-3">Texto legal original</p>
          {q.data.texto_legal ? (
            <>
              <p className="mt-1 text-xs text-tinta-3">Anexo {String(q.data.texto_legal.anexo)} — {String(q.data.texto_legal.titulo_anexo ?? "")}, item {String(q.data.texto_legal.item)}</p>
              <p className="mt-3 whitespace-pre-line font-serif text-base leading-relaxed">{String(q.data.texto_legal.texto)}</p>
            </>
          ) : (
            <p className="mt-3 whitespace-pre-line text-base leading-relaxed">{String(r.descricao_legal)}</p>
          )}
          {q.data.cclasstrib ? (
            <div className="mt-4 border-t border-regua pt-3 text-sm">
              <p className="text-2xs text-tinta-3">Tabela oficial cClassTrib</p>
              <p><span className="codigo">{String(q.data.cclasstrib.codigo)}</span> (CST {String(q.data.cclasstrib.cst)}) — {String(q.data.cclasstrib.nome)}</p>
              {q.data.cclasstrib.texto_regulamento ? <p className="mt-2 text-xs text-tinta-2">{String(q.data.cclasstrib.texto_regulamento)}</p> : null}
            </div>
          ) : null}
          <div className="mt-4 border-t border-regua pt-3">
            <p className="text-2xs text-tinta-3">Códigos abrangidos ({fmtNum(codigos.length)}){alterouCodigos ? <span className="ml-2 text-ocre">alterado, não salvo</span> : null}</p>
            <ListaCodigos itens={codigos.map(item)} aoRemover={editavel ? (c) => setCodigos((l) => l.filter((x) => x !== c)) : undefined} />
            {editavel ? <AdicionarCodigo tipo={tipo} rotulo="Incluir código no benefício" aoAdicionar={(c) => setCodigos((l) => unir(l, [c]))} /> : null}
            <p className="mt-4 text-2xs text-tinta-3">Exceções ({fmtNum(excCod.length + excTexto.length)})</p>
            {excTexto.map((e, i) => (
              <p key={i} className="mt-1 text-xs"><AlertTriangle className="mr-1 inline size-3 text-ocre" />Em palavras: {e.descricao ?? ""}</p>
            ))}
            <ListaCodigos alerta itens={excCod.map(item)} aoRemover={editavel ? (c) => setExcCod((l) => l.filter((x) => x !== c)) : undefined} />
            {editavel ? <AdicionarCodigo tipo={tipo} rotulo="Adicionar exceção" aoAdicionar={(c) => setExcCod((l) => unir(l, [c]))} /> : null}
          </div>
        </Painel>

        <Painel className="flex flex-col gap-4 p-5">
          <p className="text-2xs font-medium text-tinta-3">Regra estruturada</p>
          <div className="grid grid-cols-3 gap-3">
            <Campo rotulo="Tratamento"><p className="text-sm">{String(r.tipo_tratamento).replaceAll("_", " ")}</p></Campo>
            <Campo rotulo="CST" htmlFor="rcst"><Input id="rcst" className="codigo" value={cst} disabled={!editavel || r.tipo_tratamento === "imposto_seletivo"} onChange={(e) => setCst(e.target.value)} /></Campo>
            <Campo rotulo="cClassTrib" htmlFor="rcct"><Input id="rcct" className="codigo" value={cct} disabled={!editavel || r.tipo_tratamento === "imposto_seletivo"} onChange={(e) => setCct(e.target.value)} /></Campo>
          </div>
          <div>
            <div className="mb-2 flex items-center justify-between">
              <p className="text-sm font-medium">Condições legais</p>
              <span className="flex gap-2">
                {decidivel ? <Button tamanho="sm" variant="fantasma" onClick={() => sugerir.mutate()} disabled={sugerir.isPending}><Sparkles /> Sugerir com IA</Button> : null}
                {editavel ? <Button tamanho="sm" onClick={() => setCond((c) => [...c, { atributo: "", fonte: "item", deve_ser: "nao", pergunta: "", trecho_legal: "" }])}><Plus /> Condição</Button> : null}
              </span>
            </div>
            {cond.length === 0 ? <p className="text-xs text-tinta-3">Nenhuma condição além do código. Se o texto legal impõe alguma (ex.: “sem adição de açúcar”), estruture-a aqui.</p> : null}
            <ul className="grid gap-3">
              {cond.map((c, i) => (
                <li key={i} className="grid gap-2 rounded-md border border-regua p-3">
                  <div className="grid grid-cols-[1fr_8rem_6rem_auto] gap-2">
                    <Input aria-label="Atributo" className="codigo" placeholder="atributo (ex.: adicao_acucar)" list="catalogo-atributos" value={c.atributo} onChange={(e) => setCond((x) => x.map((y, j) => (j === i ? { ...y, atributo: e.target.value } : y)))} />
                    <Select aria-label="Fonte" valor={c.fonte} aoMudar={(v) => setCond((x) => x.map((y, j) => (j === i ? { ...y, fonte: v } : y)))} opcoes={[{ valor: "item", rotulo: "Item" }, { valor: "empresa", rotulo: "Empresa" }, { valor: "operacao", rotulo: "Operação" }]} />
                    <Input aria-label="Deve ser" value={c.deve_ser} onChange={(e) => setCond((x) => x.map((y, j) => (j === i ? { ...y, deve_ser: e.target.value } : y)))} />
                    <Button tamanho="iconeSm" variant="fantasma" aria-label="Remover condição" onClick={() => setCond((x) => x.filter((_, j) => j !== i))}><Trash2 /></Button>
                  </div>
                  <Input aria-label="Pergunta ao revisor" placeholder="Pergunta ao revisor (ex.: O suco tem adição de açúcar?)" value={c.pergunta} onChange={(e) => setCond((x) => x.map((y, j) => (j === i ? { ...y, pergunta: e.target.value } : y)))} />
                  <Input aria-label="Trecho legal" placeholder="Trecho literal da lei" value={c.trecho_legal ?? ""} onChange={(e) => setCond((x) => x.map((y, j) => (j === i ? { ...y, trecho_legal: e.target.value } : y)))} />
                </li>
              ))}
            </ul>
            <datalist id="catalogo-atributos">{q.data.catalogo_atributos.map((a) => <option key={String(a.chave)} value={String(a.chave)}>{String(a.pergunta)}</option>)}</datalist>
          </div>
          <label className="flex items-center gap-2 text-sm"><Checkbox checked={controverso} onCheckedChange={(v) => setControverso(v === true)} disabled={!editavel} /> Caso controverso (fontes especializadas divergem — itens vão sempre para análise humana)</label>
          {controverso ? <Textarea aria-label="Nota sobre a controvérsia" placeholder="Descreva a divergência e as fontes" value={notaContro} onChange={(e) => setNotaContro(e.target.value)} /> : null}
          {editavel ? <Button onClick={() => salvar.mutate()} disabled={salvar.isPending}>{r.status === "aprovada" ? "Criar nova versão com estas alterações" : "Salvar e revalidar"}</Button> : null}
          {decidivel ? (
            <div className="mt-auto grid gap-2 border-t border-regua pt-4">
              {exigemJustificativa ? (
                <p className="text-xs text-perigo">
                  Esta regra tem {exigemJustificativa} divergência(s) com a lei ou a tabela oficial. Corrija-as, ou explique na nota por que a regra está correta assim (mínimo de 15 caracteres).
                </p>
              ) : null}
              <Textarea aria-label="Nota da revisão" placeholder={exigemJustificativa ? "Justificativa obrigatória (ex.: sigo a tabela oficial até manifestação da Receita, pois…)" : "Nota da revisão (opcional)"} value={nota} onChange={(e) => setNota(e.target.value)} />
              {alterouCodigos ? <p className="text-xs text-ocre">Há alterações de códigos não salvas. Salve e revalide antes de aprovar.</p> : null}
              <div className="flex gap-2">
                <Button variant="confirmar" className="flex-1" disabled={decidir.isPending || !!r.erros_validacao?.length || faltaJustificativa || alterouCodigos} onClick={() => decidir.mutate("aprovar")}><Check /> Aprovar regra</Button>
                <Button variant="secundario" disabled={decidir.isPending} onClick={() => decidir.mutate("rejeitar")}><X /> Rejeitar</Button>
              </div>
              <p className="text-2xs text-tinta-3">Ao aprovar, você confirma que a regra estruturada corresponde ao texto legal. A aprovação fica registrada com seu nome.</p>
            </div>
          ) : r.revisado_por_email ? (
            <p className="mt-auto text-xs text-tinta-3">Revisada por {String(r.revisado_por_email)} em {fmtDataHora(String(r.revisado_em))}. {r.nota_revisao ? `Nota: ${String(r.nota_revisao)}` : ""}</p>
          ) : null}
        </Painel>
      </div>
      {q.data.versao_anterior ? (
        <Painel className="mt-6 p-5 text-sm">
          <p className="text-2xs text-tinta-3">Versão anterior (v{String(q.data.versao_anterior.versao)}, {String(q.data.versao_anterior.status)})</p>
          <p className="mt-1">cClassTrib <span className="codigo">{String(q.data.versao_anterior.cclasstrib ?? "—")}</span> · {fmtNum(((q.data.versao_anterior.abrangencia as { codigos?: unknown[] })?.codigos ?? []).length)} códigos · {fmtNum(((q.data.versao_anterior.condicoes as unknown[]) ?? []).length)} condições</p>
        </Painel>
      ) : null}
    </>
  );
}

type ItemCodigo = { codigo: string; formatado: string; descricao: string | null };

/** Lista de códigos agrupada pelo "caminho" na tabela, para não repetir a hierarquia em cada linha. */
function ListaCodigos({ itens, alerta = false, aoRemover }: { itens: ItemCodigo[]; alerta?: boolean; aoRemover?: (codigo: string) => void }) {
  if (!itens.length) return null;
  const grupos: { caminho: string; itens: (ItemCodigo & { folha: string })[] }[] = [];
  for (const it of itens) {
    const partes = (it.descricao ?? "").split(" › ");
    const folha = partes.pop() ?? "";
    const caminho = partes.slice(1).join(" › ");  // sem o capítulo, que se repete em todos
    const ultimo = grupos.at(-1);
    if (ultimo && ultimo.caminho === caminho) ultimo.itens.push({ ...it, folha });
    else grupos.push({ caminho, itens: [{ ...it, folha }] });
  }
  return (
    <div className="mt-1 max-h-72 overflow-y-auto text-xs">
      {grupos.map((g, i) => (
        <div key={i} className="py-1">
          {g.caminho ? <p className="text-2xs leading-snug text-tinta-3">{g.caminho}</p> : null}
          <ul>
            {g.itens.map((c) => (
              <li key={c.codigo} className="flex gap-3 py-0.5 pl-3" title={c.descricao ?? undefined}>
                <span className="codigo flex w-24 shrink-0 items-center gap-1">{alerta ? <AlertTriangle className="size-3 text-ocre" /> : null}{c.formatado}</span>
                <span className={cn("flex-1 text-tinta-2", !c.descricao && "text-tinta-3")}>{c.descricao ? c.folha : "descrição disponível após salvar (ou código inexistente na tabela vigente)"}</span>
                {aoRemover ? <button type="button" className="shrink-0 text-tinta-3 hover:text-perigo" aria-label={`Remover ${c.formatado}`} onClick={() => aoRemover(c.codigo)}><X className="size-3.5" /></button> : null}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

type Divergencia = { codigo: string; mensagem: string; divergencia?: boolean; gravidade?: "alta" | "media" | "info"; codigos?: string[]; total_codigos?: number; acao?: string };

const GRAVIDADE: Record<"alta" | "media" | "info", { rotulo: string; cor: string }> = {
  alta: { rotulo: "Divergência", cor: "bg-perigo/10 text-perigo" },
  media: { rotulo: "Atenção", cor: "bg-ocre/15 text-ocre" },
  info: { rotulo: "Informativo", cor: "bg-superficie-2 text-tinta-3" },
};
const ACAO: Record<string, string> = {
  incluir_na_abrangencia: "Incluir no benefício",
  remover_da_abrangencia: "Retirar do benefício",
  adicionar_excecao: "Adicionar como exceção",
};
const ORDEM_GRAVIDADE = { alta: 0, media: 1, info: 2 };

/** Divergências entre a regra, o texto da lei e a tabela oficial, com correção sugerida por código. */
function PainelDivergencias({ itens, item, editavel, aoAplicar }: { itens: Divergencia[]; item: (c: string) => ItemCodigo; editavel: boolean; aoAplicar: (acao: string, codigos: string[]) => void }) {
  const lista = [...itens].sort((a, b) => ORDEM_GRAVIDADE[a.gravidade ?? "alta"] - ORDEM_GRAVIDADE[b.gravidade ?? "alta"]);
  return (
    <Painel className="mb-4 border-perigo/40 p-4">
      <p className="text-sm font-medium">Divergências encontradas ({itens.length})</p>
      <p className="mb-3 text-xs text-tinta-3">Comparação automática entre o texto da lei, a tabela oficial cClassTrib e esta regra. Nada é corrigido sozinho: você decide.</p>
      <ul className="grid gap-3">
        {lista.map((d, i) => <ItemDivergencia key={`${d.codigo}-${i}`} d={d} item={item} editavel={editavel} aoAplicar={aoAplicar} />)}
      </ul>
    </Painel>
  );
}

function ItemDivergencia({ d, item, editavel, aoAplicar }: { d: Divergencia; item: (c: string) => ItemCodigo; editavel: boolean; aoAplicar: (acao: string, codigos: string[]) => void }) {
  const [aberto, setAberto] = useState(false);
  const [marcados, setMarcados] = useState<string[]>(d.codigos ?? []);
  const [aplicado, setAplicado] = useState(false);
  const g = GRAVIDADE[d.gravidade ?? "alta"];
  const acao = editavel ? d.acao : undefined;
  return (
    <li className="rounded-md border border-regua p-3 text-sm">
      <div className="flex items-start gap-2">
        <span className={cn("shrink-0 rounded px-1.5 py-0.5 text-2xs font-medium", g.cor)}>{g.rotulo}</span>
        <p className="flex-1">{d.mensagem}</p>
      </div>
      {d.codigos?.length ? (
        <div className="mt-2 pl-1">
          <button type="button" className="text-xs text-tinta-3 underline-offset-2 hover:underline" onClick={() => setAberto((v) => !v)}>
            {aberto ? "Ocultar" : "Ver"} {d.codigos.length} código(s){d.total_codigos && d.total_codigos > d.codigos.length ? ` (de ${d.total_codigos})` : ""}
          </button>
          {aberto ? (
            <ul className="mt-2 max-h-64 overflow-y-auto text-xs">
              {d.codigos.map((c) => {
                const it = item(c);
                return (
                  <li key={c} className="flex items-start gap-2 py-0.5" title={it.descricao ?? undefined}>
                    {acao ? <Checkbox aria-label={`Marcar ${it.formatado}`} checked={marcados.includes(c)} onCheckedChange={(v) => setMarcados((m) => (v ? [...m, c] : m.filter((x) => x !== c)))} /> : null}
                    <span className="codigo w-24 shrink-0">{it.formatado}</span>
                    <span className="text-tinta-2">{it.descricao ? it.descricao.split(" › ").slice(-2).join(" › ") : ""}</span>
                  </li>
                );
              })}
            </ul>
          ) : null}
          {acao ? (
            <div className="mt-2 flex items-center gap-2">
              <Button
                tamanho="sm"
                variant="secundario"
                disabled={!marcados.length || aplicado}
                onClick={() => {
                  aoAplicar(acao, marcados);
                  setAplicado(true);
                }}
              >
                {ACAO[acao] ?? acao} ({marcados.length})
              </Button>
              {aplicado ? <span className="text-2xs text-ocre">aplicado; salve para revalidar</span> : null}
            </div>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}

function AdicionarCodigo({ tipo, rotulo, aoAdicionar }: { tipo: string; rotulo: string; aoAdicionar: (codigo: string) => void }) {
  const [valor, setValor] = useState("");
  const digitos = soDigitos(valor);
  const valido = tipo === "nbs" ? /^\d{1,9}$/.test(digitos) : /^\d{2,8}$/.test(digitos);
  return (
    <form
      className="mt-2 flex gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (!valido) return;
        aoAdicionar(digitos);
        setValor("");
      }}
    >
      <Input className="codigo h-8 w-40 text-xs" aria-label={rotulo} placeholder={tipo === "nbs" ? "1.0101.11.00" : "0304.43.00"} value={valor} onChange={(e) => setValor(e.target.value)} />
      <Button tamanho="sm" type="submit" disabled={!valido}><Plus /> {rotulo}</Button>
    </form>
  );
}
