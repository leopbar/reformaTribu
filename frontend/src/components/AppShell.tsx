import { useQuery } from "@tanstack/react-query";
import { Link, Outlet, useNavigate, useRouterState } from "@tanstack/react-router";
import { Command } from "cmdk";
import {
  Bell,
  Bot,
  Building2,
  ChevronsUpDown,
  ClipboardList,
  FileSearch,
  Home,
  KeyRound,
  Landmark,
  LogOut,
  Moon,
  ScrollText,
  Search,
  Settings,
  Sun,
  UserRound,
} from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { api, ok } from "@/api/client";
import { useAuth } from "@/auth/auth";
import { fmtDataHora } from "@/lib/format";
import { cn } from "@/lib/utils";
import { AvisoResponsabilidade, mensagemErro } from "./dominio";
import { Button, Kbd, Menu, MenuContent, MenuItem, MenuLabel, MenuSeparator, MenuTrigger, Popover, PopoverContent, PopoverTrigger } from "./ui/primitives";

export function useTema() {
  const [escuro, setEscuro] = useState(() => document.documentElement.classList.contains("dark"));
  useEffect(() => {
    document.documentElement.classList.toggle("dark", escuro);
    try {
      localStorage.setItem("tema", escuro ? "escuro" : "claro");
    } catch {
      /* armazenamento indisponível */
    }
  }, [escuro]);
  return { escuro, alternar: () => setEscuro((e) => !e) };
}

const NAV = [
  { para: "/", rotulo: "Painel", icone: Home, perm: "ver" },
  { para: "/auditorias", rotulo: "Auditorias", icone: ClipboardList, perm: "ver" },
  { para: "/empresas", rotulo: "Empresas", icone: Building2, perm: "ver" },
  { para: "/atividades", rotulo: "Atividades", icone: ScrollText, perm: "ver_log" },
  { para: "/configuracoes", rotulo: "Configurações", icone: Settings, perm: "ver" },
] as const;

