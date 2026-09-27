import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, UserPlus } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { api, ok, type Schemas } from "@/api/client";
import { useAuth } from "@/auth/auth";
import { Cabecalho, EstadoErro, mensagemErro } from "@/components/dominio";
import { Aviso, Button, Campo, Checkbox, Dialog, DialogContent, Input, Painel, Select, Skeleton, Switch, Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/primitives";
import { fmtDataHora, fmtUSD } from "@/lib/format";

export function ConfiguracoesPage() {
  const { pode } = useAuth();
  return (
    <>
      <Cabecalho titulo="Configurações" />
      <Tabs defaultValue={pode("gerenciar_configuracoes") ? "geral" : "abreviacoes"}>
        <TabsList className="mb-6">
          {pode("gerenciar_configuracoes") ? <TabsTrigger value="geral">Análise e orçamento</TabsTrigger> : null}
          {pode("gerenciar_usuarios") ? <TabsTrigger value="usuarios">Usuários e papéis</TabsTrigger> : null}
          <TabsTrigger value="abreviacoes">Dicionário de abreviações</TabsTrigger>
          {pode("gerenciar_configuracoes") ? <TabsTrigger value="dados">Dados da organização</TabsTrigger> : null}
        </TabsList>
        <TabsContent value="geral"><Geral /></TabsContent>
        <TabsContent value="usuarios"><Usuarios /></TabsContent>
        <TabsContent value="abreviacoes"><Abreviacoes /></TabsContent>
        <TabsContent value="dados"><Dados /></TabsContent>
      </Tabs>
    </>
  );
}

function Geral() {
  const q = useQuery({ queryKey: ["organizacao"], queryFn: () => ok(api.GET("/api/organizacao")) });
  if (q.isError) return <EstadoErro erro={q.error} />;
  if (!q.data) return <Skeleton className="h-64" />;
  return <FormGeral key={q.dataUpdatedAt} inicial={q.data.configuracoes} gastoMes={q.data.gasto_mes_usd} />;
}

function FormGeral({ inicial, gastoMes }: { inicial: Schemas["ConfiguracoesOut"]; gastoMes: number }) {
  const qc = useQueryClient();
  const [c, setC] = useState<Schemas["ConfiguracoesOut"]>(inicial);
  const salvar = useMutation({
    mutationFn: () => {
      const corpo: Partial<Schemas["ConfiguracoesOut"]> = { ...c };
      delete corpo.modelos_disponiveis;
      return ok(api.PATCH("/api/organizacao/configuracoes", { body: corpo }));
    },
    onSuccess: () => {
      toast.success("Configurações salvas");
      void qc.invalidateQueries({ queryKey: ["organizacao"] });
    },
    onError: (e) => toast.error(mensagemErro(e)),
  });
  const modelos = c.modelos_disponiveis.map((m) => ({ valor: m, rotulo: m }));
  const num = (k: keyof Schemas["ConfiguracoesOut"]) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setC({ ...c, [k]: e.target.value === "" ? null : Number(e.target.value) });
  return (
    <div className="grid max-w-3xl gap-6">
      <Painel className="grid gap-4 p-5 sm:grid-cols-3">
        <h2 className="text-base sm:col-span-3">Limites de confiança</h2>
        <p className="-mt-2 text-xs text-tinta-3 sm:col-span-3">Limites mais altos mandam mais itens para análise humana e reduzem o risco de “falsos confirmados”.</p>
        <Campo rotulo="Confirmado a partir de" htmlFor="lc"><Input id="lc" type="number" step="0.01" min="0.5" max="1" value={c.limiar_confirmado} onChange={num("limiar_confirmado")} /></Campo>
        <Campo rotulo="Corrigido a partir de" htmlFor="lk"><Input id="lk" type="number" step="0.01" min="0.5" max="1" value={c.limiar_corrigido} onChange={num("limiar_corrigido")} /></Campo>
        <Campo rotulo="Escalonar abaixo de" htmlFor="le"><Input id="le" type="number" step="0.01" min="0" max="1" value={c.limiar_escalonamento} onChange={num("limiar_escalonamento")} /></Campo>
      </Painel>
      <Painel className="grid gap-4 p-5 sm:grid-cols-2">
        <h2 className="text-base sm:col-span-2">Modelos de IA</h2>
        <Campo rotulo="Julgamento principal"><Select aria-label="Modelo principal" valor={c.modelo_principal ?? "_"} aoMudar={(v) => setC({ ...c, modelo_principal: v === "_" ? null : v })} opcoes={[{ valor: "_", rotulo: "Padrão do servidor" }, ...modelos]} /></Campo>
        <Campo rotulo="Segundo parecer (escalonamento)"><Select aria-label="Modelo de escalonamento" valor={c.modelo_escalonamento ?? "_"} aoMudar={(v) => setC({ ...c, modelo_escalonamento: v === "_" ? null : v })} opcoes={[{ valor: "_", rotulo: "Padrão do servidor" }, ...modelos]} /></Campo>
        <Campo rotulo="Modelo leve (abreviações difíceis)"><Select aria-label="Modelo leve" valor={c.modelo_leve ?? "_"} aoMudar={(v) => setC({ ...c, modelo_leve: v === "_" ? null : v })} opcoes={[{ valor: "_", rotulo: "Padrão do servidor" }, ...modelos]} /></Campo>
        <label className="flex items-center gap-3 self-end text-sm"><Switch checked={c.usar_modelo_leve} onCheckedChange={(v) => setC({ ...c, usar_modelo_leve: v })} /> Usar modelo leve para expandir abreviações</label>
        <Campo rotulo="Usar lote (Batch API) a partir de N itens" htmlFor="lote" ajuda="Lotes custam 50% menos e levam até 24 h."><Input id="lote" type="number" min={1} value={c.lote_min_itens ?? ""} placeholder="padrão do servidor" onChange={num("lote_min_itens")} /></Campo>
      </Painel>
      <Painel className="grid gap-4 p-5 sm:grid-cols-2">
        <h2 className="text-base sm:col-span-2">Orçamento e regras de análise</h2>
        <Campo rotulo="Orçamento mensal de IA (US$)" htmlFor="orc" ajuda={`Gasto neste mês: ${fmtUSD(gastoMes)}`}><Input id="orc" type="number" min={0} step="1" value={c.orcamento_mensal_usd ?? ""} onChange={num("orcamento_mensal_usd")} /></Campo>
        <Campo rotulo="Alertar ao atingir (%)" htmlFor="al"><Input id="al" type="number" min={10} max={100} value={c.alerta_orcamento_pct} onChange={num("alerta_orcamento_pct")} /></Campo>
        <label className="flex items-center gap-3 text-sm sm:col-span-2"><Switch checked={c.imposto_seletivo_exige_analise} onCheckedChange={(v) => setC({ ...c, imposto_seletivo_exige_analise: v })} /> Itens sujeitos ao Imposto Seletivo sempre vão para análise humana</label>
        <Campo rotulo="Apagar planilhas originais após (dias)" htmlFor="ret" ajuda="0 = manter. Os itens auditados continuam disponíveis."><Input id="ret" type="number" min={0} value={c.retencao_arquivos_dias} onChange={num("retencao_arquivos_dias")} /></Campo>
      </Painel>
      <div className="flex justify-end">
        <Button variant="primario" onClick={() => salvar.mutate()} disabled={salvar.isPending}>Salvar configurações</Button>
      </div>
    </div>
  );
}

const PAPEIS = [
  { valor: "administrador", rotulo: "Administrador" },
  { valor: "revisor", rotulo: "Revisor" },
  { valor: "operador", rotulo: "Operador" },
  { valor: "leitura", rotulo: "Leitura" },
];

function Usuarios() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["usuarios"], queryFn: () => ok(api.GET("/api/usuarios")) });
  const empresas = useQuery({ queryKey: ["empresas"], queryFn: () => ok(api.GET("/api/empresas", { params: { query: {} } })) });
  const [novo, setNovo] = useState(false);
  const [senha, setSenha] = useState<string | null>(null);
  const [form, setForm] = useState({ nome: "", email: "", papel: "revisor", empresas: [] as string[] });
  const criar = useMutation({
    mutationFn: () => ok(api.POST("/api/usuarios", { body: { nome: form.nome, email: form.email, papel: form.papel as "revisor", empresas_liberadas: form.empresas } })),
    onSuccess: (u) => {
      void qc.invalidateQueries({ queryKey: ["usuarios"] });
      setSenha(u.senha_temporaria ?? null);
      toast.success(u.senha_temporaria ? "Usuário criado" : "Usuário existente adicionado à organização");
    },
    onError: (e) => toast.error(mensagemErro(e)),
  });
  const alterar = useMutation({
    mutationFn: (v: { id: string; corpo: Schemas["UsuarioPatch"] }) => ok(api.PATCH("/api/usuarios/{membership_id}", { params: { path: { membership_id: v.id } }, body: v.corpo })),
    onSuccess: () => {
      toast.success("Usuário atualizado");
      void qc.invalidateQueries({ queryKey: ["usuarios"] });
    },
    onError: (e) => toast.error(mensagemErro(e)),
  });
  return (
    <Painel>
      <div className="flex items-center justify-between border-b border-regua px-5 py-3">
        <h2 className="text-base">Usuários</h2>
        <Button variant="primario" tamanho="sm" onClick={() => { setNovo(true); setSenha(null); setForm({ nome: "", email: "", papel: "revisor", empresas: [] }); }}><UserPlus /> Adicionar usuário</Button>
      </div>
      <table className="w-full text-sm">
        <thead><tr className="border-b border-regua text-left text-2xs text-tinta-3"><th className="px-5 py-2 font-medium">Nome</th><th className="px-3 py-2 font-medium">Papel</th><th className="px-3 py-2 font-medium">Último acesso</th><th className="px-5 py-2 font-medium">Ativo</th></tr></thead>
        <tbody>
          {(q.data ?? []).map((u) => (
            <tr key={u.membership_id} className="border-b border-regua last:border-0">
              <td className="px-5 py-2.5">{u.nome}<span className="block text-2xs text-tinta-3">{u.email}</span></td>
              <td className="px-3 py-2.5 w-44"><Select aria-label={`Papel de ${u.nome}`} valor={u.papel} aoMudar={(v) => alterar.mutate({ id: u.membership_id, corpo: { papel: v as "revisor" } })} opcoes={PAPEIS} /></td>
              <td className="px-3 py-2.5 text-tinta-2">{fmtDataHora(u.ultimo_login_em)}</td>
              <td className="px-5 py-2.5"><Switch aria-label={`Ativo: ${u.nome}`} checked={u.ativo} onCheckedChange={(v) => alterar.mutate({ id: u.membership_id, corpo: { ativo: v } })} /></td>
            </tr>
          ))}
        </tbody>
      </table>
      <Dialog open={novo} onOpenChange={setNovo}>
        <DialogContent titulo="Adicionar usuário" descricao="Se o e-mail já tiver conta, a pessoa é apenas vinculada a esta organização.">
          {senha ? (
            <Aviso tom="ok" titulo="Senha temporária (anote agora; ela não será exibida de novo)">
              <p className="codigo mt-1 select-all text-base">{senha}</p>
              <p className="mt-1 text-xs">Entregue por um canal seguro. A pessoa pode trocá-la em “Minha conta”.</p>
            </Aviso>
          ) : (
            <div className="grid gap-3">
              <Campo rotulo="Nome" htmlFor="un"><Input id="un" value={form.nome} onChange={(e) => setForm({ ...form, nome: e.target.value })} /></Campo>
              <Campo rotulo="E-mail" htmlFor="ue"><Input id="ue" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></Campo>
              <Campo rotulo="Papel"><Select aria-label="Papel" valor={form.papel} aoMudar={(v) => setForm({ ...form, papel: v })} opcoes={PAPEIS} /></Campo>
              {form.papel === "leitura" ? (
                <fieldset className="grid gap-1.5">
                  <legend className="mb-1 text-xs font-medium text-tinta-2">Empresas liberadas para consulta</legend>
                  {(empresas.data ?? []).map((e) => (
                    <label key={e.id} className="flex items-center gap-2 text-sm">
                      <Checkbox checked={form.empresas.includes(e.id)} onCheckedChange={(v) => setForm({ ...form, empresas: v ? [...form.empresas, e.id] : form.empresas.filter((x) => x !== e.id) })} />
                      {e.razao_social}
                    </label>
                  ))}
                </fieldset>
              ) : null}
              <Button variant="primario" disabled={!form.nome || !form.email || criar.isPending} onClick={() => criar.mutate()}>Adicionar</Button>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </Painel>
  );
}

function Abreviacoes() {
  const qc = useQueryClient();
  const { sessao, pode } = useAuth();
  const [busca, setBusca] = useState("");
  const q = useQuery({ queryKey: ["abreviacoes", busca], queryFn: () => ok(api.GET("/api/abreviacoes", { params: { query: { busca: busca || undefined } } })) });
  const [ab, setAb] = useState({ abreviacao: "", expansao: "", global: false });
  const criar = useMutation({
    mutationFn: () => ok(api.POST("/api/abreviacoes", { body: ab })),
    onSuccess: () => {
      toast.success("Abreviação adicionada");
      setAb({ abreviacao: "", expansao: "", global: false });
      void qc.invalidateQueries({ queryKey: ["abreviacoes"] });
    },
    onError: (e) => toast.error(mensagemErro(e)),
  });
  const alterar = useMutation({
    mutationFn: (v: { id: string; ativo: boolean }) => ok(api.PATCH("/api/abreviacoes/{abrev_id}", { params: { path: { abrev_id: v.id } }, body: { ativo: v.ativo } })),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["abreviacoes"] }),
    onError: (e) => toast.error(mensagemErro(e)),
  });
  const editavel = pode("gerenciar_abreviacoes");
  return (
    <div className="grid max-w-3xl gap-4">
      <p className="text-sm text-tinta-3">Usado para expandir descrições do varejo antes da busca (ex.: “SAB LIQ” → “sabonete líquido”). As da organização substituem as globais.</p>
      {editavel ? (
        <Painel className="flex flex-wrap items-end gap-3 p-4">
          <Campo rotulo="Abreviação" htmlFor="ab" className="w-36"><Input id="ab" value={ab.abreviacao} onChange={(e) => setAb({ ...ab, abreviacao: e.target.value.trim() })} /></Campo>
          <Campo rotulo="Expansão" htmlFor="ex" className="flex-1"><Input id="ex" value={ab.expansao} onChange={(e) => setAb({ ...ab, expansao: e.target.value })} /></Campo>
          {sessao?.superadmin ? <label className="flex items-center gap-2 pb-2 text-sm"><Checkbox checked={ab.global} onCheckedChange={(v) => setAb({ ...ab, global: v === true })} /> Global</label> : null}
          <Button variant="primario" disabled={!ab.abreviacao || !ab.expansao || criar.isPending} onClick={() => criar.mutate()}><Plus /> Adicionar</Button>
        </Painel>
      ) : null}
      <Input value={busca} onChange={(e) => setBusca(e.target.value)} placeholder="Buscar" aria-label="Buscar abreviação" className="w-64" />
      <Painel>
        <table className="w-full text-sm">
          <thead><tr className="border-b border-regua text-left text-2xs text-tinta-3"><th className="px-5 py-2 font-medium">Abreviação</th><th className="px-3 py-2 font-medium">Expansão</th><th className="px-3 py-2 font-medium">Escopo</th><th className="px-5 py-2 font-medium">Ativa</th></tr></thead>
          <tbody>
            {(q.data ?? []).map((a) => (
              <tr key={a.id} className="border-b border-regua last:border-0">
                <td className="codigo px-5 py-2">{a.abreviacao}</td>
                <td className="px-3 py-2">{a.expansao}</td>
                <td className="px-3 py-2 text-tinta-3">{a.global ? "Global" : "Organização"}</td>
                <td className="px-5 py-2"><Switch aria-label={`Ativa: ${a.abreviacao}`} disabled={!editavel || (a.global && !sessao?.superadmin)} checked={a.ativo} onCheckedChange={(v) => alterar.mutate({ id: a.id, ativo: v })} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Painel>
    </div>
  );
}

function Dados() {
  const exportar = useMutation({
    mutationFn: () => ok(api.POST("/api/organizacao/exportar-dados")),
    onSuccess: () => toast.success("Pacote de dados em preparação. Ele aparece nas exportações da auditoria mais recente."),
    onError: (e) => toast.error(mensagemErro(e)),
  });
  return (
    <div className="grid max-w-3xl gap-4">
      <Painel className="p-5">
        <h2 className="text-base">Exportar todos os dados da organização</h2>
        <p className="mt-1 text-sm text-tinta-3">Gera um pacote (JSON compactado) com empresas, auditorias, itens, decisões, memória aprovada, chamadas de IA e log de auditoria (LGPD, portabilidade).</p>
        <Button className="mt-4" onClick={() => exportar.mutate()} disabled={exportar.isPending}>Gerar pacote de dados</Button>
      </Painel>
      <Aviso tom="info" titulo="Exclusão definitiva">
        A exclusão de todos os dados da organização é feita pelo superadministrador da plataforma, mediante solicitação formal do administrador.
      </Aviso>
    </div>
  );
}
