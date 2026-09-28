import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BadgeCheck, BookOpenText, Scale } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { api, ok } from "@/api/client";
import { useAuth } from "@/auth/auth";
import { EstadoErro, EstadoVazio, mensagemErro, STATUS } from "@/components/dominio";
import { Aviso, Button, Dialog, DialogContent, Painel, Skeleton } from "@/components/ui/primitives";
import { fmtData, fmtDataHora, fmtNum } from "@/lib/format";
import { cn } from "@/lib/utils";
import { TRATAMENTO } from "./comum";


const IS: Record<string, string> = { sujeito: "Sujeito ao IS", nao_sujeito: "Sem IS", depende: "IS depende do item" };

/** Famílias investigadas: o raciocínio jurídico feito uma vez por código e reaproveitado pelos itens. */
export function FamiliasPainel({ auditId }: { auditId: string }) {
  const q = useQuery({
    queryKey: ["teses", auditId],
    queryFn: () => ok(api.GET("/api/auditorias/{audit_id}/teses", { params: { path: { audit_id: auditId } } })),
  });
  const [aberta, setAberta] = useState<string | null>(null);
  if (q.isError) return <EstadoErro erro={q.error} aoTentar={() => void q.refetch()} />;
  if (!q.data) return <Skeleton className="h-64" />;
  if (q.data.length === 0)
    return <EstadoVazio icone={<Scale className="size-8" />} titulo="Nenhuma família investigada ainda" descricao="As famílias aparecem à medida que o analista investiga cada código." />;
  return (
    <div className="grid gap-3">
      <p className="max-w-3xl text-sm text-tinta-2">
        Para cada código (NCM/NBS), o analista investiga a lei <strong>uma vez</strong>: levanta as hipóteses de enquadramento,
        as condições de cada uma e os trechos que as fundamentam. Depois aplica esse raciocínio aos fatos de cada item.
        Um revisor pode validar a tese: ela passa a contar como precedente aprovado.
      </p>
      <Painel className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-regua text-left text-2xs text-tinta-3">
              <th className="px-5 py-2 font-medium">Família</th>
              <th className="px-3 py-2 font-medium">Hipóteses (em ordem de precedência)</th>
              <th className="px-3 py-2 text-right font-medium">Itens</th>
              <th className="px-3 py-2 font-medium">Situação</th>
              <th className="px-5 py-2" />
            </tr>
          </thead>
          <tbody>
            {q.data.map((t) => (
              <tr key={t.id} className="border-b border-regua align-top last:border-0">
                <td className="px-5 py-3">
                  <span className="codigo text-sm font-medium">{t.codigo_formatado}</span>
                  <span className="block max-w-sm text-xs text-tinta-3">{(t.descricao ?? "").split(" › ").slice(-2).join(" › ")}</span>
                </td>
                <td className="px-3 py-3">
                  <ol className="flex flex-wrap gap-1">
                    {t.hipoteses.map((h) => (
                      <li key={String(h.id)} className="rounded border border-regua bg-superficie-2 px-1.5 py-0.5 text-2xs" title={String(h.titulo)}>
                        <span className="codigo">{String(h.cclasstrib)}</span> · {TRATAMENTO[String(h.tipo)] ?? String(h.tipo)}
                      </li>
                    ))}
                  </ol>
                  {t.imposto_seletivo && t.imposto_seletivo !== "nao_sujeito" ? <span className="mt-1 block text-2xs text-ocre">{IS[t.imposto_seletivo]}</span> : null}
                </td>
                <td className="num px-3 py-3 text-right">{fmtNum(t.itens)}</td>
                <td className="px-3 py-3 text-2xs">
                  {Object.entries(t.por_status).map(([s, n]) => (
                    <span key={s} className={cn("mr-2 whitespace-nowrap", STATUS[s as keyof typeof STATUS]?.cor)}>
                      {STATUS[s as keyof typeof STATUS]?.rotulo ?? s}: <span className="num">{fmtNum(n)}</span>
                    </span>
                  ))}
                  {t.aprovada_em ? (
                    <span className="mt-1 flex items-center gap-1 text-conferido">
                      <BadgeCheck className="size-3.5" aria-hidden /> Validada por {t.aprovada_por_email}
                    </span>
                  ) : null}
                </td>
                <td className="px-5 py-3 text-right">
                  <Button variant="fantasma" tamanho="sm" onClick={() => setAberta(t.id)}>
                    <BookOpenText /> Ver raciocínio
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Painel>
      <Dialog open={!!aberta} onOpenChange={(o) => !o && setAberta(null)}>
        {aberta ? (
          <DialogContent lateral titulo="Raciocínio da família" className="max-w-3xl">
            <DetalheTese id={aberta} auditId={auditId} />
          </DialogContent>
        ) : null}
      </Dialog>
    </div>
  );
}

type Ref = { ref: string; trecho?: string };

export function DetalheTese({ id, auditId }: { id: string; auditId?: string }) {
  const { pode } = useAuth();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["tese", id], queryFn: () => ok(api.GET("/api/teses/{tese_id}", { params: { path: { tese_id: id } } })) });
  const aprovar = useMutation({
    mutationFn: () => ok(api.POST("/api/teses/{tese_id}/aprovar", { params: { path: { tese_id: id } }, body: {} })),
    onSuccess: () => {
      toast.success("Tese validada. Os itens da família foram reavaliados.");
      void qc.invalidateQueries({ queryKey: ["tese", id] });
      if (auditId) {
        void qc.invalidateQueries({ queryKey: ["teses", auditId] });
        void qc.invalidateQueries({ queryKey: ["itens", auditId] });
      }
    },
    onError: (e) => toast.error(mensagemErro(e)),
  });
  if (q.isError) return <EstadoErro erro={q.error} />;
  if (!q.data) return <Skeleton className="h-96" />;
  const t = q.data;
  const r = t.resultado as {
    entendimento?: string;
    hipoteses?: { id: string; titulo: string; tipo: string; cclasstrib: string; explicacao: string; condicoes: { fato: string; valor_exigido: string; explicacao: string }[]; excecoes: { descricao: string; fato: string; valor_que_exclui: string }[]; fundamentos: Ref[] }[];
    fatos_necessarios?: { fato: string; escopo: string; pergunta: string }[];
    imposto_seletivo?: { situacao: string; explicacao: string; fundamentos: Ref[] };
    conflitos?: { descricao: string }[];
    observacoes?: string;
  };
  const ev = t.evidencias as { trechos_normativos?: { ref: string; norma: string; local: string; texto: string; titulo?: string }[]; correlacoes_oficiais?: { ref: string; cclasstrib: string; descricao_item_anexo?: string; condicao?: string; excecao?: string }[]; cclasstrib_candidatos?: { ref: string; codigo: string; nome: string; cst: string }[] };
  const porRef = new Map<string, string>();
  for (const p of ev.trechos_normativos ?? []) porRef.set(p.ref, `${p.norma} — ${p.local}`);
  for (const c of ev.correlacoes_oficiais ?? []) porRef.set(c.ref, `Correlação oficial cClassTrib ${c.cclasstrib}`);
  for (const c of ev.cclasstrib_candidatos ?? []) porRef.set(c.ref, `Tabela cClassTrib ${c.codigo} (CST ${c.cst})`);
  const validacao = t.validacao as { hipoteses_descartadas?: { cclasstrib: string; motivo: string }[]; referencias_invalidas?: { hipotese: string; refs: string[] }[] };

  return (
    <div className="grid gap-5 text-sm">
      <div>
        <p className="codigo text-base font-semibold">{t.codigo_formatado}</p>
        <p className="text-xs text-tinta-3">{t.descricao}</p>
        <p className="mt-2">{r.entendimento}</p>
        <p className="mt-1 text-2xs text-tinta-3">
          Vigência {fmtData(t.data_referencia)} · {t.transicao.periodo} · modelo {t.modelo} · {fmtDataHora(t.created_at)}
        </p>
        <p className="mt-1 text-2xs text-tinta-3">
          Dossiê considerado: {Object.entries(t.fatos_empresa).map(([k, v]) => `${k.replaceAll("_", " ")} = ${String(v)}`).join("; ") || "—"}
        </p>
      </div>
      <section>
        <h3 className="mb-2 font-semibold">Hipóteses, da mais específica à regra geral</h3>
        <ol className="grid gap-3">
          {(r.hipoteses ?? []).map((h, n) => (
            <li key={h.id} className="rounded-md border border-regua p-3">
              <p className="font-medium">
                {n + 1}. {h.titulo} <span className="codigo text-xs text-tinta-3">cClassTrib {h.cclasstrib}</span>
              </p>
              {h.explicacao ? <p className="mt-1 text-xs text-tinta-2">{h.explicacao}</p> : null}
              {h.condicoes.length ? (
                <p className="mt-2 text-xs">
                  <span className="font-medium">Vale se:</span> {h.condicoes.map((c) => `${c.fato.replaceAll("_", " ")} = ${c.valor_exigido}`).join(" e ")}
                </p>
              ) : (
                <p className="mt-2 text-xs text-tinta-3">Sem condições além do próprio código.</p>
              )}
              {h.excecoes.length ? (
                <p className="mt-1 text-xs">
                  <span className="font-medium">Exceto:</span> {h.excecoes.map((e) => e.descricao).join("; ")}
                </p>
              ) : null}
              <ul className="mt-2 grid gap-1">
                {h.fundamentos.map((f) => (
                  <li key={f.ref} className={cn("border-l-2 pl-2 text-2xs", porRef.has(f.ref) ? "border-regua-forte text-tinta-2" : "border-perigo text-perigo")}>
                    <span className="font-medium">{porRef.get(f.ref) ?? `${f.ref} (referência inexistente — desconsiderada)`}</span>
                    {f.trecho ? <> — “{f.trecho}”</> : null}
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ol>
      </section>
      {r.fatos_necessarios?.length ? (
        <section>
          <h3 className="mb-1 font-semibold">Fatos que decidem entre as hipóteses</h3>
          <ul className="list-disc pl-5 text-xs text-tinta-2">
            {r.fatos_necessarios.map((f) => (
              <li key={f.fato}>
                {f.pergunta} <span className="text-tinta-3">({f.escopo === "empresa" ? "sobre a empresa" : "por item"})</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {r.imposto_seletivo ? (
        <section>
          <h3 className="mb-1 font-semibold">Imposto Seletivo</h3>
          <p className="text-xs">{IS[r.imposto_seletivo.situacao] ?? r.imposto_seletivo.situacao}. {r.imposto_seletivo.explicacao}</p>
        </section>
      ) : null}
      {r.conflitos?.length ? (
        <Aviso tom="atencao" titulo="Conflitos e limites apontados pelo analista">
          <ul className="list-disc pl-5 text-xs">
            {r.conflitos.map((c, i) => (
              <li key={i}>{c.descricao}</li>
            ))}
          </ul>
        </Aviso>
      ) : null}
      {validacao.hipoteses_descartadas?.length ? (
        <Aviso tom="info" titulo="Descartado pela validação automática">
          {validacao.hipoteses_descartadas.map((d) => `${d.cclasstrib}: ${d.motivo}`).join("; ")}
        </Aviso>
      ) : null}
      {r.observacoes ? <p className="text-xs text-tinta-3">{r.observacoes}</p> : null}
      <details className="rounded-md border border-regua">
        <summary className="cursor-pointer px-3 py-2 font-medium">Material consultado ({(ev.trechos_normativos ?? []).length} trechos, {(ev.correlacoes_oficiais ?? []).length} correlações)</summary>
        <ul className="grid gap-2 border-t border-regua p-3 text-xs">
          {(ev.trechos_normativos ?? []).map((p) => (
            <li key={p.ref}>
              <span className="font-medium">
                {p.ref} · {p.norma} — {p.local}
              </span>
              <p className="whitespace-pre-line text-tinta-2">{p.texto}</p>
            </li>
          ))}
          {(ev.correlacoes_oficiais ?? []).map((c) => (
            <li key={c.ref}>
              <span className="font-medium">
                {c.ref} · correlação cClassTrib {c.cclasstrib}
              </span>{" "}
              <span className="text-tinta-2">
                {c.descricao_item_anexo} {c.condicao ? `· condição: ${c.condicao}` : ""} {c.excecao ? `· exceção: ${c.excecao}` : ""}
              </span>
            </li>
          ))}
        </ul>
      </details>
      <div className="sticky bottom-0 -mx-6 flex items-center gap-2 border-t border-regua bg-superficie px-6 py-3">
        {t.aprovada_em ? (
          <span className="flex items-center gap-1 text-sm text-conferido">
            <BadgeCheck className="size-4" /> Validada por {t.aprovada_por_email} em {fmtDataHora(t.aprovada_em)}
          </span>
        ) : pode("revisar") ? (
          <Button variant="confirmar" onClick={() => aprovar.mutate()} disabled={aprovar.isPending}>
            <BadgeCheck /> Validar este raciocínio
          </Button>
        ) : null}
        <span className="ml-auto text-2xs text-tinta-3">{fmtNum(t.itens)} itens usam esta tese</span>
      </div>
    </div>
  );
}
