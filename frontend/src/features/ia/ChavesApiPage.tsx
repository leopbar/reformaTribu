import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Bot, CheckCircle2, ExternalLink, KeyRound, PlugZap, Trash2, XCircle } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { api, ok } from "@/api/client";
import type { components } from "@/api/schema";
import { Cabecalho, EstadoErro, mensagemErro } from "@/components/dominio";
import { Aviso, Button, Campo, Input, Painel, Skeleton, Switch } from "@/components/ui/primitives";
import { fmtDataHora } from "@/lib/format";
import { cn } from "@/lib/utils";

type Provedor = components["schemas"]["ProvedorOut"];

/** Cadastro das chaves de API de cada plataforma de IA (superadministrador). */
export function ChavesApiPage() {
  const q = useQuery({ queryKey: ["ia-provedores"], queryFn: () => ok(api.GET("/api/ia/provedores")) });
  return (
    <>
      <Cabecalho
        titulo="Chaves de API"
        subtitulo="Cadastre a chave de cada plataforma de IA. As chaves ficam cifradas no servidor e nunca voltam para a tela: depois de salvas, aparece só o final."
        acoes={
          <Button asChild variant="secundario">
            <Link to="/ia/modelos">
              <Bot /> Modelos de IA
            </Link>
          </Button>
        }
      />
      <Aviso tom="info" className="mb-4" titulo="Dados enviados às plataformas">
        Só a descrição, os códigos e os atributos dos itens vão para a IA (nada de dados pessoais). Cada plataforma tem a própria política de uso de dados; confira-a antes de ativar.
      </Aviso>
      {q.isError ? <EstadoErro erro={q.error} aoTentar={() => void q.refetch()} /> : null}
      {!q.data && !q.isError ? <Skeleton className="h-96" /> : null}
      <div className="grid gap-4 lg:grid-cols-3">
        {q.data?.map((p) => (
          <CartaoProvedor key={p.provedor} p={p} />
        ))}
      </div>
    </>
  );
}

