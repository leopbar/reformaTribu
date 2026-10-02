import { QueryClient } from "@tanstack/react-query";
import { createRootRouteWithContext, createRoute, createRouter, Link, Navigate, Outlet } from "@tanstack/react-router";
import { useAuth } from "@/auth/auth";
import { AppShell } from "@/components/AppShell";
import { EstadoVazio } from "@/components/dominio";
import { Button, Skeleton } from "@/components/ui/primitives";
import { LoginPage } from "@/features/auth/LoginPage";
import { AuditoriaPage } from "@/features/auditorias/AuditoriaPage";
import { AuditoriasPage } from "@/features/auditorias/AuditoriasPage";
import { ExportarPage } from "@/features/auditorias/ExportarPage";
import { FilaRevisaoPage } from "@/features/auditorias/FilaRevisaoPage";
import { NovaAuditoriaPage } from "@/features/auditorias/NovaAuditoriaPage";
import { ConfiguracoesPage } from "@/features/configuracoes/ConfiguracoesPage";
import { EmpresaDetalhePage, EmpresasPage } from "@/features/empresas/EmpresasPage";
import { AtividadesPage, ContaPage, PlataformaPage } from "@/features/outros/OutrasPaginas";
import { PainelPage } from "@/features/painel/PainelPage";
import { ChavesApiPage } from "@/features/ia/ChavesApiPage";
import { ModelosPage } from "@/features/ia/ModelosPage";
import { BaseReferenciaPage, RegraRevisaoPage, RegrasDetalhesPage, RegrasPage } from "@/features/referencia/ReferenciaPages";

interface Contexto {
  queryClient: QueryClient;
}

const raiz = createRootRouteWithContext<Contexto>()({
  component: () => <Outlet />,
  notFoundComponent: () => (
    <div className="p-10">
      <EstadoVazio titulo="Página não encontrada" descricao="O endereço não existe ou foi movido." acao={<Button asChild variant="primario"><Link to="/">Ir para o painel</Link></Button>} />
    </div>
  ),
});

function Protegido() {
  const { sessao, carregando } = useAuth();
  if (carregando) return <div className="p-10"><Skeleton className="h-96" /></div>;
  if (!sessao) return <Navigate to="/entrar" />;
  return <AppShell />;
}

function SemOrganizacao({ children }: { children: React.ReactNode }) {
  const { sessao } = useAuth();
  if (sessao && !sessao.org_atual) {
    return sessao.superadmin ? (
      <Navigate to="/referencia" />
    ) : (
      <EstadoVazio titulo="Você ainda não está em nenhuma organização" descricao="Peça ao administrador do escritório ou da empresa para adicionar o seu e-mail." />
    );
  }
  return <>{children}</>;
}

const entrar = createRoute({ getParentRoute: () => raiz, path: "/entrar", component: LoginPage });
const app = createRoute({ getParentRoute: () => raiz, id: "app", component: Protegido });
function comOrg(Comp: () => React.JSX.Element) {
  return function ComOrganizacao() {
    return (
      <SemOrganizacao>
        <Comp />
      </SemOrganizacao>
    );
  };
}

const painel = createRoute({ getParentRoute: () => app, path: "/", component: comOrg(PainelPage) });
const empresas = createRoute({ getParentRoute: () => app, path: "/empresas", component: comOrg(EmpresasPage) });
const empresa = createRoute({ getParentRoute: () => app, path: "/empresas/$id", component: comOrg(EmpresaDetalhePage) });
const auditorias = createRoute({ getParentRoute: () => app, path: "/auditorias", component: comOrg(AuditoriasPage) });
const nova = createRoute({
  getParentRoute: () => app,
  path: "/auditorias/nova",
  validateSearch: (s: Record<string, unknown>): { empresa?: string } => ({ empresa: typeof s.empresa === "string" ? s.empresa : undefined }),
  component: comOrg(NovaAuditoriaPage),
});
const auditoria = createRoute({ getParentRoute: () => app, path: "/auditorias/$id", component: comOrg(AuditoriaPage) });
const revisar = createRoute({ getParentRoute: () => app, path: "/auditorias/$id/revisar", component: comOrg(FilaRevisaoPage) });
const exportar = createRoute({ getParentRoute: () => app, path: "/auditorias/$id/exportar", component: comOrg(ExportarPage) });
const configuracoes = createRoute({ getParentRoute: () => app, path: "/configuracoes", component: comOrg(ConfiguracoesPage) });
const atividades = createRoute({ getParentRoute: () => app, path: "/atividades", component: comOrg(AtividadesPage) });
const conta = createRoute({ getParentRoute: () => app, path: "/conta", component: ContaPage });
const referencia = createRoute({ getParentRoute: () => app, path: "/referencia", component: BaseReferenciaPage });
const regras = createRoute({ getParentRoute: () => app, path: "/referencia/regras", component: RegrasPage });
const regrasDetalhes = createRoute({ getParentRoute: () => app, path: "/referencia/regras/detalhes", component: RegrasDetalhesPage });
const regra = createRoute({ getParentRoute: () => app, path: "/referencia/regras/$id", component: RegraRevisaoPage });
const iaModelos = createRoute({ getParentRoute: () => app, path: "/ia/modelos", component: ModelosPage });
const iaChaves = createRoute({ getParentRoute: () => app, path: "/ia/chaves", component: ChavesApiPage });
const plataforma = createRoute({ getParentRoute: () => app, path: "/plataforma", component: PlataformaPage });

const arvore = raiz.addChildren([
  entrar,
  app.addChildren([painel, empresas, empresa, auditorias, nova, auditoria, revisar, exportar, configuracoes, atividades, conta, referencia, regras, regrasDetalhes, regra, plataforma, iaModelos, iaChaves]),
]);

export function criarRouter(queryClient: QueryClient) {
  return createRouter({ routeTree: arvore, context: { queryClient }, defaultPreload: "intent", scrollRestoration: true });
}

declare module "@tanstack/react-router" {
  interface Register {
    router: ReturnType<typeof criarRouter>;
  }
}
