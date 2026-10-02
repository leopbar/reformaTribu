import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCheck, ListFilter } from "lucide-react";
import { toast } from "sonner";
import { api, ok } from "@/api/client";
import { EstadoErro, EstadoVazio, mensagemErro, SeloStatus } from "@/components/dominio";
import { Button, Painel, Skeleton } from "@/components/ui/primitives";
import { fmtNum, plural } from "@/lib/format";

const IS: Record<string, string> = { sujeito: "sujeito ao IS", na_origem: "IS na origem (não recolhe)", nao_sujeito: "sem IS" };

/** Revisão por grupo (ADR 0029): itens que pedem a mesma decisão aparecem juntos; uma decisão resolve todos.
 * "Ver itens" leva para a fila só com os itens do grupo, para conferir um a um antes, se quiser. */
export function GruposRevisao({ auditId, aoVerItens }: { auditId: string; aoVerItens: (ids: string[]) => void }) {
  const qc = useQueryClient();
  const grupos = useQuery({
    queryKey: ["grupos-revisao", auditId],
    queryFn: () => ok(api.GET("/api/auditorias/{audit_id}/revisao/grupos", { params: { path: { audit_id: auditId } } })),
  });
  const atualizar = () => {
    void qc.invalidateQueries({ queryKey: ["grupos-revisao", auditId] });
    void qc.invalidateQueries({ queryKey: ["itens", auditId] });
    void qc.invalidateQueries({ queryKey: ["auditoria", auditId] });
  };
  const desfazer = useMutation({
    mutationFn: (loteId: string) =>
      ok(api.POST("/api/auditorias/{audit_id}/lotes/{lote_id}/desfazer", { params: { path: { audit_id: auditId, lote_id: loteId } } })),
    onSuccess: (r) => {
      toast.success(r.mensagem);
      atualizar();
    },
    onError: (e) => toast.error(mensagemErro(e)),
  });
  const aprovar = useMutation({
    mutationFn: (ids: string[]) =>
      ok(
        api.POST("/api/auditorias/{audit_id}/aprovar-lote", {
          params: { path: { audit_id: auditId } },
          body: { item_ids: ids, confirmar: true, total_esperado: ids.length, comentario: "Aprovado na revisão por grupo" },
        }),
      ),
    onSuccess: (r) => {
      toast.success(r.mensagem, r.lote_id ? { action: { label: "Desfazer", onClick: () => desfazer.mutate(r.lote_id!) }, duration: 12000 } : undefined);
      atualizar();
    },
    onError: (e) => toast.error(mensagemErro(e)),
  });
  if (grupos.isError) return <EstadoErro erro={grupos.error} aoTentar={() => void grupos.refetch()} />;
  if (!grupos.data) return <Skeleton className="h-64" />;
  if (grupos.data.length === 0)
    return <EstadoVazio titulo="Nenhum grupo pendente" descricao="Não há itens em revisão do contador ou do especialista nesta auditoria." />;
  const total = grupos.data.reduce((n, g) => n + g.itens, 0);
  return (
    <div className="grid gap-3">
      <p className="text-sm text-tinta-2">
        {plural(total, "item pendente", "itens pendentes")} em {plural(grupos.data.length, "decisão", "decisões")}. Cada cartão junta itens com o mesmo código, o
        mesmo resultado sugerido e a mesma dúvida.
      </p>
      {grupos.data.map((g) => (
        <Painel key={g.chave} className="p-4">
          <div className="flex flex-wrap items-start gap-3">
            <div className="min-w-0 flex-1">
              <p className="flex flex-wrap items-center gap-2">
                <SeloStatus status={g.status} />
                <span className="codigo text-sm font-medium">{g.codigo_formatado ?? "sem código"}</span>
                <span className="truncate text-sm text-tinta-2">{g.descricao_oficial}</span>
              </p>
              {g.cclasstrib ? (
                <p className="mt-1 text-xs text-tinta-2">
                  Sugestão: <span className="codigo">cClassTrib {g.cclasstrib}</span> · CST <span className="codigo">{g.cst}</span>
                  {g.imposto_seletivo ? ` · ${IS[g.imposto_seletivo] ?? g.imposto_seletivo}` : ""}
                </p>
              ) : (
                <p className="mt-1 text-xs text-tinta-2">Sem enquadramento sugerido: abra o item para corrigir o código.</p>
              )}
              {g.motivo ? <p className="mt-1 text-xs text-tinta-3">Por que veio para você: {g.motivo}</p> : null}
              <p className="mt-2 text-xs text-tinta-2">
                {g.amostra.join(" · ")}
                {g.itens > g.amostra.length ? <span className="text-tinta-3"> e mais {fmtNum(g.itens - g.amostra.length)}</span> : null}
              </p>
            </div>
            <div className="flex shrink-0 flex-col gap-2">
              {g.cclasstrib ? (
                <Button variant="confirmar" disabled={aprovar.isPending} onClick={() => aprovar.mutate(g.item_ids)}>
                  <CheckCheck /> {g.itens === 1 ? "Aprovar" : `Aprovar os ${fmtNum(g.itens)}`}
                </Button>
              ) : null}
              <Button variant="fantasma" onClick={() => aoVerItens(g.item_ids)}>
                <ListFilter /> Ver itens
              </Button>
            </div>
          </div>
        </Painel>
      ))}
    </div>
  );
}