function CartaoProvedor({ p }: { p: Provedor }) {
  const qc = useQueryClient();
  const [chave, setChave] = useState("");
  const [url, setUrl] = useState(p.base_url);
  const atualizar = (dados: Provedor[]) => {
    qc.setQueryData(["ia-provedores"], dados);
    void qc.invalidateQueries({ queryKey: ["ia-agentes"] });
    void qc.invalidateQueries({ queryKey: ["ia-modelos"] });
  };
  const salvar = useMutation({
    mutationFn: (corpo: { chave?: string; remover_chave?: boolean; ativo?: boolean; base_url?: string }) =>
      ok(api.PUT("/api/ia/provedores/{provedor}", { params: { path: { provedor: p.provedor } }, body: { remover_chave: false, ...corpo } })),
    onSuccess: (dados, corpo) => {
      atualizar(dados);
      if (corpo.chave) {
        setChave("");
        toast.success("Chave salva. Testando a conexão…");
        testar.mutate();
      } else toast.success("Alteração salva");
    },
    onError: (e) => toast.error(mensagemErro(e)),
  });
  const testar = useMutation({
    mutationFn: () => ok(api.POST("/api/ia/provedores/{provedor}/testar", { params: { path: { provedor: p.provedor } }, body: {} })),
    onSuccess: (r) => {
      (r.ok ? toast.success : toast.error)(r.mensagem);
      void qc.invalidateQueries({ queryKey: ["ia-provedores"] });
    },
    onError: (e) => toast.error(mensagemErro(e)),
  });
  const pronta = p.ativo && (p.tem_chave || p.chave_no_servidor);
  return (
    <Painel className={cn("flex flex-col gap-4 p-5", !p.ativo && "opacity-75")}>
      <div className="flex items-start gap-3">
        <KeyRound className="mt-0.5 size-5 text-tinta-2" aria-hidden />
        <div className="min-w-0 flex-1">
          <h2 className="text-base font-semibold">{p.nome}</h2>
          <p className="text-2xs text-tinta-3">
            {p.modelos_ativos} modelo(s) ativo(s) ·{" "}
            <a href={p.site} target="_blank" rel="noreferrer" className="inline-flex items-center gap-0.5 underline">
              painel da plataforma <ExternalLink className="size-3" aria-hidden />
            </a>
          </p>
        </div>
        <label className="flex items-center gap-2 text-xs">
          {p.ativo ? "Ativa" : "Desativada"}
          <Switch checked={p.ativo} onCheckedChange={(v) => salvar.mutate({ ativo: v })} aria-label={`Ativar ${p.nome}`} />
        </label>
      </div>

      <div className="rounded-md border border-regua bg-superficie-2 px-3 py-2 text-sm">
        {p.tem_chave ? (
          <p>
            Chave cadastrada: <span className="codigo">••••{p.chave_final}</span>
          </p>
        ) : p.chave_no_servidor ? (
          <p className="text-tinta-2">Usando a chave de reserva do servidor (arquivo .env).</p>
        ) : (
          <p className="text-ocre">Nenhuma chave cadastrada: os modelos desta plataforma não podem ser usados.</p>
        )}
        {p.testado_em ? (
          <p className={cn("mt-1 flex items-start gap-1.5 text-2xs", p.teste_ok ? "text-conferido" : "text-perigo")}>
            {p.teste_ok ? <CheckCircle2 className="mt-px size-3.5 shrink-0" aria-hidden /> : <XCircle className="mt-px size-3.5 shrink-0" aria-hidden />}
            <span>
              {p.teste_mensagem} <span className="text-tinta-3">({fmtDataHora(p.testado_em)})</span>
            </span>
          </p>
        ) : null}
      </div>

      <Campo rotulo={p.tem_chave ? "Trocar a chave" : "Colar a chave"} htmlFor={`k-${p.provedor}`} ajuda="A chave é cifrada antes de ser guardada.">
        <div className="flex gap-2">
          <Input id={`k-${p.provedor}`} type="password" autoComplete="off" value={chave} onChange={(e) => setChave(e.target.value)} placeholder={p.provedor === "anthropic" ? "sk-ant-…" : "sk-…"} />
          <Button variant="primario" disabled={chave.trim().length < 10 || salvar.isPending} onClick={() => salvar.mutate({ chave: chave.trim() })}>
            Salvar
          </Button>
        </div>
      </Campo>

      <div className="flex flex-wrap gap-2">
        <Button variant="secundario" tamanho="sm" onClick={() => testar.mutate()} disabled={testar.isPending || !(p.tem_chave || p.chave_no_servidor)}>
          <PlugZap /> {testar.isPending ? "Testando…" : "Testar conexão"}
        </Button>
        {p.tem_chave ? (
          <Button
            variant="fantasma"
            tamanho="sm"
            onClick={() => {
              if (window.confirm(`Remover a chave da ${p.nome}? Os agentes que usam modelos desta plataforma vão parar de funcionar.`)) salvar.mutate({ remover_chave: true });
            }}
          >
            <Trash2 /> Remover chave
          </Button>
        ) : null}
      </div>

      <details className="text-xs">
        <summary className="cursor-pointer text-tinta-3">Avançado</summary>
        <div className="mt-2 grid gap-2">
          <Campo rotulo="Endereço da API" htmlFor={`u-${p.provedor}`} ajuda={`Padrão: ${p.base_url_padrao}`}>
            <div className="flex gap-2">
              <Input id={`u-${p.provedor}`} value={url} onChange={(e) => setUrl(e.target.value)} />
              <Button variant="secundario" tamanho="sm" disabled={url === p.base_url || salvar.isPending} onClick={() => salvar.mutate({ base_url: url })}>
                Salvar
              </Button>
            </div>
          </Campo>
          <p className="text-tinta-3">Lote: {p.lote}</p>
          {p.atualizado_por ? <p className="text-tinta-3">Última alteração: {p.atualizado_por} · {fmtDataHora(p.updated_at)}</p> : null}
        </div>
      </details>
      <p className={cn("text-2xs font-medium", pronta ? "text-conferido" : "text-tinta-3")}>{pronta ? "Pronta para uso" : "Indisponível para os agentes"}</p>
    </Painel>
  );
}
