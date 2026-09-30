import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, ChevronDown, CircleHelp, Lightbulb, Sparkles, Users } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { api, ok, type Schemas } from "@/api/client";
import { useAuth } from "@/auth/auth";
import { EstadoErro, EstadoVazio, mensagemErro } from "@/components/dominio";
import { Aviso, Button, Input, Painel, Skeleton } from "@/components/ui/primitives";
import { fmtDataHora, fmtNum, plural } from "@/lib/format";
import { cn } from "@/lib/utils";
import { usePendencias } from "./comum";

type Pendencia = Schemas["PendenciaOut"];
type Opcao = { valor: string; rotulo?: string; efeito?: string };

export function useResponder(auditId: string, aoConcluir?: () => void) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, valor, respostas_itens, observacao }: { id: string; valor?: string; respostas_itens?: Record<string, string>; observacao?: string }) =>
      ok(api.POST("/api/pendencias/{pendencia_id}/responder", { params: { path: { pendencia_id: id } }, body: { valor: valor ?? null, respostas_itens: respostas_itens ?? {}, observacao: observacao ?? null } })),
    onSuccess: (r) => {
      toast.success(r.mensagem);
      void qc.invalidateQueries({ queryKey: ["pendencias", auditId] });
      void qc.invalidateQueries({ queryKey: ["itens", auditId] });
      void qc.invalidateQueries({ queryKey: ["auditoria", auditId] });
      void qc.invalidateQueries({ queryKey: ["dossie-item"] });
      void qc.invalidateQueries({ queryKey: ["teses", auditId] });
      aoConcluir?.();
    },
    onError: (e) => toast.error(mensagemErro(e)),
  });
}

/** Perguntas decisivas do analista, agrupadas: uma resposta vale para o grupo inteiro. */
export function PerguntasPainel({ auditId }: { auditId: string }) {
  const [verRespondidas, setVerRespondidas] = useState(false);
  const q = usePendencias(auditId, verRespondidas ? "respondida" : "aberta");
  if (q.isError) return <EstadoErro erro={q.error} aoTentar={() => void q.refetch()} />;
  if (!q.data) return <Skeleton className="h-64" />;
  const total = q.data.reduce((s, p) => s + p.total_itens, 0);
  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <p className="max-w-3xl text-sm text-tinta-2">
          O analista só pergunta o que <strong>muda o enquadramento</strong>. Cada pergunta é feita para o grupo mais amplo
          possível (a empresa, uma categoria do ERP ou um NCM). Responda uma vez para todos; se variar, responda item a item.
          Os itens são reclassificados na hora, sem novo custo de IA.
        </p>
        <Button variant="fantasma" tamanho="sm" className="ml-auto" onClick={() => setVerRespondidas((v) => !v)}>
          {verRespondidas ? "Ver perguntas abertas" : "Ver perguntas respondidas"}
        </Button>
      </div>
      {!verRespondidas && q.data.length > 0 ? (
        <Aviso tom="atencao" titulo={`${plural(q.data.length, "pergunta aberta destrava", "perguntas abertas destravam")} ${plural(total, "item", "itens")}`} />
      ) : null}
      {q.data.length === 0 ? (
        <EstadoVazio
          icone={<CheckCircle2 className="size-8 text-conferido" />}
          titulo={verRespondidas ? "Nenhuma pergunta respondida ainda" : "Nenhuma pergunta aberta"}
          descricao={verRespondidas ? undefined : "O analista tem todas as informações de que precisa para os itens desta auditoria."}
        />
      ) : (
        q.data.map((p) => <CartaoPergunta key={p.id} p={p} auditId={auditId} />)
      )}
    </div>
  );
}

const ESCOPO: Record<string, string> = { empresa: "Toda a empresa", grupo: "Grupo de itens", item: "Um item" };

