import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, definirSessao, obterSessao, ok, ouvirSessao, renovarSessao, type Sessao } from "@/api/client";
import { useQueryClient } from "@tanstack/react-query";

interface AuthCtx {
  sessao: Sessao | null;
  carregando: boolean;
  entrar: (email: string, senha: string) => Promise<Sessao>;
  sair: () => Promise<void>;
  trocarOrganizacao: (orgId: string) => Promise<void>;
  pode: (permissao: string) => boolean;
}

const Ctx = createContext<AuthCtx | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [sessao, setSessao] = useState<Sessao | null>(obterSessao());
  const [carregando, setCarregando] = useState(true);
  const qc = useQueryClient();

  useEffect(() => ouvirSessao(setSessao), []);
  useEffect(() => {
    renovarSessao().finally(() => setCarregando(false));
  }, []);
  // Renova o token de acesso um pouco antes de expirar.
  useEffect(() => {
    if (!sessao) return;
    const t = setTimeout(() => void renovarSessao(), Math.max(30, sessao.expira_em_segundos - 60) * 1000);
    return () => clearTimeout(t);
  }, [sessao]);

  const entrar = useCallback(async (email: string, senha: string) => {
    const s = await ok(api.POST("/api/auth/login", { body: { email, senha } }));
    definirSessao(s);
    return s;
  }, []);

  const sair = useCallback(async () => {
    try {
      await api.POST("/api/auth/logout");
    } finally {
      definirSessao(null);
      qc.clear();
    }
  }, [qc]);

  const trocarOrganizacao = useCallback(
    async (orgId: string) => {
      const s = await ok(api.POST("/api/auth/trocar-organizacao", { body: { org_id: orgId } }));
      definirSessao(s);
      qc.clear();
    },
    [qc],
  );

  const pode = useCallback((p: string) => !!sessao?.permissoes.includes(p), [sessao]);

  const valor = useMemo(
    () => ({ sessao, carregando, entrar, sair, trocarOrganizacao, pode }),
    [sessao, carregando, entrar, sair, trocarOrganizacao, pode],
  );
  return <Ctx.Provider value={valor}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthCtx {
  const c = useContext(Ctx);
  if (!c) throw new Error("useAuth fora do AuthProvider");
  return c;
}
