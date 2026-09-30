import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { AlertTriangle, Check, ChevronDown, KeyRound, Plus, Star } from "lucide-react";
import { Select as SelectPrim } from "radix-ui";
import { useState } from "react";
import { toast } from "sonner";
import { api, ok } from "@/api/client";
import type { components } from "@/api/schema";
import { Cabecalho, EstadoErro, mensagemErro } from "@/components/dominio";
import { Aviso, Button, Campo, Dialog, DialogContent, Input, Painel, Select, Skeleton, Switch, Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/primitives";
import { fmtUSD } from "@/lib/format";
import { cn } from "@/lib/utils";

type Agente = components["schemas"]["AgenteOut"];
type Opcao = components["schemas"]["OpcaoModelo"];
type Modelo = components["schemas"]["ModeloIAOut"];

const ESFORCO: Record<string, string> = { low: "Baixo", medium: "Médio", high: "Alto" };

/** Administração de IA: o modelo de cada agente (com ranking recomendado) e o catálogo de modelos. */
export function ModelosPage() {
  return (
    <>
      <Cabecalho
        titulo="Modelos de IA"
        subtitulo="Escolha o modelo de cada agente do sistema. A escolha vale para as próximas auditorias de todas as organizações; as que já começaram mantêm os modelos com que foram iniciadas."
        acoes={
          <Button asChild variant="secundario">
            <Link to="/ia/chaves">
              <KeyRound /> Chaves de API
            </Link>
          </Button>
        }
      />
      <Tabs defaultValue="agentes">
        <TabsList className="mb-4">
          <TabsTrigger value="agentes">Agentes</TabsTrigger>
          <TabsTrigger value="catalogo">Catálogo de modelos</TabsTrigger>
        </TabsList>
        <TabsContent value="agentes">
          <Agentes />
        </TabsContent>
        <TabsContent value="catalogo">
          <Catalogo />
        </TabsContent>
      </Tabs>
    </>
  );
}

// ================================================================================ agentes ==
function Agentes() {
  const q = useQuery({ queryKey: ["ia-agentes"], queryFn: () => ok(api.GET("/api/ia/agentes")) });
  if (q.isError) return <EstadoErro erro={q.error} aoTentar={() => void q.refetch()} />;
  if (!q.data) return <Skeleton className="h-96" />;
  return (
    <div className="grid gap-4">
      <Aviso tom="info" titulo="Como escolher">
        Em cada agente, os primeiros da lista são os <b>recomendados</b>, em ordem de ranking e com o motivo. Abaixo ficam os outros modelos ativos de todas as plataformas. O custo mostrado é o de <b>1.000 chamadas típicas</b> daquele agente. Trocar por um modelo mais barato reduz o custo, mas a qualidade muda — teste numa planilha pequena antes de usar em tudo.
      </Aviso>
      {q.data.map((a) => (
        <CartaoAgente key={a.agente} agente={a} />
      ))}
    </div>
  );
}

function CartaoAgente({ agente }: { agente: Agente }) {
  const qc = useQueryClient();
  const salvar = useMutation({
    mutationFn: (corpo: { modelo: string; esforco: string }) => ok(api.PUT("/api/ia/agentes/{agente}", { params: { path: { agente: agente.agente } }, body: corpo })),
    onSuccess: (dados) => {
      qc.setQueryData(["ia-agentes"], dados);
      void qc.invalidateQueries({ queryKey: ["ia-modelos"] });
      toast.success(`${agente.nome}: modelo atualizado`);
    },
    onError: (e) => toast.error(mensagemErro(e)),
  });
  const todas = [...agente.recomendados, ...agente.outros];
  const atual = todas.find((o) => o.modelo === agente.modelo);
  const suportaEsforco = ["claude-sonnet", "claude-opus", "claude-fable", "gpt-5"].some((p) => agente.modelo.startsWith(p));
  return (
    <Painel className="p-5">
      <div className="flex flex-wrap items-start gap-x-6 gap-y-3">
        <div className="min-w-60 flex-1">
          <h2 className="text-base font-semibold">{agente.nome}</h2>
          <p className="mt-0.5 text-sm text-tinta-2">{agente.funcao}</p>
          <p className="mt-0.5 text-2xs text-tinta-3">O que exige: {agente.exige}</p>
        </div>
        <div className="grid w-full gap-2 sm:w-[26rem]">
          <SeletorModelo agente={agente} disabled={salvar.isPending} aoEscolher={(m) => salvar.mutate({ modelo: m, esforco: agente.esforco })} />
          {atual?.aviso ? (
            <p className="flex items-center gap-1.5 text-2xs text-ocre">
              <AlertTriangle className="size-3.5" aria-hidden /> {atual.aviso}
            </p>
          ) : null}
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-2xs text-tinta-3">
            {atual ? (
              <span>
                {atual.provedor_nome} · US$ {atual.preco_entrada} / {atual.preco_saida} por milhão (entrada / saída) · <b className="text-tinta-2">{fmtUSD(atual.custo_1000_chamadas)}</b> por 1.000 chamadas
              </span>
            ) : null}
            {suportaEsforco ? (
              <label className="ml-auto flex items-center gap-1.5">
                Esforço de raciocínio
                <Select
                  aria-label={`Esforço do ${agente.nome}`}
                  className="h-7 w-24"
                  valor={agente.esforco}
                  aoMudar={(v) => salvar.mutate({ modelo: agente.modelo, esforco: v })}
                  opcoes={agente.esforcos.map((e) => ({ valor: e, rotulo: ESFORCO[e] ?? e }))}
                />
              </label>
            ) : null}
          </div>
        </div>
      </div>
    </Painel>
  );
}

/** Lista suspensa em dois grupos: recomendados (ranking, com motivo) e os demais modelos ativos. */
function SeletorModelo({ agente, aoEscolher, disabled }: { agente: Agente; aoEscolher: (m: string) => void; disabled?: boolean }) {
  const todas = [...agente.recomendados, ...agente.outros];
  const atual = todas.find((o) => o.modelo === agente.modelo);
  return (
    <SelectPrim.Root value={agente.modelo} onValueChange={aoEscolher} disabled={disabled}>
      <SelectPrim.Trigger aria-label={`Modelo do ${agente.nome}`} className="flex h-10 w-full items-center justify-between gap-2 rounded-md border border-regua-forte bg-superficie px-3 text-left text-sm">
        <SelectPrim.Value>
          {atual ? (
            <span className="flex items-center gap-2">
              {atual.posicao ? <span className="num rounded bg-conferido-suave px-1 text-2xs font-semibold text-conferido">{atual.posicao}º</span> : null}
              <span className="font-medium">{atual.nome}</span>
              <span className="text-2xs text-tinta-3">{atual.provedor_nome}</span>
            </span>
          ) : (
            agente.modelo
          )}
        </SelectPrim.Value>
        <SelectPrim.Icon>
          <ChevronDown className="size-4 text-tinta-3" />
        </SelectPrim.Icon>
      </SelectPrim.Trigger>
      <SelectPrim.Portal>
        <SelectPrim.Content position="popper" sideOffset={4} className="z-50 w-[var(--radix-select-trigger-width)] min-w-[22rem] overflow-hidden rounded-md border border-regua bg-superficie shadow-painel">
          <SelectPrim.Viewport className="max-h-[26rem] overflow-y-auto p-1">
            <SelectPrim.Group>
              <SelectPrim.Label className="flex items-center gap-1.5 px-2 py-1.5 text-2xs font-semibold uppercase tracking-wide text-conferido">
                <Star className="size-3" aria-hidden /> Recomendados para este agente
              </SelectPrim.Label>
              {agente.recomendados.map((o) => (
                <ItemModelo key={o.modelo} o={o} />
              ))}
            </SelectPrim.Group>
            {agente.outros.length ? (
              <>
                <SelectPrim.Separator className="my-1 h-px bg-regua" />
                <SelectPrim.Group>
                  <SelectPrim.Label className="px-2 py-1.5 text-2xs font-semibold uppercase tracking-wide text-tinta-3">Outros modelos ativos</SelectPrim.Label>
                  {agente.outros.map((o) => (
                    <ItemModelo key={o.modelo} o={o} />
                  ))}
                </SelectPrim.Group>
              </>
            ) : null}
          </SelectPrim.Viewport>
        </SelectPrim.Content>
      </SelectPrim.Portal>
    </SelectPrim.Root>
  );
}

function ItemModelo({ o }: { o: Opcao }) {
  return (
    <SelectPrim.Item
      value={o.modelo}
      disabled={!o.disponivel}
      className="relative flex cursor-default select-none flex-col rounded-sm py-1.5 pl-7 pr-2 outline-none data-[disabled]:opacity-60 data-[highlighted]:bg-superficie-2"
    >
      <SelectPrim.ItemIndicator className="absolute left-2 top-2">
        <Check className="size-3.5" />
      </SelectPrim.ItemIndicator>
      <span className="flex items-center gap-2 text-sm">
        {o.posicao ? <span className="num rounded bg-conferido-suave px-1 text-2xs font-semibold text-conferido">{o.posicao}º</span> : null}
        <SelectPrim.ItemText>{o.nome}</SelectPrim.ItemText>
        <span className="text-2xs text-tinta-3">{o.provedor_nome}</span>
        <span className="num ml-auto text-2xs text-tinta-2">{fmtUSD(o.custo_1000_chamadas)}/1.000</span>
      </span>
      {o.motivo ? <span className="text-2xs text-tinta-3">{o.motivo}</span> : null}
      {o.aviso ? <span className="text-2xs text-ocre">{o.aviso}</span> : null}
    </SelectPrim.Item>
  );
}

// =============================================================================== catálogo ==
function Catalogo() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["ia-modelos"], queryFn: () => ok(api.GET("/api/ia/modelos")) });
  const [editando, setEditando] = useState<Modelo | null>(null);
  const [novo, setNovo] = useState(false);
  const alternar = useMutation({
    mutationFn: (m: Modelo) => ok(api.PUT("/api/ia/modelos/{modelo}", { params: { path: { modelo: m.modelo } }, body: { ativo: !m.ativo } })),
    onSuccess: (dados) => {
      qc.setQueryData(["ia-modelos"], dados);
      void qc.invalidateQueries({ queryKey: ["ia-agentes"] });
    },
    onError: (e) => toast.error(mensagemErro(e)),
  });
  if (q.isError) return <EstadoErro erro={q.error} aoTentar={() => void q.refetch()} />;
  if (!q.data) return <Skeleton className="h-96" />;
  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <p className="text-sm text-tinta-2">Só os modelos <b>ativos</b> aparecem nas listas dos agentes. Os preços são por milhão de tokens e podem ser ajustados quando a plataforma mudar a tabela.</p>
        <Button variant="secundario" className="ml-auto" onClick={() => setNovo(true)}>
          <Plus /> Cadastrar modelo
        </Button>
      </div>
      <Painel className="overflow-x-auto">
        <table className="w-full min-w-[52rem] text-sm">
          <thead>
            <tr className="border-b border-regua text-left text-2xs text-tinta-3">
              <th className="px-4 py-2 font-medium">Ativo</th>
              <th className="px-3 py-2 font-medium">Modelo</th>
              <th className="px-3 py-2 font-medium">Plataforma</th>
              <th className="px-3 py-2 text-right font-medium">Entrada</th>
              <th className="px-3 py-2 text-right font-medium">Saída</th>
              <th className="px-3 py-2 text-right font-medium">Cache</th>
              <th className="px-3 py-2 font-medium">Recursos</th>
              <th className="px-3 py-2 font-medium">Em uso por</th>
              <th className="px-4 py-2" />
            </tr>
          </thead>
          <tbody>
            {q.data.map((m) => (
              <tr key={m.modelo} className={cn("border-b border-regua last:border-0", !m.ativo && "text-tinta-3")}>
                <td className="px-4 py-2">
                  <Switch checked={m.ativo} onCheckedChange={() => alternar.mutate(m)} aria-label={`Ativar ${m.nome}`} disabled={alternar.isPending} />
                </td>
                <td className="px-3 py-2">
                  <p className="font-medium">{m.nome}</p>
                  <p className="codigo text-2xs text-tinta-3">{m.modelo}</p>
                </td>
                <td className="px-3 py-2">
                  {m.provedor_nome}
                  {!m.plataforma_pronta ? <p className="text-2xs text-ocre">sem chave cadastrada</p> : null}
                </td>
                <td className="num px-3 py-2 text-right">US$ {m.preco_entrada}</td>
                <td className="num px-3 py-2 text-right">US$ {m.preco_saida}</td>
                <td className="num px-3 py-2 text-right">US$ {m.preco_cache_leitura}</td>
                <td className="px-3 py-2 text-2xs text-tinta-2">
                  {[m.suporta_lote ? "lote −50%" : null, m.suporta_esforco ? "esforço" : null].filter(Boolean).join(" · ") || "—"}
                </td>
                <td className="px-3 py-2 text-2xs">{m.em_uso_por.join(", ") || "—"}</td>
                <td className="px-4 py-2 text-right">
                  <Button tamanho="sm" variant="fantasma" onClick={() => setEditando(m)}>
                    Editar
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Painel>
      <Dialog open={!!editando} onOpenChange={(o) => !o && setEditando(null)}>
        {editando ? (
          <DialogContent titulo={`Editar ${editando.nome}`} descricao="Preços em US$ por milhão de tokens.">
            <FormModelo modelo={editando} aoConcluir={() => setEditando(null)} />
          </DialogContent>
        ) : null}
      </Dialog>
      <Dialog open={novo} onOpenChange={setNovo}>
        {novo ? (
          <DialogContent titulo="Cadastrar modelo" descricao="Use o identificador exato da API da plataforma (ex.: gpt-5-mini). Preços em US$ por milhão de tokens.">
            <FormModelo aoConcluir={() => setNovo(false)} />
          </DialogContent>
        ) : null}
      </Dialog>
    </div>
  );
}

function FormModelo({ modelo, aoConcluir }: { modelo?: Modelo; aoConcluir: () => void }) {
  const qc = useQueryClient();
  const [f, setF] = useState({
    modelo: modelo?.modelo ?? "",
    provedor: modelo?.provedor ?? "openai",
    nome: modelo?.nome ?? "",
    preco_entrada: String(modelo?.preco_entrada ?? ""),
    preco_saida: String(modelo?.preco_saida ?? ""),
    preco_cache_leitura: String(modelo?.preco_cache_leitura ?? "0"),
    suporta_esforco: modelo?.suporta_esforco ?? false,
    notas: modelo?.notas ?? "",
  });
  const num = (v: string) => Number(v.replace(",", "."));
  const salvar = useMutation({
    mutationFn: () => {
      const corpo = {
        nome: f.nome,
        preco_entrada: num(f.preco_entrada),
        preco_saida: num(f.preco_saida),
        preco_cache_leitura: num(f.preco_cache_leitura || "0"),
        suporta_esforco: f.suporta_esforco,
        notas: f.notas || null,
      };
      return modelo
        ? ok(api.PUT("/api/ia/modelos/{modelo}", { params: { path: { modelo: modelo.modelo } }, body: corpo }))
        : ok(api.POST("/api/ia/modelos", { body: { ...corpo, modelo: f.modelo.trim(), provedor: f.provedor } }));
    },
    onSuccess: (dados) => {
      qc.setQueryData(["ia-modelos"], dados);
      void qc.invalidateQueries({ queryKey: ["ia-agentes"] });
      toast.success("Modelo salvo");
      aoConcluir();
    },
    onError: (e) => toast.error(mensagemErro(e)),
  });
  const valido = f.nome.trim().length >= 2 && !Number.isNaN(num(f.preco_entrada)) && f.preco_entrada !== "" && f.preco_saida !== "" && (!!modelo || f.modelo.trim().length >= 3);
  return (
    <div className="grid gap-3">
      {!modelo ? (
        <div className="grid gap-3 sm:grid-cols-2">
          <Campo rotulo="Identificador na API" htmlFor="m-id">
            <Input id="m-id" value={f.modelo} onChange={(e) => setF({ ...f, modelo: e.target.value })} placeholder="gpt-5-mini" />
          </Campo>
          <Campo rotulo="Plataforma" htmlFor="m-prov">
            <Select id="m-prov" valor={f.provedor} aoMudar={(v) => setF({ ...f, provedor: v })} opcoes={[{ valor: "anthropic", rotulo: "Anthropic" }, { valor: "openai", rotulo: "OpenAI" }, { valor: "deepseek", rotulo: "DeepSeek" }]} />
          </Campo>
        </div>
      ) : null}
      <Campo rotulo="Nome de exibição" htmlFor="m-nome">
        <Input id="m-nome" value={f.nome} onChange={(e) => setF({ ...f, nome: e.target.value })} />
      </Campo>
      <div className="grid gap-3 sm:grid-cols-3">
        <Campo rotulo="Entrada" htmlFor="m-e">
          <Input id="m-e" inputMode="decimal" value={f.preco_entrada} onChange={(e) => setF({ ...f, preco_entrada: e.target.value })} />
        </Campo>
        <Campo rotulo="Saída" htmlFor="m-s">
          <Input id="m-s" inputMode="decimal" value={f.preco_saida} onChange={(e) => setF({ ...f, preco_saida: e.target.value })} />
        </Campo>
        <Campo rotulo="Leitura de cache" htmlFor="m-c">
          <Input id="m-c" inputMode="decimal" value={f.preco_cache_leitura} onChange={(e) => setF({ ...f, preco_cache_leitura: e.target.value })} />
        </Campo>
      </div>
      <label className="flex items-center gap-2 text-sm">
        <Switch checked={f.suporta_esforco} onCheckedChange={(v) => setF({ ...f, suporta_esforco: v })} /> Aceita o parâmetro de esforço de raciocínio
      </label>
      <Campo rotulo="Notas (opcional)" htmlFor="m-n">
        <Input id="m-n" value={f.notas} onChange={(e) => setF({ ...f, notas: e.target.value })} />
      </Campo>
      <div className="flex justify-end">
        <Button variant="primario" disabled={!valido || salvar.isPending} onClick={() => salvar.mutate()}>
          Salvar
        </Button>
      </div>
    </div>
  );
}
