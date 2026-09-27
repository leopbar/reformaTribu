import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ClipboardList, Upload } from "lucide-react";
import { api, ok } from "@/api/client";
import { useAuth } from "@/auth/auth";
import { Cabecalho, EstadoErro, EstadoVazio } from "@/components/dominio";
import { Button, Painel, Skeleton } from "@/components/ui/primitives";
import { fmtDataHora, fmtNum, fmtUSD } from "@/lib/format";
import { ROTULO_STATUS_AUDITORIA } from "./comum";

export function AuditoriasPage() {
  const { pode } = useAuth();
  const q = useQuery({ queryKey: ["auditorias"], queryFn: () => ok(api.GET("/api/auditorias", { params: { query: {} } })), refetchInterval: 15_000 });
  return (
    <>
      <Cabecalho
        titulo="Auditorias"
        acoes={
          pode("criar_auditoria") ? (
            <Button asChild variant="primario">
              <Link to="/auditorias/nova">
                <Upload /> Enviar planilha
              </Link>
            </Button>
          ) : null
        }
      />
      {q.isError ? <EstadoErro erro={q.error} aoTentar={() => void q.refetch()} /> : null}
      {q.isLoading ? <Skeleton className="h-48" /> : null}
      {q.data?.length === 0 ? (
        <EstadoVazio icone={<ClipboardList className="size-8" />} titulo="Nenhuma auditoria ainda" descricao="Envie a planilha de produtos e serviços de uma empresa para começar a primeira auditoria." acao={pode("criar_auditoria") ? <Button asChild variant="primario"><Link to="/auditorias/nova">Enviar planilha</Link></Button> : null} />
      ) : null}
      {q.data && q.data.length > 0 ? (
        <Painel className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-regua text-left text-2xs text-tinta-3">
                <th className="px-5 py-2 font-medium">Auditoria</th>
                <th className="px-3 py-2 font-medium">Empresa</th>
                <th className="px-3 py-2 font-medium">Situação</th>
                <th className="px-3 py-2 text-right font-medium">Itens</th>
                <th className="px-3 py-2 text-right font-medium">Para revisar</th>
                <th className="px-5 py-2 text-right font-medium">Custo de IA</th>
              </tr>
            </thead>
            <tbody>
              {q.data.map((a) => (
                <tr key={a.id} className="border-b border-regua last:border-0 hover:bg-superficie-2">
                  <td className="px-5 py-3">
                    <Link to="/auditorias/$id" params={{ id: a.id }} className="font-medium hover:underline">
                      {a.nome}
                    </Link>
                    <span className="block text-2xs text-tinta-3">{fmtDataHora(a.created_at)}</span>
                  </td>
                  <td className="px-3 py-3 text-tinta-2">{a.empresa}</td>
                  <td className="px-3 py-3">{ROTULO_STATUS_AUDITORIA[a.status] ?? a.status}</td>
                  <td className="num px-3 py-3 text-right">{fmtNum(a.total_itens)}</td>
                  <td className="num px-3 py-3 text-right">{a.pendentes_revisao ? fmtNum(a.pendentes_revisao) : "—"}</td>
                  <td className="num px-5 py-3 text-right">{fmtUSD(a.custo_usd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Painel>
      ) : null}
    </>
  );
}