export function AppShell() {
  const { sessao, sair, trocarOrganizacao, pode } = useAuth();
  const { escuro, alternar } = useTema();
  const [paleta, setPaleta] = useState(false);
  const navegar = useNavigate();
  const caminho = useRouterState({ select: (s) => s.location.pathname });

  useEffect(() => {
    const aoTeclar = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaleta((p) => !p);
      }
    };
    window.addEventListener("keydown", aoTeclar);
    return () => window.removeEventListener("keydown", aoTeclar);
  }, []);

  if (!sessao) return null;
  const temOrg = !!sessao.org_atual;

  return (
    <div className="flex min-h-dvh">
      <a href="#conteudo" className="sr-only focus:not-sr-only focus:fixed focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-superficie focus:px-3 focus:py-2">
        Pular para o conteúdo
      </a>
      <aside className="sticky top-0 hidden h-dvh w-56 shrink-0 flex-col border-r border-regua bg-superficie md:flex">
        <div className="flex h-14 items-center gap-2 border-b border-regua px-4">
          <img src="/marca.svg" alt="" className="size-7" />
          <div className="leading-tight">
            <p className="text-sm font-semibold">Auditor Fiscal</p>
            <p className="text-2xs text-tinta-3">Reforma Tributária</p>
          </div>
        </div>
        <nav aria-label="Principal" className="flex flex-1 flex-col gap-0.5 p-2">
          {temOrg &&
            NAV.filter((n) => pode(n.perm)).map((n) => {
              const ativo = n.para === "/" ? caminho === "/" : caminho.startsWith(n.para);
              return (
                <Link
                  key={n.para}
                  to={n.para}
                  className={cn(
                    "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm text-tinta-2 hover:bg-superficie-2 hover:text-tinta",
                    ativo && "bg-superficie-2 font-medium text-tinta shadow-[inset_2px_0_0_var(--tinta)]",
                  )}
                  aria-current={ativo ? "page" : undefined}
                >
                  <n.icone className="size-4" aria-hidden />
                  {n.rotulo}
                </Link>
              );
            })}
          {sessao.superadmin ? (
            <>
              <p className="mt-4 px-3 pb-1 text-2xs font-medium text-tinta-3">Plataforma</p>
              <Link
                to="/referencia"
                className={cn(
                  "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm text-tinta-2 hover:bg-superficie-2",
                  caminho.startsWith("/referencia") && "bg-superficie-2 font-medium text-tinta",
                )}
              >
                <FileSearch className="size-4" aria-hidden /> Base de referência
              </Link>
              <Link
                to="/plataforma"
                className={cn(
                  "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm text-tinta-2 hover:bg-superficie-2",
                  caminho.startsWith("/plataforma") && "bg-superficie-2 font-medium text-tinta",
                )}
              >
                <Landmark className="size-4" aria-hidden /> Organizações
              </Link>
              <Link
                to="/ia/modelos"
                className={cn(
                  "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm text-tinta-2 hover:bg-superficie-2",
                  caminho.startsWith("/ia/modelos") && "bg-superficie-2 font-medium text-tinta",
                )}
              >
                <Bot className="size-4" aria-hidden /> Modelos de IA
              </Link>
              <Link
                to="/ia/chaves"
                className={cn(
                  "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm text-tinta-2 hover:bg-superficie-2",
                  caminho.startsWith("/ia/chaves") && "bg-superficie-2 font-medium text-tinta",
                )}
              >
                <KeyRound className="size-4" aria-hidden /> Chaves de API
              </Link>
            </>
          ) : null}
        </nav>
        <div className="border-t border-regua p-3">
          <AvisoResponsabilidade />
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-regua bg-papel/90 px-4 backdrop-blur">
          <Menu>
            <MenuTrigger asChild>
              <Button variant="fantasma" className="max-w-[18rem] justify-between gap-2 px-2">
                <span className="truncate text-left">
                  <span className="block text-2xs text-tinta-3">Organização</span>
                  <span className="block truncate text-sm font-medium">{sessao.org_atual?.nome ?? "Selecione"}</span>
                </span>
                <ChevronsUpDown className="text-tinta-3" />
              </Button>
            </MenuTrigger>
            <MenuContent align="start">
              <MenuLabel>Suas organizações</MenuLabel>
              {sessao.organizacoes.map((o) => (
                <MenuItem
                  key={o.org_id}
                  onSelect={async () => {
                    try {
                      await trocarOrganizacao(o.org_id);
                      toast.success(`Organização: ${o.nome}`);
                      void navegar({ to: "/" });
                    } catch (e) {
                      toast.error(mensagemErro(e));
                    }
                  }}
                >
                  <span className="flex-1 truncate">{o.nome}</span>
                  {o.org_id === sessao.org_atual?.org_id ? <span className="text-2xs text-conferido">atual</span> : null}
                </MenuItem>
              ))}
              {sessao.organizacoes.length === 0 ? <MenuItem disabled>Nenhuma organização vinculada</MenuItem> : null}
            </MenuContent>
          </Menu>

          <button
            type="button"
            onClick={() => setPaleta(true)}
            className="ml-auto hidden h-9 w-72 items-center gap-2 rounded-md border border-regua bg-superficie px-3 text-sm text-tinta-3 hover:border-regua-forte sm:flex"
          >
            <Search className="size-4" aria-hidden />
            Buscar ou ir para…
            <span className="ml-auto flex gap-1">
              <Kbd>Ctrl</Kbd>
              <Kbd>K</Kbd>
            </span>
          </button>
          {temOrg ? <Notificacoes /> : null}
          <Button variant="fantasma" tamanho="icone" onClick={alternar} aria-label={escuro ? "Usar tema claro" : "Usar tema escuro"}>
            {escuro ? <Sun /> : <Moon />}
          </Button>
          <Menu>
            <MenuTrigger asChild>
              <Button variant="fantasma" tamanho="icone" aria-label="Conta">
                <UserRound />
              </Button>
            </MenuTrigger>
            <MenuContent>
              <MenuLabel>
                {sessao.nome}
                <span className="block font-normal">{sessao.email}</span>
                {sessao.org_atual ? <span className="block font-normal capitalize">{sessao.org_atual.papel}</span> : null}
              </MenuLabel>
              <MenuSeparator />
              <MenuItem onSelect={() => void navegar({ to: "/conta" })}>
                <UserRound /> Minha conta
              </MenuItem>
              <MenuItem
                onSelect={async () => {
                  await sair();
                  void navegar({ to: "/entrar" });
                }}
              >
                <LogOut /> Sair
              </MenuItem>
            </MenuContent>
          </Menu>
        </header>

        <main id="conteudo" className="mx-auto w-full max-w-[1600px] flex-1 px-4 py-6 md:px-8">
          <Outlet />
        </main>
        <footer className="border-t border-regua px-4 py-3 md:hidden">
          <AvisoResponsabilidade />
        </footer>
      </div>

      <PaletaComandos aberta={paleta} aoFechar={() => setPaleta(false)} />
    </div>
  );
}

