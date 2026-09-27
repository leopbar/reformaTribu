import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { api, ok } from "@/api/client";
import { Cabecalho, EstadoErro, mensagemErro } from "@/components/dominio";
import { Aviso, Button, Campo, Dialog, DialogContent, Input, Painel, Select, Skeleton } from "@/components/ui/primitives";
import { fmtDataHora, fmtNum } from "@/lib/format";

const ACOES: Record<string, string> = {
  login: "Entrada no sistema",
  login_falhou: "Tentativa de acesso falhou",
  troca_organizacao: "Troca de organização",
  upload_planilha: "Planilha enviada",
  auditoria_criada: "Auditoria criada",
  auditoria_iniciada: "Auditoria iniciada",
  auditoria_cancelada: "Auditoria cancelada",
  item_reprocessado: "Item reprocessado",
  aprovacao: "Aprovação",
  aprovacao_lote: "Aprovação em lote",
  edicao: "Edição de item",
  rejeicao: "Rejeição",
  desfazer: "Decisão desfeita",
  exportacao: "Exportação",
  configuracao_alterada: "Configuração alterada",
  usuario_alterado: "Usuário alterado",
  empresa_alterada: "Empresa alterada",
  abreviacao_alterada: "Abreviação alterada",
  orcamento: "Orçamento de IA",
  dados_organizacao_exportados: "Dados exportados (LGPD)",
  expurgo_arquivos: "Arquivos expurgados (retenção)",
};

