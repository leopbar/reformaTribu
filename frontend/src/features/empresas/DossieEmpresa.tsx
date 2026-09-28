import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, ClipboardList } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { api, ok, type Schemas } from "@/api/client";
import { useAuth } from "@/auth/auth";
import { EstadoErro, mensagemErro, ORIGEM_FATO } from "@/components/dominio";
import { Aviso, Button, Painel, Select, Skeleton } from "@/components/ui/primitives";
import { fmtDataHora, plural } from "@/lib/format";
import { cn } from "@/lib/utils";

export function useDossie(companyId: string) {
  return useQuery({
    queryKey: ["dossie", companyId],
    queryFn: () => ok(api.GET("/api/empresas/{company_id}/dossie", { params: { path: { company_id: companyId } } })),
  });
}

/** Dossiê do estabelecimento: o que o analista precisa saber sobre quem vende antes de olhar os itens. */
export function DossieEmpresa({ companyId }: { companyId: string }) {
  const { pode } = useAuth();
  const qc = useQueryClient();
  const q = useDossie(companyId);
  const [segmento, setSegmento] = useState<string | undefined>();
  const [respostas, setRespostas] = useState<Record<string, string>>({});
  const salvar = useMutation({
    mutationFn: () =>
      ok(api.POST("/api/empresas/{company_id}/dossie", { params: { path: { company_id: companyId } }, body: { segmento: segmento ?? null, respostas } })),
    onSuccess: (d) => {
      toast.success(d.completo ? "Dossiê completo. As próximas análises já usam essas informações." : "Dossiê salvo.");
      setRespostas({});
      setSegmento(undefined);
      qc.setQueryData(["dossie", companyId], d);
      void qc.invalidateQueries({ queryKey: ["pendencias"] });
      void qc.invalidateQueries({ queryKey: ["itens"] });
    },
    onError: (e) => toast.error(mensagemErro(e)),
  });
  if (q.isError) return <EstadoErro erro={q.error} aoTentar={() => void q.refetch()} />;
  if (!q.data) return <Skeleton className="h-64" />;
  const d = q.data;
  const editavel = pode("responder");
  const alterado = segmento !== undefined || Object.keys(respostas).length > 0;
  const segAtual = segmento ?? d.segmento ?? undefined;

  return (
    <Painel className="mb-6">
      <div className="flex flex-wrap items-center gap-3 border-b border-regua px-5 py-3">
        <ClipboardList className="size-4 text-tinta-3" aria-hidden />
        <h2 className="text-base">Dossiê do estabelecimento</h2>
        {d.completo ? (
          <span className="inline-flex items-center gap-1 text-xs text-conferido">
            <CheckCircle2 className="size-3.5" aria-hidden /> Completo
          </span>
        ) : (
          <span className="text-xs text-ocre">{plural(d.faltando, "informação faltando", "informações faltando")}</span>
        )}
      </div>
      <div className="grid gap-4 px-5 py-4">
        <p className="max-w-3xl text-sm text-tinta-2">
          Antes de analisar os itens, o analista precisa conhecer quem vende. Estas respostas valem para todos os produtos da
          empresa e ficam registradas com o autor. Assim o analista não precisa perguntar a mesma coisa milhares de vezes.
        </p>
        {d.perguntas_abertas_em_auditorias ? (
          <Aviso tom="atencao" titulo={`${plural(d.perguntas_abertas_em_auditorias, "pergunta sobre a empresa aguarda", "perguntas sobre a empresa aguardam")} resposta nas auditorias`}>
            Elas aparecem abaixo. Ao salvar, os itens afetados são reavaliados na hora.
          </Aviso>
        ) : null}
        <div className="grid gap-1.5 sm:max-w-md">
          <label className="text-sm font-medium" htmlFor="segmento">
            Segmento
          </label>
          <Select id="segmento" aria-label="Segmento" valor={segAtual} aoMudar={setSegmento} opcoes={d.segmentos.map((s) => ({ valor: s.valor!, rotulo: s.rotulo! }))} placeholder="Escolha o segmento" disabled={!editavel} />
          <p className="text-2xs text-tinta-3">Define as perguntas abaixo. Regime: {String(d.cadastro.regime_tributario ?? "").replaceAll("_", " ")} · UF: {String(d.cadastro.uf)}</p>
        </div>
        <ListaPerguntas perguntas={d.perguntas} respostas={respostas} editavel={editavel} aoResponder={(k, v) => setRespostas((r) => ({ ...r, [k]: v }))} />
        {d.perguntas_das_analises.length ? (
          <div>
            <p className="mb-1 text-sm font-medium">Perguntas do analista durante as análises</p>
            <ListaPerguntas perguntas={d.perguntas_das_analises} respostas={respostas} editavel={editavel} aoResponder={(k, v) => setRespostas((r) => ({ ...r, [k]: v }))} />
          </div>
        ) : null}
        {d.outros_fatos.length ? (
          <div>
            <p className="text-sm font-medium">Outros fatos sobre a empresa (respondidos durante as análises)</p>
            <ul className="mt-1 text-xs text-tinta-2">
              {d.outros_fatos.map((f) => (
                <li key={f.id}>
                  {f.atributo.replaceAll("_", " ")} = <span className="font-medium">{f.valor}</span> · {f.origem_rotulo}
                  {f.autor_email ? ` · ${f.autor_email}` : ""} · {fmtDataHora(f.created_at)}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {editavel ? (
          <div className="flex justify-end">
            <Button variant="primario" disabled={!alterado || salvar.isPending} onClick={() => salvar.mutate()}>
              {salvar.isPending ? "Salvando…" : "Salvar dossiê"}
            </Button>
          </div>
        ) : null}
      </div>
    </Painel>
  );
}

type PerguntaDossie = Schemas["PerguntaDossieOut"];

function ListaPerguntas({
  perguntas,
  respostas,
  editavel,
  aoResponder,
}: {
  perguntas: PerguntaDossie[];
  respostas: Record<string, string>;
  editavel: boolean;
  aoResponder: (atributo: string, valor: string) => void;
}) {
  return (
    <ul className="divide-y divide-regua rounded-md border border-regua">
      {perguntas.map((p) => {
        const valor = respostas[p.atributo] ?? p.valor ?? undefined;
        return (
          <li key={p.atributo} className="grid gap-2 px-4 py-3 sm:grid-cols-[1fr_auto] sm:items-center">
            <div>
              <p className="text-sm font-medium">{p.pergunta}</p>
              {p.ajuda ? <p className="text-2xs text-tinta-3">{p.ajuda}</p> : null}
              {p.valor ? (
                <p className="text-2xs text-tinta-3">
                  Resposta atual: <span className="font-medium text-tinta">{p.valor}</span> · {ORIGEM_FATO[p.origem ?? ""] ?? p.origem}
                  {p.autor_email ? ` · ${p.autor_email}` : ""} · {fmtDataHora(p.respondido_em)}
                </p>
              ) : (
                <p className="text-2xs text-ocre">Ainda sem resposta</p>
              )}
            </div>
            <div className="flex gap-1" role="radiogroup" aria-label={p.pergunta}>
              {p.opcoes.map((o) => (
                <button
                  key={o.valor}
                  role="radio"
                  aria-checked={valor === o.valor}
                  disabled={!editavel}
                  onClick={() => aoResponder(p.atributo, o.valor!)}
                  className={cn(
                    "rounded-md border px-3 py-1.5 text-sm",
                    valor === o.valor ? "border-tinta bg-tinta text-papel" : "border-regua hover:border-regua-forte",
                    respostas[p.atributo] && valor === o.valor && "ring-2 ring-caneta/40",
                  )}
                >
                  {o.rotulo}
                </button>
              ))}
            </div>
          </li>
        );
      })}
    </ul>
  );
}
