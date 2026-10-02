import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCheck, Undo2 } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { api, ok } from "@/api/client";
import { EstadoErro, EstadoVazio, mensagemErro } from "@/components/dominio";
import { Aviso, Button, Checkbox, Painel, Select, Skeleton } from "@/components/ui/primitives";
import { fmtNum } from "@/lib/format";

const SITUACAO: Record<string, string> = { pendente: "A confirmar", aceito: "Sugestão aceita", mantido: "NCM do ERP mantido" };

/** NCM/NBS a confirmar no cadastro quando a dúvida não muda o imposto (ADR 0029). O IBS/CBS do item já saiu;
 * aqui a pessoa só decide qual código vai para o cadastro e a nota fiscal, em lote. */
export function AjustesCadastroPainel({ auditId }: { auditId: string }) {
  const qc = useQueryClient();
  const [filtro, setFiltro] = useState("pendente");
  const [sel, setSel] = useState<Set<string>>(new Set());
  const lista = useQuery({
    queryKey: ["ajustes-cadastro", auditId, filtro],
    queryFn: () =>
      ok(api.GET("/api/auditorias/{audit_id}/ajustes-cadastro", { params: { path: { audit_id: auditId }, query: { status: filtro } } })),
  });
  const decidir = useMutation({
    mutationFn: (corpo: { item_ids: string[]; acao: "aceitar" | "manter" | "reabrir" }) =>
      ok(api.POST("/api/auditorias/{audit_id}/ajustes-cadastro", { params: { path: { audit_id: auditId } }, body: corpo })),
    onSuccess: (r, corpo) => {
      toast.success(
        r.mensagem,
        corpo.acao !== "reabrir" ? { action: { label: "Desfazer", onClick: () => decidir.mutate({ item_ids: corpo.item_ids, acao: "reabrir" }) }, duration: 10000 } : undefined,
      );
      setSel(new Set());
      void qc.invalidateQueries({ queryKey: ["ajustes-cadastro", auditId] });
      void qc.invalidateQueries({ queryKey: ["auditoria", auditId] });
      void qc.invalidateQueries({ queryKey: ["itens", auditId] });
    },
    onError: (e) => toast.error(mensagemErro(e)),
  });
  const linhas = useMemo(() => lista.data ?? [], [lista.data]);
  if (lista.isError) return <EstadoErro erro={lista.error} aoTentar={() => void lista.refetch()} />;
  if (!lista.data) return <Skeleton className="h-64" />;
  const todos = linhas.length > 0 && linhas.every((l) => sel.has(l.item_id));
  const alternar = (id: string) =>
    setSel((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  const alvo = sel.size ? [...sel] : linhas.filter((l) => l.status === "pendente").map((l) => l.item_id);
  return (
    <div className="grid gap-4">
      <Aviso tom="info" titulo="O imposto destes itens já está definido">
        Em todos eles, o código do ERP e o sugerido levam ao mesmo IBS/CBS. Falta só decidir qual código fica no cadastro e na nota
        fiscal. Enquanto a sugestão não é aceita, a exportação mantém o NCM do ERP. A decisão vira memória da empresa.
      </Aviso>
      <Painel>
        <div className="flex flex-wrap items-center gap-2 border-b border-regua px-5 py-3">
          <h2 className="mr-auto text-base">Ajustes de cadastro</h2>
          <Select
            aria-label="Situação"
            className="w-48"
            valor={filtro}
            aoMudar={(v) => {
              setFiltro(v);
              setSel(new Set());
            }}
            opcoes={[
              { valor: "pendente", rotulo: "A confirmar" },
              { valor: "todos", rotulo: "Todos" },
            ]}
          />
          <Button variant="secundario" disabled={!alvo.length || decidir.isPending} onClick={() => decidir.mutate({ item_ids: alvo, acao: "manter" })}>
            <Undo2 /> Manter NCM do ERP {sel.size ? `(${fmtNum(sel.size)})` : ""}
          </Button>
          <Button variant="confirmar" disabled={!alvo.length || decidir.isPending} onClick={() => decidir.mutate({ item_ids: alvo, acao: "aceitar" })}>
            <CheckCheck /> Aceitar sugestão {sel.size ? `(${fmtNum(sel.size)})` : `de todos (${fmtNum(alvo.length)})`}
          </Button>
        </div>
        {linhas.length === 0 ? (
          <EstadoVazio titulo="Nada a confirmar" descricao="Nenhum item tem código a ajustar no cadastro." />
        ) : (
          <div className="max-h-[36rem] overflow-y-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-superficie">
                <tr className="border-b border-regua text-left text-2xs text-tinta-3">
                  <th className="w-10 px-5 py-2">
                    <Checkbox
                      aria-label="Selecionar todos"
                      checked={todos}
                      onCheckedChange={(v) => setSel(v ? new Set(linhas.map((l) => l.item_id)) : new Set())}
                    />
                  </th>
                  <th className="px-2 py-2 font-medium">Linha</th>
                  <th className="px-3 py-2 font-medium">Item</th>
                  <th className="px-3 py-2 font-medium">NCM/NBS do ERP</th>
                  <th className="px-3 py-2 font-medium">Sugerido</th>
                  <th className="px-3 py-2 font-medium">cClassTrib</th>
                  <th className="px-5 py-2 font-medium">Situação</th>
                </tr>
              </thead>
              <tbody>
                {linhas.map((l) => (
                  <tr key={l.item_id} className="border-b border-regua align-top last:border-0">
                    <td className="px-5 py-2">
                      <Checkbox aria-label={`Selecionar ${l.descricao}`} checked={sel.has(l.item_id)} onCheckedChange={() => alternar(l.item_id)} />
                    </td>
                    <td className="num px-2 py-2 text-tinta-3">{l.linha}</td>
                    <td className="px-3 py-2">
                      {l.descricao}
                      {l.alternativas.length ? <span className="block text-2xs text-tinta-3">outras opções avaliadas: {l.alternativas.join(", ")}</span> : null}
                    </td>
                    <td className="codigo px-3 py-2 text-xs">{l.erp_formatado ?? <span className="font-sans text-tinta-3">sem código válido</span>}</td>
                    <td className="codigo px-3 py-2 text-xs">{l.sugerido_formatado ?? <span className="font-sans text-tinta-3">a definir</span>}</td>
                    <td className="codigo px-3 py-2 text-xs">{l.cclasstrib ?? "—"}</td>
                    <td className="px-5 py-2 text-xs text-tinta-2">{SITUACAO[l.status ?? ""] ?? l.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Painel>
    </div>
  );
}
