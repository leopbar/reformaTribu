import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "@tanstack/react-router";
import { ArrowLeft, Building2, Plus, Upload } from "lucide-react";
import { useState } from "react";
import { Controller, useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { api, ok } from "@/api/client";
import { useAuth } from "@/auth/auth";
import { Cabecalho, EstadoErro, EstadoVazio, mensagemErro } from "@/components/dominio";
import { Button, Campo, Dialog, DialogContent, DialogTrigger, Input, Painel, Select, Skeleton } from "@/components/ui/primitives";
import { fmtCnpj, fmtDataHora, fmtNum, fmtUSD } from "@/lib/format";
import { ROTULO_STATUS_AUDITORIA } from "@/features/auditorias/comum";
import { DossieEmpresa } from "./DossieEmpresa";

const REGIMES = [
  { valor: "mei", rotulo: "MEI" },
  { valor: "simples_nacional", rotulo: "Simples Nacional" },
  { valor: "lucro_presumido", rotulo: "Lucro Presumido" },
  { valor: "lucro_real", rotulo: "Lucro Real" },
];
const UFS = "AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split(" ");

/** Validação do CNPJ (inclusive alfanumérico, IN RFB 2.229/2024). */
export function cnpjValido(v: string): boolean {
  const c = v.replace(/[^0-9A-Za-z]/g, "").toUpperCase();
  if (!/^[0-9A-Z]{12}\d{2}$/.test(c) || /^(\d)\1{13}$/.test(c)) return false;
  const dv = (base: string, pesos: number[]) => {
    const soma = [...base].reduce((s, ch, i) => s + (ch.charCodeAt(0) - 48) * pesos[i]!, 0);
    const r = soma % 11;
    return r < 2 ? 0 : 11 - r;
  };
  const d1 = dv(c.slice(0, 12), [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]);
  const d2 = dv(c.slice(0, 12) + d1, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]);
  return c.slice(12) === `${d1}${d2}`;
}

const esquema = z.object({
  razao_social: z.string().trim().min(2, "Informe a razão social."),
  nome_fantasia: z.string().trim().optional(),
  cnpj: z.string().refine(cnpjValido, "CNPJ inválido. Confira os dígitos (o CNPJ alfanumérico também é aceito)."),
  regime_tributario: z.enum(["mei", "simples_nacional", "lucro_presumido", "lucro_real"], { message: "Escolha o regime." }),
  uf: z.string().length(2, "Escolha a UF."),
  atividade_principal: z.string().trim().optional(),
  cnae: z.string().trim().optional(),
});
type Dados = z.infer<typeof esquema>;