function CartaoPergunta({ p, auditId }: { p: Pendencia; auditId: string }) {
  const { pode } = useAuth();
  const [porItem, setPorItem] = useState(false);
  const [obs, setObs] = useState("");
  const [respostas, setRespostas] = useState<Record<string, string>>({});
  const responder = useResponder(auditId, () => setRespostas({}));
  // A lista traz só uma amostra dos itens; ao abrir, busca todos.
  const completa = useQuery({
    queryKey: ["pendencia", p.id],
    queryFn: () => ok(api.GET("/api/pendencias/{pendencia_id}", { params: { path: { pendencia_id: p.id } } })),
    enabled: porItem,
  });
  const itens = completa.data?.itens ?? p.itens;
  const opcoes = (p.opcoes as Opcao[]) ?? [];
  const aberta = p.status === "aberta";
  const sugestoes = p.itens.filter((i) => i.sugestao);
  const podeResponder = pode("responder") && aberta;
  const faltam = p.total_itens - itens.length;

  return (
    <Painel className="p-5">
      <div className="flex flex-wrap items-center gap-2 text-2xs text-tinta-3">
        <span className="inline-flex items-center gap-1 rounded-full border border-regua bg-superficie-2 px-2 py-0.5 font-medium text-tinta-2">
          <Users className="size-3" aria-hidden /> {p.grupo_rotulo ?? ESCOPO[p.escopo]}
        </span>
        <span>{plural(p.total_itens, "item afetado", "itens afetados")}</span>
        {p.status === "respondida" ? (
          <span className="text-conferido">
            Respondida “{p.resposta}” por {p.respondido_por_email} · {fmtDataHora(p.respondido_em)}
          </span>
        ) : null}
      </div>
      <h3 className="mt-2 flex items-start gap-2 text-base font-semibold">
        <CircleHelp className="mt-0.5 size-5 shrink-0 text-ocre" aria-hidden />
        {p.pergunta}
      </h3>
      {!opcoes.some((o) => o.efeito) && p.motivo ? <p className="mt-2 pl-7 text-xs text-tinta-2">{p.motivo}</p> : null}
      {opcoes.some((o) => o.efeito) ? (
        <ul className="mt-2 grid gap-1 pl-7 text-xs text-tinta-2">
          {opcoes.map((o) => (
            <li key={o.valor}>
              <span className="font-medium text-tinta">Se “{o.rotulo ?? o.valor}”</span> → {o.efeito}
            </li>
          ))}
        </ul>
      ) : null}

      {sugestoes.length ? (
        <p className="mt-3 flex items-start gap-1.5 pl-7 text-xs text-caneta">
          <Lightbulb className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          A IA supõe uma resposta para {plural(sugestoes.length, "item", "itens")}, mas suposição não vira fato: confirme abaixo.
        </p>
      ) : null}

      {podeResponder ? (
        <div className="mt-4 flex flex-wrap items-center gap-2 pl-7">
          {opcoes.map((o) => (
            <Button key={o.valor} variant="secundario" disabled={responder.isPending} onClick={() => responder.mutate({ id: p.id, valor: o.valor, observacao: obs || undefined })}>
              {o.rotulo ?? o.valor}
              {p.total_itens > 1 ? <span className="text-tinta-3">para {p.escopo === "empresa" ? "a empresa" : `os ${fmtNum(p.total_itens)}`}</span> : null}
            </Button>
          ))}
          {p.total_itens > 1 ? (
            <Button variant="fantasma" onClick={() => setPorItem((v) => !v)} aria-expanded={porItem}>
              Varia por item <ChevronDown className={cn("transition-transform", porItem && "rotate-180")} />
            </Button>
          ) : null}
          <Input value={obs} onChange={(e) => setObs(e.target.value)} placeholder="Observação (opcional, fica no histórico)" className="ml-auto max-w-xs" aria-label="Observação" />
        </div>
      ) : null}

      <details className="group mt-4 pl-7" open={porItem}>
        <summary className="cursor-pointer list-none text-xs font-medium text-tinta-2" onClick={(e) => { e.preventDefault(); setPorItem((v) => !v); }}>
          {porItem ? "Ocultar itens" : `Ver os itens (${fmtNum(p.total_itens)})`}
        </summary>
        <ul className="mt-2 divide-y divide-regua rounded-md border border-regua">
          {itens.map((i) => (
            <li key={i.id} className="flex flex-wrap items-center gap-3 px-3 py-2 text-sm">
              <span className="num w-10 text-2xs text-tinta-3">{i.linha}</span>
              <span className="codigo w-20 text-2xs text-tinta-3">{i.codigo_interno}</span>
              <span className="min-w-0 flex-1 truncate">{i.descricao}</span>
              {i.sugestao ? (
                <span className="flex items-center gap-1 text-2xs text-caneta" title={i.sugestao.evidencia}>
                  <Sparkles className="size-3" aria-hidden /> IA supõe “{i.sugestao.valor}”
                </span>
              ) : null}
              {podeResponder && porItem ? (
                <span className="flex gap-1">
                  {opcoes.map((o) => (
                    <Button
                      key={o.valor}
                      tamanho="sm"
                      variant={respostas[i.id] === o.valor ? "primario" : "secundario"}
                      onClick={() => setRespostas((r) => ({ ...r, [i.id]: o.valor }))}
                      aria-pressed={respostas[i.id] === o.valor}
                    >
                      {o.rotulo ?? o.valor}
                    </Button>
                  ))}
                </span>
              ) : null}
            </li>
          ))}
          {faltam > 0 ? <li className="px-3 py-2 text-2xs text-tinta-3">e mais {fmtNum(faltam)} itens (abra a pergunta pelo item para vê-los).</li> : null}
        </ul>
        {podeResponder && porItem ? (
          <div className="mt-2 flex justify-end">
            <Button variant="primario" disabled={!Object.keys(respostas).length || responder.isPending} onClick={() => responder.mutate({ id: p.id, respostas_itens: respostas, observacao: obs || undefined })}>
              Salvar {plural(Object.keys(respostas).length, "resposta", "respostas")}
            </Button>
          </div>
        ) : null}
      </details>
    </Painel>
  );
}