function Notificacoes() {
  const q = useQuery({
    queryKey: ["notificacoes"],
    queryFn: () => ok(api.GET("/api/notificacoes", { params: { query: {} } })),
    refetchInterval: 60_000,
  });
  const naoLidas = (q.data ?? []).filter((n) => !n.lida_em).length;
  return (
    <Popover
      onOpenChange={async (aberto) => {
        if (!aberto && naoLidas) {
          await api.POST("/api/notificacoes/marcar-lidas");
          void q.refetch();
        }
      }}
    >
      <PopoverTrigger asChild>
        <Button variant="fantasma" tamanho="icone" aria-label={`Notificações${naoLidas ? `: ${naoLidas} não lidas` : ""}`} className="relative">
          <Bell />
          {naoLidas ? <span className="absolute right-2 top-2 size-2 rounded-full bg-ocre" aria-hidden /> : null}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-96 p-0">
        <p className="border-b border-regua px-4 py-2.5 text-sm font-medium">Notificações</p>
        <ul className="max-h-96 overflow-y-auto">
          {(q.data ?? []).length === 0 ? (
            <li className="px-4 py-6 text-center text-sm text-tinta-3">Nada novo por aqui.</li>
          ) : (
            q.data!.map((n) => (
              <li key={n.id} className={cn("border-b border-regua px-4 py-3 last:border-0", !n.lida_em && "bg-superficie-2")}>
                <p className="text-sm font-medium">{n.titulo}</p>
                <p className="text-xs text-tinta-2">{n.mensagem}</p>
                <p className="mt-1 flex justify-between text-2xs text-tinta-3">
                  {fmtDataHora(n.created_at)}
                  {n.link ? (
                    <Link to={n.link} className="text-caneta hover:underline">
                      Abrir
                    </Link>
                  ) : null}
                </p>
              </li>
            ))
          )}
        </ul>
      </PopoverContent>
    </Popover>
  );
}

function PaletaComandos({ aberta, aoFechar }: { aberta: boolean; aoFechar: () => void }) {
  const navegar = useNavigate();
  const { pode, sessao } = useAuth();
  const empresas = useQuery({
    queryKey: ["empresas"],
    queryFn: () => ok(api.GET("/api/empresas", { params: { query: {} } })),
    enabled: aberta && !!sessao?.org_atual,
  });
  const auditorias = useQuery({
    queryKey: ["auditorias", "paleta"],
    queryFn: () => ok(api.GET("/api/auditorias", { params: { query: { limite: 30 } } })),
    enabled: aberta && !!sessao?.org_atual,
  });
  const ir = (para: string) => {
    aoFechar();
    void navegar({ to: para });
  };
  if (!aberta) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-tinta/30 pt-[12vh]" onClick={aoFechar}>
      <Command
        label="Paleta de comandos"
        className="w-full max-w-xl overflow-hidden rounded-lg border border-regua bg-superficie shadow-painel"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => e.key === "Escape" && aoFechar()}
      >
        <div className="flex items-center gap-2 border-b border-regua px-4">
          <Search className="size-4 text-tinta-3" aria-hidden />
          <Command.Input autoFocus placeholder="Buscar empresa, auditoria ou ação…" className="h-12 w-full bg-transparent text-sm outline-none" />
        </div>
        <Command.List className="max-h-96 overflow-y-auto p-2 [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-2xs [&_[cmdk-group-heading]]:text-tinta-3">
          <Command.Empty className="px-3 py-6 text-center text-sm text-tinta-3">Nada encontrado.</Command.Empty>
          <Command.Group heading="Ações">
            {pode("criar_auditoria") ? <Item aoSelecionar={() => ir("/auditorias/nova")}>Nova auditoria (enviar planilha)</Item> : null}
            <Item aoSelecionar={() => ir("/")}>Ir para o painel</Item>
            <Item aoSelecionar={() => ir("/auditorias")}>Ver auditorias</Item>
            <Item aoSelecionar={() => ir("/empresas")}>Ver empresas</Item>
            {pode("gerenciar_configuracoes") ? <Item aoSelecionar={() => ir("/configuracoes")}>Configurações</Item> : null}
            {sessao?.superadmin ? <Item aoSelecionar={() => ir("/referencia/regras")}>Regras legais (resumo)</Item> : null}
          </Command.Group>
          <Command.Group heading="Auditorias">
            {(auditorias.data ?? []).map((a) => (
              <Item key={a.id} aoSelecionar={() => ir(`/auditorias/${a.id}`)}>
                {a.nome} <span className="text-tinta-3">· {a.empresa}</span>
              </Item>
            ))}
          </Command.Group>
          <Command.Group heading="Empresas">
            {(empresas.data ?? []).map((e) => (
              <Item key={e.id} aoSelecionar={() => ir(`/empresas/${e.id}`)}>
                {e.razao_social}
              </Item>
            ))}
          </Command.Group>
        </Command.List>
      </Command>
    </div>
  );
}

function Item({ children, aoSelecionar }: { children: React.ReactNode; aoSelecionar: () => void }) {
  return (
    <Command.Item
      onSelect={aoSelecionar}
      className="flex cursor-default items-center gap-2 rounded-md px-3 py-2 text-sm data-[selected=true]:bg-superficie-2"
    >
      {children}
    </Command.Item>
  );
}