export function AtividadesPage() {
  const [busca, setBusca] = useState("");
  const [acao, setAcao] = useState("_");
  const [pagina, setPagina] = useState(1);
  const q = useQuery({
    queryKey: ["atividades", busca, acao, pagina],
    queryFn: () => ok(api.GET("/api/atividades", { params: { query: { busca: busca || undefined, acao: acao === "_" ? undefined : acao, pagina, por_pagina: 50 } } })),
  });
  const total = q.data?.total ?? 0;
  return (
    <>
      <Cabecalho titulo="Registro de atividades" subtitulo="Log imutável das ações relevantes (encadeado por hash; não pode ser alterado nem apagado)." />
      <div className="mb-4 flex flex-wrap gap-2">
        <Input className="w-72" placeholder="Buscar por usuário ou identificador" value={busca} onChange={(e) => { setBusca(e.target.value); setPagina(1); }} aria-label="Buscar atividades" />
        <Select aria-label="Tipo de ação" className="w-64" valor={acao} aoMudar={(v) => { setAcao(v); setPagina(1); }} opcoes={[{ valor: "_", rotulo: "Todas as ações" }, ...Object.entries(ACOES).map(([k, v]) => ({ valor: k, rotulo: v }))]} />
      </div>
      {q.isError ? <EstadoErro erro={q.error} /> : null}
      {q.isLoading ? <Skeleton className="h-64" /> : null}
      {q.data ? (
        <Painel className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead><tr className="border-b border-regua text-left text-2xs text-tinta-3"><th className="px-5 py-2 font-medium">Quando</th><th className="px-3 py-2 font-medium">Ação</th><th className="px-3 py-2 font-medium">Usuário</th><th className="px-3 py-2 font-medium">Detalhes</th><th className="px-5 py-2 font-medium">IP</th></tr></thead>
            <tbody>
              {q.data.itens.map((a) => (
                <tr key={a.id} className="border-b border-regua align-top last:border-0">
                  <td className="num whitespace-nowrap px-5 py-2 text-tinta-2">{fmtDataHora(a.created_at)}</td>
                  <td className="px-3 py-2">{ACOES[a.acao] ?? a.acao}</td>
                  <td className="px-3 py-2 text-tinta-2">{a.user_email ?? "sistema"}</td>
                  <td className="codigo max-w-md truncate px-3 py-2 text-2xs text-tinta-3" title={JSON.stringify(a.detalhes)}>{a.entidade ? `${a.entidade} ${a.entidade_id ?? ""} ` : ""}{Object.keys(a.detalhes).length ? JSON.stringify(a.detalhes) : ""}</td>
                  <td className="codigo px-5 py-2 text-2xs text-tinta-3">{a.ip ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="flex items-center justify-between border-t border-regua px-5 py-2 text-xs text-tinta-3">
            <span>{fmtNum(total)} registros</span>
            <span className="flex gap-2">
              <Button tamanho="sm" disabled={pagina === 1} onClick={() => setPagina((p) => p - 1)}>Anterior</Button>
              <Button tamanho="sm" disabled={pagina * 50 >= total} onClick={() => setPagina((p) => p + 1)}>Próxima</Button>
            </span>
          </div>
        </Painel>
      ) : null}
    </>
  );
}

export function ContaPage() {
  const [atual, setAtual] = useState("");
  const [nova, setNova] = useState("");
  const [conf, setConf] = useState("");
  const m = useMutation({
    mutationFn: () => ok(api.POST("/api/conta/senha", { body: { senha_atual: atual, nova_senha: nova } })),
    onSuccess: () => {
      toast.success("Senha alterada");
      setAtual(""); setNova(""); setConf("");
    },
    onError: (e) => toast.error(mensagemErro(e)),
  });
  return (
    <>
      <Cabecalho titulo="Minha conta" />
      <Painel className="grid max-w-md gap-4 p-5">
        <h2 className="text-base">Alterar senha</h2>
        <Campo rotulo="Senha atual" htmlFor="sa"><Input id="sa" type="password" autoComplete="current-password" value={atual} onChange={(e) => setAtual(e.target.value)} /></Campo>
        <Campo rotulo="Nova senha" htmlFor="sn" ajuda="Pelo menos 12 caracteres, com três tipos entre minúsculas, maiúsculas, números e símbolos."><Input id="sn" type="password" autoComplete="new-password" value={nova} onChange={(e) => setNova(e.target.value)} /></Campo>
        <Campo rotulo="Confirme a nova senha" htmlFor="sc" erro={conf && conf !== nova ? "As senhas não conferem." : undefined}><Input id="sc" type="password" autoComplete="new-password" value={conf} onChange={(e) => setConf(e.target.value)} /></Campo>
        <Button variant="primario" disabled={!atual || nova.length < 12 || nova !== conf || m.isPending} onClick={() => m.mutate()}>Alterar senha</Button>
      </Painel>
    </>
  );
}

export function PlataformaPage() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["plataforma-orgs"], queryFn: () => ok(api.GET("/api/plataforma/organizacoes")) });
  const [aberto, setAberto] = useState(false);
  const [form, setForm] = useState({ nome: "", tipo: "escritorio_contabil", admin_nome: "", admin_email: "" });
  const [senha, setSenha] = useState<string | null | undefined>(undefined);
  const criar = useMutation({
    mutationFn: () => ok(api.POST("/api/plataforma/organizacoes", { body: { ...form, tipo: form.tipo as "empresa" } })),
    onSuccess: (o) => {
      setSenha(o.senha_temporaria ?? null);
      void qc.invalidateQueries({ queryKey: ["plataforma-orgs"] });
    },
    onError: (e) => toast.error(mensagemErro(e)),
  });
  return (
    <>
      <Cabecalho titulo="Organizações da plataforma" acoes={<Button variant="primario" onClick={() => { setAberto(true); setSenha(undefined); }}>Nova organização</Button>} />
      <Painel>
        <table className="w-full text-sm">
          <thead><tr className="border-b border-regua text-left text-2xs text-tinta-3"><th className="px-5 py-2 font-medium">Nome</th><th className="px-3 py-2 font-medium">Tipo</th><th className="px-5 py-2 font-medium">Criada em</th></tr></thead>
          <tbody>
            {(q.data ?? []).map((o) => (
              <tr key={o.id} className="border-b border-regua last:border-0"><td className="px-5 py-2.5">{o.nome}</td><td className="px-3 py-2.5">{o.tipo === "escritorio_contabil" ? "Escritório contábil" : "Empresa"}</td><td className="px-5 py-2.5">{fmtDataHora(o.created_at)}</td></tr>
            ))}
          </tbody>
        </table>
      </Painel>
      <Dialog open={aberto} onOpenChange={setAberto}>
        <DialogContent titulo="Nova organização" descricao="Cria o tenant e o primeiro administrador.">
          {senha !== undefined ? (
            <Aviso tom="ok" titulo="Organização criada">
              {senha ? <>Senha temporária do administrador (anote agora): <span className="codigo select-all">{senha}</span></> : "O administrador já tinha conta e foi vinculado."}
            </Aviso>
          ) : (
            <div className="grid gap-3">
              <Campo rotulo="Nome" htmlFor="on"><Input id="on" value={form.nome} onChange={(e) => setForm({ ...form, nome: e.target.value })} /></Campo>
              <Campo rotulo="Tipo"><Select aria-label="Tipo" valor={form.tipo} aoMudar={(v) => setForm({ ...form, tipo: v })} opcoes={[{ valor: "escritorio_contabil", rotulo: "Escritório contábil" }, { valor: "empresa", rotulo: "Empresa" }]} /></Campo>
              <Campo rotulo="Nome do administrador" htmlFor="an"><Input id="an" value={form.admin_nome} onChange={(e) => setForm({ ...form, admin_nome: e.target.value })} /></Campo>
              <Campo rotulo="E-mail do administrador" htmlFor="ae"><Input id="ae" type="email" value={form.admin_email} onChange={(e) => setForm({ ...form, admin_email: e.target.value })} /></Campo>
              <Button variant="primario" disabled={!form.nome || !form.admin_email || !form.admin_nome || criar.isPending} onClick={() => criar.mutate()}>Criar</Button>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
