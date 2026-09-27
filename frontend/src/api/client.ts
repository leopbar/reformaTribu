/**
 * Cliente tipado da API (gerado do OpenAPI do FastAPI: `npm run api:gen`).
 * - Token de acesso curto em memória (nunca em localStorage).
 * - Refresh token em cookie httpOnly; renovação automática e única quando o acesso expira.
 * - Erros convertidos em ApiError com mensagem e ação em português.
 */
import createClient from "openapi-fetch";
import type { components, paths } from "./schema";

export type Schemas = components["schemas"];
export type Sessao = Schemas["SessaoOut"];

type Ouvinte = (s: Sessao | null) => void;

let accessToken: string | null = null;
let sessaoAtual: Sessao | null = null;
let renovando: Promise<Sessao | null> | null = null;
const ouvintes = new Set<Ouvinte>();

export class ApiError extends Error {
  status: number;
  codigo: string;
  acao?: string;
  detalhes?: unknown;
  constructor(status: number, codigo: string, mensagem: string, acao?: string, detalhes?: unknown) {
    super(mensagem);
    this.status = status;
    this.codigo = codigo;
    this.acao = acao;
    this.detalhes = detalhes;
  }
}

function lerCookie(nome: string): string | null {
  const m = document.cookie.match(new RegExp(`(?:^|; )${nome}=([^;]*)`));
  return m ? decodeURIComponent(m[1] ?? "") : null;
}

export function definirSessao(s: Sessao | null) {
  sessaoAtual = s;
  accessToken = s?.access_token ?? null;
  ouvintes.forEach((o) => o(s));
}

export function ouvirSessao(o: Ouvinte): () => void {
  ouvintes.add(o);
  return () => ouvintes.delete(o);
}

export const obterSessao = () => sessaoAtual;

type CorpoErro = { erro?: { codigo?: string; mensagem?: string; acao?: string; detalhes?: unknown } };

export async function erroDeResposta(resp: Response, jaLido?: unknown): Promise<ApiError> {
  let corpo: CorpoErro = (jaLido as CorpoErro) ?? {};
  if (!jaLido) {
    try {
      corpo = await resp.clone().json();
    } catch {
      /* corpo não-JSON ou já consumido */
    }
  }
  const e = corpo.erro ?? {};
  const padrao =
    resp.status >= 500
      ? "O servidor não conseguiu concluir a operação. Tente novamente em instantes."
      : "Não foi possível concluir a operação.";
  return new ApiError(resp.status, e.codigo ?? `http_${resp.status}`, e.mensagem ?? padrao, e.acao, e.detalhes);
}

export async function renovarSessao(): Promise<Sessao | null> {
  if (renovando) return renovando;
  renovando = (async () => {
    try {
      const resp = await fetch("/api/auth/refresh", {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-CSRF-Token": lerCookie("csrf_token") ?? "" },
      });
      if (!resp.ok) {
        definirSessao(null);
        return null;
      }
      const s = (await resp.json()) as Sessao;
      definirSessao(s);
      return s;
    } catch {
      return null;
    } finally {
      setTimeout(() => (renovando = null), 0);
    }
  })();
  return renovando;
}

export async function tokenValido(): Promise<string | null> {
  if (accessToken) return accessToken;
  return (await renovarSessao())?.access_token ?? null;
}

async function fetchAutenticado(input: Request): Promise<Response> {
  const tentativa = input.clone();
  if (accessToken) input.headers.set("Authorization", `Bearer ${accessToken}`);
  input.headers.set("X-CSRF-Token", lerCookie("csrf_token") ?? "");
  const resp = await fetch(input);
  if (resp.status !== 401 || input.url.includes("/api/auth/")) return resp;
  const nova = await renovarSessao();
  if (!nova) return resp;
  tentativa.headers.set("Authorization", `Bearer ${nova.access_token}`);
  return fetch(tentativa);
}

export const api = createClient<paths>({ baseUrl: "", fetch: fetchAutenticado, credentials: "same-origin" });

/** Desembrulha a resposta do openapi-fetch lançando ApiError em caso de erro. */
export async function ok<T>(p: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  const r = await p;
  if (!r.response.ok) throw await erroDeResposta(r.response, r.error);
  return r.data as T;
}

/** Requisições fora do contrato tipado (upload multipart, download de arquivos). */
export async function requisicao(url: string, init: RequestInit = {}): Promise<Response> {
  const req = new Request(url, { credentials: "same-origin", ...init });
  const resp = await fetchAutenticado(req);
  if (!resp.ok) throw await erroDeResposta(resp);
  return resp;
}

export async function baixarArquivo(url: string, nomePadrao: string) {
  const resp = await requisicao(url);
  const disp = resp.headers.get("content-disposition") ?? "";
  const nome = /filename="?([^"]+)"?/.exec(disp)?.[1] ?? nomePadrao;
  const blob = await resp.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = nome;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
