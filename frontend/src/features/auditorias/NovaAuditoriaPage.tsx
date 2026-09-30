import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import { FileSpreadsheet, UploadCloud, Wand2 } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { api, ok, requisicao, type Schemas } from "@/api/client";
import { Cabecalho, mensagemErro } from "@/components/dominio";
import { Aviso, Button, Campo, Checkbox, Input, Label, Painel, Select } from "@/components/ui/primitives";
import { fmtNum } from "@/lib/format";
import { useDossie } from "@/features/empresas/DossieEmpresa";
import { cn } from "@/lib/utils";

type Upload = Schemas["UploadOut"];

export const PASSOS = ["Enviar planilha", "Mapear colunas", "Revisar prévia", "Confirmar custo e iniciar"] as const;

export function Passos({ atual }: { atual: number }) {
  return (
    <ol className="mb-6 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs" aria-label="Etapas da nova auditoria">
      {PASSOS.map((p, i) => (
        <li key={p} className="flex items-center gap-2" aria-current={i === atual ? "step" : undefined}>
          <span
            className={cn(
              "grid size-5 place-items-center rounded-full border text-2xs num",
              i < atual && "border-conferido bg-conferido text-white",
              i === atual && "border-tinta bg-tinta text-papel",
              i > atual && "border-regua-forte text-tinta-3",
            )}
          >
            {i + 1}
          </span>
          <span className={cn(i === atual ? "font-medium text-tinta" : "text-tinta-3")}>{p}</span>
          {i < PASSOS.length - 1 ? <span className="mx-1 h-px w-6 bg-regua-forte" aria-hidden /> : null}
        </li>
      ))}
    </ol>
  );
}

export function NovaAuditoriaPage() {
  const busca = useSearch({ strict: false }) as { empresa?: string };
  const navegar = useNavigate();
  const [empresa, setEmpresa] = useState<string | undefined>(busca.empresa);
  const [upload, setUpload] = useState<Upload | null>(null);
  const empresas = useQuery({ queryKey: ["empresas"], queryFn: () => ok(api.GET("/api/empresas", { params: { query: {} } })) });

  return (
    <>
      <Cabecalho titulo="Nova auditoria" subtitulo="Nenhuma chamada de IA é feita antes da sua confirmação do custo estimado." />
      <Passos atual={upload ? 1 : 0} />
      {!upload ? (
        <EnvioArquivo
          empresa={empresa}
          setEmpresa={setEmpresa}
          empresas={(empresas.data ?? []).map((e) => ({ valor: e.id, rotulo: e.razao_social }))}
          aoEnviar={setUpload}
        />
      ) : (
        <Mapeamento
          upload={upload}
          setUpload={setUpload}
          empresa={empresa!}
          aoCriar={(id) => void navegar({ to: "/auditorias/$id", params: { id } })}
          voltar={() => setUpload(null)}
        />
      )}
    </>
  );
}

function EnvioArquivo({
  empresa,
  setEmpresa,
  empresas,
  aoEnviar,
}: {
  empresa?: string;
  setEmpresa: (v: string) => void;
  empresas: { valor: string; rotulo: string }[];
  aoEnviar: (u: Upload) => void;
}) {
  const entrada = useRef<HTMLInputElement>(null);
  const [arrastando, setArrastando] = useState(false);
  const enviar = useMutation({
    mutationFn: async (arquivo: File) => {
      const fd = new FormData();
      fd.append("arquivo", arquivo);
      fd.append("company_id", empresa!);
      const r = await requisicao("/api/uploads", { method: "POST", body: fd });
      return (await r.json()) as Upload;
    },
    onSuccess: aoEnviar,
    onError: (e) => toast.error(mensagemErro(e)),
  });
  const escolher = (f: File | undefined) => {
    if (!f) return;
    if (!empresa) {
      toast.error("Escolha a empresa antes de enviar a planilha.");
      return;
    }
    enviar.mutate(f);
  };
  return (
    <div className="grid max-w-3xl gap-6">
      <Campo rotulo="Empresa auditada">
        <Select aria-label="Empresa auditada" valor={empresa} aoMudar={setEmpresa} opcoes={empresas} placeholder="Escolha a empresa" />
      </Campo>
      {empresa ? <AvisoDossie empresa={empresa} /> : null}
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setArrastando(true);
        }}
        onDragLeave={() => setArrastando(false)}
        onDrop={(e) => {
          e.preventDefault();
          setArrastando(false);
          escolher(e.dataTransfer.files[0]);
        }}
        className={cn(
          "flex flex-col items-center justify-center gap-3 rounded-lg border-2 border-dashed px-6 py-14 text-center transition-colors",
          arrastando ? "border-caneta bg-caneta-suave" : "border-regua-forte bg-superficie",
        )}
      >
        <UploadCloud className="size-9 text-tinta-3" aria-hidden />
        <p className="text-base font-medium">{enviar.isPending ? "Lendo a planilha…" : "Arraste a planilha aqui"}</p>
        <p className="text-sm text-tinta-3">XLSX, XLS ou CSV, até 100 mil linhas. Planilhas com macros são recusadas.</p>
        <input ref={entrada} type="file" accept=".xlsx,.xls,.csv,text/csv" className="sr-only" onChange={(e) => escolher(e.target.files?.[0])} />
        <Button variant="primario" onClick={() => entrada.current?.click()} disabled={enviar.isPending || !empresa}>
          <FileSpreadsheet /> Escolher arquivo
        </Button>
        {!empresa ? <p className="text-2xs text-tinta-3">Escolha a empresa primeiro.</p> : null}
      </div>
    </div>
  );
}

