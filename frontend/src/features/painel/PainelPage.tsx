import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ArrowRight, Building2, Upload } from "lucide-react";
import { api, ok } from "@/api/client";
import { useAuth } from "@/auth/auth";
import { Cabecalho, EstadoErro, EstadoVazio } from "@/components/dominio";
import { Button, Painel, Progresso, Skeleton } from "@/components/ui/primitives";
import { fmtCnpj, fmtData, fmtNum, fmtUSD } from "@/lib/format";
import { ROTULO_STATUS_AUDITORIA } from "@/features/auditorias/comum";

export function PainelPage() {
  const { sessao, pode } = useAuth();
  const q = useQuery({ queryKey: ["painel"], queryFn: () => ok(api.GET("/api/painel")), refetchInterval: 20_000 });
  const escritorio = sessao?.org_atual?.tipo === "escritorio_contabil";

  return (
    <>
      <Cabecalho
        titulo={escritorio ? "Carteira de clientes" : "Painel"}
        subtitulo={sessao?.org_atual?.nome}
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
      {q.isLoading ? <Skeleton className="h-64" /> : null}
      {q.data ? (
        <div className="space-y-6">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Numero rotulo="Empresas" valor={fmtNum(q.data.totais.empresas as number)} />
            <Numero rotulo="Itens para revisar" valor={fmtNum(q.data.totais.pendentes_revisao as number)} destaque />
            <Numero rotulo="Aguardando informação" valor={fmtNum(q.data.totais.aguardando_informacao as number)} />
            {q.data.totais.gasto_mes_usd != null ? (
              <Numero
                rotulo="IA no mês"
                valor={fmtUSD(q.data.totais.gasto_mes_usd as number)}
                sub={q.data.totais.orcamento_usd ? `de ${fmtUSD(q.data.totais.orcamento_usd as number)}` : undefined}
              />
            ) : null}
          </div>

          {q.data.em_andamento.length ? (
            <Painel>
              <h2 className="border-b border-regua px-5 py-3 text-base">Auditorias em andamento</h2>
              <ul>
                {q.data.em_andamento.map((a) => {
                  const c = a.contadores as { concluidos?: number; total?: number };
                  const pct = c?.total ? ((c.concluidos ?? 0) / c.total) * 100 : 0;
                  return (
                    <li key={a.id as string} className="border-b border-regua last:border-0">
                      <Link to="/auditorias/$id" params={{ id: a.id as string }} className="grid items-center gap-4 px-5 py-3 hover:bg-superficie-2 sm:grid-cols-[1fr_12rem_8rem]">
                        <span>
                          <span className="font-medium">{a.nome as string}</span>
                          <span className="block text-xs text-tinta-3">{a.empresa as string}</span>
                        </span>
                        <Progresso valor={pct} rotulo={`Progresso de ${a.nome}`} />
                        <span className="text-right text-xs text-tinta-2">{ROTULO_STATUS_AUDITORIA[a.status as string] ?? (a.status as string)}</span>
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </Painel>
          ) : null}

          <Painel>
            <h2 className="border-b border-regua px-5 py-3 text-base">Empresas</h2>
            {q.data.empresas.length === 0 ? (
              <div className="p-5">
                <EstadoVazio
                  icone={<Building2 className="size-8" />}
                  titulo="Nenhuma empresa cadastrada"
                  descricao="Cadastre a primeira empresa a ser auditada. Depois, envie a planilha de produtos e serviços dela."
                  acao={
                    pode("gerenciar_empresas") ? (
                      <Button asChild variant="primario">
                        <Link to="/empresas">Cadastrar empresa</Link>
                      </Button>
                    ) : null
                  }
                />
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-regua text-left text-2xs text-tinta-3">
                      <th className="px-5 py-2 font-medium">Empresa</th>
                      <th className="px-3 py-2 font-medium">Última auditoria</th>
                      <th className="px-3 py-2 text-right font-medium">Para revisar</th>
                      <th className="px-3 py-2 text-right font-medium">Aguardando informação</th>
                      <th className="px-5 py-2" />
                    </tr>
                  </thead>
                  <tbody>
                    {q.data.empresas.map((e) => (
                      <tr key={e.id} className="border-b border-regua last:border-0 hover:bg-superficie-2">
                        <td className="px-5 py-3">
                          <Link to="/empresas/$id" params={{ id: e.id }} className="font-medium hover:underline">
                            {e.razao_social}
                          </Link>
                          <span className="codigo block text-2xs text-tinta-3">{fmtCnpj(e.cnpj)}</span>
                        </td>
                        <td className="px-3 py-3 text-tinta-2">
                          {e.ultima_auditoria_em ? (
                            <>
                              {fmtData(e.ultima_auditoria_em)}
                              <span className="block text-2xs text-tinta-3">{ROTULO_STATUS_AUDITORIA[e.ultima_auditoria_status ?? ""] ?? ""}</span>
                            </>
                          ) : (
                            <span className="text-tinta-3">Nunca auditada</span>
                          )}
                        </td>
                        <td className="num px-3 py-3 text-right">{e.pendentes_revisao ? fmtNum(e.pendentes_revisao) : <span className="text-tinta-3">—</span>}</td>
                        <td className="num px-3 py-3 text-right">
                          {e.aguardando_informacao ? <span className="font-medium text-ocre">{fmtNum(e.aguardando_informacao)}</span> : <span className="text-tinta-3">—</span>}
                        </td>
                        <td className="px-5 py-3 text-right">
                          {e.ultima_auditoria_id ? (
                            <Button asChild variant="fantasma" tamanho="sm">
                              <Link to="/auditorias/$id" params={{ id: e.ultima_auditoria_id }}>
                                Abrir <ArrowRight />
                              </Link>
                            </Button>
                          ) : pode("criar_auditoria") ? (
                            <Button asChild variant="fantasma" tamanho="sm">
                              <Link to="/auditorias/nova" search={{ empresa: e.id }}>
                                Auditar <ArrowRight />
                              </Link>
                            </Button>
                          ) : null}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Painel>
        </div>
      ) : null}
    </>
  );
}

function Numero({ rotulo, valor, sub, destaque }: { rotulo: string; valor: string; sub?: string; destaque?: boolean }) {
  return (
    <Painel className="px-5 py-4">
      <p className="text-xs text-tinta-3">{rotulo}</p>
      <p className={destaque ? "num mt-1 text-2xl font-semibold text-caneta" : "num mt-1 text-2xl font-semibold"}>{valor}</p>
      {sub ? <p className="text-2xs text-tinta-3">{sub}</p> : null}
    </Painel>
  );
}