export function EmpresasPage() {
  const { pode } = useAuth();
  const q = useQuery({ queryKey: ["empresas"], queryFn: () => ok(api.GET("/api/empresas", { params: { query: {} } })) });
  return (
    <>
      <Cabecalho
        titulo="Empresas auditadas"
        subtitulo="Cada empresa tem o próprio dossiê (quem vende e como vende), as auditorias, os fatos já confirmados e a memória de classificações aprovadas."
        acoes={pode("gerenciar_empresas") ? <NovaEmpresa /> : null}
      />
      {q.isError ? <EstadoErro erro={q.error} aoTentar={() => void q.refetch()} /> : null}
      {q.isLoading ? <Skeleton className="h-48" /> : null}
      {q.data && q.data.length === 0 ? (
        <EstadoVazio icone={<Building2 className="size-8" />} titulo="Nenhuma empresa ainda" descricao="Cadastre a primeira empresa para começar a auditar os cadastros dela." acao={pode("gerenciar_empresas") ? <NovaEmpresa /> : null} />
      ) : null}
      {q.data && q.data.length > 0 ? (
        <Painel className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-regua text-left text-2xs text-tinta-3">
                <th className="px-5 py-2 font-medium">Razão social</th>
                <th className="px-3 py-2 font-medium">CNPJ</th>
                <th className="px-3 py-2 font-medium">Regime</th>
                <th className="px-3 py-2 font-medium">UF</th>
              </tr>
            </thead>
            <tbody>
              {q.data.map((e) => (
                <tr key={e.id} className="border-b border-regua last:border-0 hover:bg-superficie-2">
                  <td className="px-5 py-3">
                    <Link to="/empresas/$id" params={{ id: e.id }} className="font-medium hover:underline">
                      {e.razao_social}
                    </Link>
                  </td>
                  <td className="codigo px-3 py-3 text-xs">{fmtCnpj(e.cnpj)}</td>
                  <td className="px-3 py-3">{REGIMES.find((r) => r.valor === e.regime_tributario)?.rotulo}</td>
                  <td className="px-3 py-3">{e.uf}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Painel>
      ) : null}
    </>
  );
}

function NovaEmpresa() {
  const [aberto, setAberto] = useState(false);
  const qc = useQueryClient();
  const f = useForm<Dados>({ resolver: zodResolver(esquema), defaultValues: { uf: "SP" } });
  const criar = useMutation({
    mutationFn: (d: Dados) => ok(api.POST("/api/empresas", { body: { ...d, atributos: {} } })),
    onSuccess: (e) => {
      toast.success(`Empresa cadastrada: ${e.razao_social}`);
      void qc.invalidateQueries({ queryKey: ["empresas"] });
      void qc.invalidateQueries({ queryKey: ["painel"] });
      setAberto(false);
      f.reset();
    },
    onError: (e) => toast.error(mensagemErro(e)),
  });
  const erro = f.formState.errors;
  return (
    <Dialog open={aberto} onOpenChange={setAberto}>
      <DialogTrigger asChild>
        <Button variant="primario">
          <Plus /> Cadastrar empresa
        </Button>
      </DialogTrigger>
      <DialogContent titulo="Cadastrar empresa" descricao="Os dados são usados nas condições legais que dependem de quem vende (ex.: regime tributário).">
        <form onSubmit={f.handleSubmit((d) => criar.mutate(d))} className="grid gap-4" noValidate>
          <Campo rotulo="Razão social" htmlFor="rs" erro={erro.razao_social?.message}>
            <Input id="rs" aria-invalid={!!erro.razao_social} {...f.register("razao_social")} />
          </Campo>
          <div className="grid gap-4 sm:grid-cols-2">
            <Campo rotulo="CNPJ" htmlFor="cnpj" erro={erro.cnpj?.message}>
              <Input id="cnpj" className="codigo" placeholder="00.000.000/0000-00" aria-invalid={!!erro.cnpj} {...f.register("cnpj")} />
            </Campo>
            <Campo rotulo="Nome fantasia (opcional)" htmlFor="nf">
              <Input id="nf" {...f.register("nome_fantasia")} />
            </Campo>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <Campo rotulo="Regime tributário" erro={erro.regime_tributario?.message}>
              <Controller control={f.control} name="regime_tributario" render={({ field }) => <Select aria-label="Regime tributário" valor={field.value} aoMudar={field.onChange} opcoes={REGIMES} placeholder="Escolha" />} />
            </Campo>
            <Campo rotulo="UF" erro={erro.uf?.message}>
              <Controller control={f.control} name="uf" render={({ field }) => <Select aria-label="UF" valor={field.value} aoMudar={field.onChange} opcoes={UFS.map((u) => ({ valor: u, rotulo: u }))} />} />
            </Campo>
          </div>
          <Campo rotulo="Atividade principal (opcional)" htmlFor="at">
            <Input id="at" {...f.register("atividade_principal")} />
          </Campo>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="fantasma" onClick={() => setAberto(false)}>
              Cancelar
            </Button>
            <Button type="submit" variant="primario" disabled={criar.isPending}>
              {criar.isPending ? "Salvando…" : "Cadastrar empresa"}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function EmpresaDetalhePage() {
  const { id } = useParams({ strict: false }) as { id: string };
  const { pode } = useAuth();
  const emp = useQuery({ queryKey: ["empresa", id], queryFn: () => ok(api.GET("/api/empresas/{company_id}", { params: { path: { company_id: id } } })) });
  const auds = useQuery({ queryKey: ["auditorias", id], queryFn: () => ok(api.GET("/api/auditorias", { params: { query: { company_id: id } } })) });
  if (emp.isError) return <EstadoErro erro={emp.error} />;
  if (!emp.data) return <Skeleton className="h-64" />;
  const e = emp.data;
  return (
    <>
      <Cabecalho
        voltar={
          <Link to="/empresas" className="inline-flex items-center gap-1 text-xs text-tinta-3 hover:text-tinta">
            <ArrowLeft className="size-3.5" /> Empresas
          </Link>
        }
        titulo={e.razao_social}
        subtitulo={
          <span className="codigo">
            {fmtCnpj(e.cnpj)} · {REGIMES.find((r) => r.valor === e.regime_tributario)?.rotulo} · {e.uf}
          </span>
        }
        acoes={
          pode("criar_auditoria") ? (
            <Button asChild variant="primario">
              <Link to="/auditorias/nova" search={{ empresa: e.id }}>
                <Upload /> Nova auditoria
              </Link>
            </Button>
          ) : null
        }
      />
      <DossieEmpresa companyId={e.id} />
      <Painel>
        <h2 className="border-b border-regua px-5 py-3 text-base">Auditorias</h2>
        {auds.data?.length === 0 ? (
          <p className="px-5 py-8 text-center text-sm text-tinta-3">Nenhuma auditoria desta empresa ainda. Envie a planilha de produtos e serviços para começar.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-regua text-left text-2xs text-tinta-3">
                <th className="px-5 py-2 font-medium">Auditoria</th>
                <th className="px-3 py-2 font-medium">Situação</th>
                <th className="px-3 py-2 text-right font-medium">Itens</th>
                <th className="px-3 py-2 text-right font-medium">Para revisar</th>
                <th className="px-5 py-2 text-right font-medium">Custo de IA</th>
              </tr>
            </thead>
            <tbody>
              {(auds.data ?? []).map((a) => (
                <tr key={a.id} className="border-b border-regua last:border-0 hover:bg-superficie-2">
                  <td className="px-5 py-3">
                    <Link to="/auditorias/$id" params={{ id: a.id }} className="font-medium hover:underline">
                      {a.nome}
                    </Link>
                    <span className="block text-2xs text-tinta-3">{fmtDataHora(a.created_at)}</span>
                  </td>
                  <td className="px-3 py-3">{ROTULO_STATUS_AUDITORIA[a.status] ?? a.status}</td>
                  <td className="num px-3 py-3 text-right">{fmtNum(a.total_itens)}</td>
                  <td className="num px-3 py-3 text-right">{fmtNum(a.pendentes_revisao)}</td>
                  <td className="num px-5 py-3 text-right">{fmtUSD(a.custo_usd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Painel>
    </>
  );
}