function Mapeamento({
  upload,
  setUpload,
  empresa,
  aoCriar,
  voltar,
}: {
  upload: Upload;
  setUpload: (u: Upload) => void;
  empresa: string;
  aoCriar: (id: string) => void;
  voltar: () => void;
}) {
  const [mapa, setMapa] = useState<Record<string, string | null>>(upload.mapeamento_sugerido);
  const [nome, setNome] = useState(() => `${upload.nome.replace(/\.[^.]+$/, "")} — ${new Date().toLocaleDateString("pt-BR")}`);
  // A classificação vale para uma data: por padrão, o início da cobrança da CBS (1º/1/2027).
  const [dataRef, setDataRef] = useState(() => (new Date() < new Date("2027-01-01") ? "2027-01-01" : new Date().toISOString().slice(0, 10)));
  const [salvarModelo, setSalvarModelo] = useState(false);
  const [sistema, setSistema] = useState("");
  const usadas = useMemo(() => new Set(Object.values(mapa).filter(Boolean)), [mapa]);
  const opcoesColunas = [{ valor: "__nenhuma__", rotulo: "— não usar —" }, ...upload.colunas.map((c) => ({ valor: c, rotulo: c }))];

  const reler = useMutation({
    mutationFn: (corpo: { planilha?: string; linha_cabecalho?: number }) =>
      ok(api.POST("/api/uploads/{arquivo_id}/reler", { params: { path: { arquivo_id: upload.arquivo_id } }, body: corpo })),
    onSuccess: (u) => {
      setUpload(u);
      setMapa(u.mapeamento_sugerido);
    },
    onError: (e) => toast.error(mensagemErro(e)),
  });
  const criar = useMutation({
    mutationFn: () =>
      ok(
        api.POST("/api/auditorias", {
          body: {
            company_id: empresa,
            arquivo_id: upload.arquivo_id,
            nome,
            mapeamento: mapa,
            data_referencia: dataRef,
            contexto_operacao: {},
            salvar_modelo: salvarModelo,
            nome_modelo: salvarModelo ? `Modelo ${sistema || upload.nome}` : null,
            sistema_origem: sistema || null,
          },
        }),
      ),
    onSuccess: (a) => {
      toast.success("Auditoria criada. Lendo e validando a planilha…");
      aoCriar(a.id);
    },
    onError: (e) => toast.error(mensagemErro(e)),
  });

  const colunasMapeadas = upload.campos.filter((c) => mapa[c.chave]);
  const faltaDescricao = !mapa.descricao;

  return (
    <div className="grid gap-6 xl:grid-cols-[26rem_1fr]">
      <Painel className="h-fit p-5">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-base">Colunas da planilha</h2>
          <span className="text-2xs text-tinta-3">
            <Wand2 className="mr-1 inline size-3.5" aria-hidden />
            detectadas automaticamente
          </span>
        </div>
        {upload.modelos.filter((m) => m.compativel).length ? (
          <div className="mb-4">
            <Label>Usar modelo salvo</Label>
            <Select
              aria-label="Modelo de mapeamento"
              valor={undefined}
              aoMudar={(id) => {
                const m = upload.modelos.find((x) => x.id === id);
                if (m) setMapa(m.mapeamento as Record<string, string | null>);
              }}
              opcoes={upload.modelos.filter((m) => m.compativel).map((m) => ({ valor: m.id, rotulo: m.nome }))}
              placeholder="Escolha um modelo"
              className="mt-1.5"
            />
          </div>
        ) : null}
        <div className="grid gap-3">
          {upload.campos.map((c) => (
            <div key={c.chave} className="grid grid-cols-[10rem_1fr] items-center gap-3">
              <Label htmlFor={`m-${c.chave}`} className="text-tinta">
                {c.rotulo}
                {c.obrigatorio && c.chave === "descricao" ? <span className="text-perigo"> *</span> : null}
              </Label>
              <Select
                id={`m-${c.chave}`}
                aria-label={c.rotulo}
                valor={mapa[c.chave] ?? "__nenhuma__"}
                aoMudar={(v) => setMapa((m) => ({ ...m, [c.chave]: v === "__nenhuma__" ? null : v }))}
                opcoes={opcoesColunas.map((o) => ({
                  ...o,
                  rotulo: usadas.has(o.valor) && mapa[c.chave] !== o.valor ? `${o.rotulo} (em uso)` : o.rotulo,
                }))}
              />
            </div>
          ))}
        </div>
        {!mapa.codigo_interno ? (
          <p className="mt-3 text-2xs text-tinta-3">Sem coluna de código interno: o sistema gera um código a partir da linha.</p>
        ) : null}
      </Painel>

      <div className="grid min-w-0 gap-6">
        <Painel className="p-5">
          <div className="mb-3 flex flex-wrap items-center gap-3 text-xs text-tinta-3">
            <span className="font-medium text-tinta">{upload.nome}</span>
            <span>{upload.formato.toUpperCase()}</span>
            {upload.encoding ? <span>codificação {upload.encoding}</span> : null}
            {upload.separador ? <span>separador “{upload.separador}”</span> : null}
            <span className="num">{fmtNum(upload.total_linhas)} linhas</span>
            {upload.planilhas.length > 1 ? (
              <span className="flex items-center gap-2">
                aba
                <Select aria-label="Aba da planilha" valor={upload.planilha ?? undefined} aoMudar={(v) => reler.mutate({ planilha: v })} opcoes={upload.planilhas.map((p) => ({ valor: p, rotulo: p }))} className="h-7 w-40" />
              </span>
            ) : null}
            <span className="flex items-center gap-2">
              cabeçalho na linha
              <Input
                type="number"
                min={1}
                max={50}
                className="h-7 w-16"
                defaultValue={upload.linha_cabecalho + 1}
                onBlur={(e) => {
                  const n = Number(e.target.value) - 1;
                  if (n >= 0 && n !== upload.linha_cabecalho) reler.mutate({ linha_cabecalho: n });
                }}
                aria-label="Linha do cabeçalho"
              />
            </span>
          </div>
          <div className="overflow-x-auto rounded-md border border-regua">
            <table className="w-full text-xs">
              <thead>
                <tr className="bg-superficie-2 text-left">
                  {colunasMapeadas.map((c) => (
                    <th key={c.chave} className="whitespace-nowrap px-3 py-2 font-medium">
                      {c.rotulo}
                      <span className="block font-normal text-tinta-3">{mapa[c.chave]}</span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {upload.amostra.slice(0, 8).map((linha, i) => (
                  <tr key={i} className="border-t border-regua">
                    {colunasMapeadas.map((c) => {
                      const idx = upload.colunas.indexOf(mapa[c.chave] ?? "");
                      return (
                        <td key={c.chave} className={cn("max-w-72 truncate px-3 py-1.5", ["ncm", "nbs", "gtin", "cest"].includes(c.chave) && "codigo")}>
                          {idx >= 0 ? linha[idx] : ""}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Painel>

        <Painel className="grid gap-4 p-5 sm:grid-cols-2">
          <Campo rotulo="Nome da auditoria" htmlFor="nome">
            <Input id="nome" value={nome} onChange={(e) => setNome(e.target.value)} />
          </Campo>
          <Campo rotulo="Vigência da classificação" htmlFor="dref" ajuda="A classificação vale para esta data: define as tabelas, a lei e a fase da transição aplicadas (2027 é o início da CBS).">
            <Input id="dref" type="date" value={dataRef} onChange={(e) => setDataRef(e.target.value)} />
          </Campo>
          <label className="flex items-center gap-2 text-sm sm:col-span-2">
            <Checkbox checked={salvarModelo} onCheckedChange={(v) => setSalvarModelo(v === true)} />
            Salvar este mapeamento como modelo para as próximas planilhas desta empresa
          </label>
          {salvarModelo ? (
            <Campo rotulo="Sistema de origem (opcional)" htmlFor="sis" className="sm:col-span-2">
              <Input id="sis" placeholder="Ex.: ERP da loja" value={sistema} onChange={(e) => setSistema(e.target.value)} />
            </Campo>
          ) : null}
        </Painel>

        {faltaDescricao ? <Aviso tom="atencao">Indique a coluna com a descrição do item para continuar.</Aviso> : null}
        <div className="flex justify-between">
          <Button variant="fantasma" onClick={voltar}>
            Enviar outro arquivo
          </Button>
          <Button variant="primario" disabled={faltaDescricao || criar.isPending || nome.trim().length < 2} onClick={() => criar.mutate()}>
            {criar.isPending ? "Criando…" : "Validar planilha e ver prévia"}
          </Button>
        </div>
      </div>
    </div>
  );
}

/** O analista precisa conhecer quem vende antes de olhar os itens. */
function AvisoDossie({ empresa }: { empresa: string }) {
  const q = useDossie(empresa);
  if (!q.data || q.data.completo) return null;
  return (
    <Aviso tom="atencao" titulo="O dossiê desta empresa está incompleto">
      Sem ele, o analista vai perguntar durante a análise (por exemplo, se a loja produz alimentos). Leva um minuto:{" "}
      <Link to="/empresas/$id" params={{ id: empresa }} className="underline">
        preencher o dossiê
      </Link>
      .
    </Aviso>
  );
}
