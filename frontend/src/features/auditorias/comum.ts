import { useQuery } from "@tanstack/react-query";
import { api, ok, type Schemas } from "@/api/client";

export const ROTULO_STATUS_AUDITORIA: Record<string, string> = {
  rascunho: "Rascunho",
  preparando: "Lendo a planilha",
  pronta: "Pronta para iniciar",
  processando: "Em processamento",
  aguardando_lote: "Aguardando lote da IA",
  pausada_orcamento: "Pausada (orçamento de IA)",
  pausada_ia: "Pausada (a IA não respondeu)",
  concluida: "Concluída",
  falhou: "Falhou",
  cancelada: "Cancelada",
};

export const ETAPAS: Record<string, string> = {
  na_fila: "Na fila",
  normalizar: "Normalizando descrição",
  validar_estrutura: "Validando código",
  buscar_memoria: "Consultando memória aprovada",
  recuperar_candidatos: "Buscando códigos candidatos",
  julgar_coerencia: "Análise por IA",
  escalar: "Segundo parecer",
  investigar: "Investigação jurídica da família",
  levantar_fatos: "Levantando fatos do item",
  aguardando_lote: "Aguardando lote",
};

export type Auditoria = Schemas["AuditoriaOut"];

export function useAuditoria(
  id: string,
  refetch?: number | false | ((q: { state: { data?: Auditoria } }) => number | false),
) {
  return useQuery({
    queryKey: ["auditoria", id],
    queryFn: () => ok(api.GET("/api/auditorias/{audit_id}", { params: { path: { audit_id: id } } })),
    refetchInterval: refetch as number | false | undefined,
  });
}

/** Linha da tabela de itens (formato colunar convertido em objetos). */
export interface LinhaItem {
  id: string;
  linha: number;
  codigo_interno: string;
  descricao: string;
  tipo: string | null;
  codigo_atual: string | null;
  codigo_sugerido: string | null;
  tipo_codigo: string;
  status: string;
  motivos: string[];
  confianca_global: string | null;
  revisao_status: string;
  tratamento: string | null;
  cclasstrib_sugerido: string | null;
  cst_sugerido: string | null;
  imposto_seletivo: string | null;
  perguntas: number;
  origem: string | null;
  nivel_revisao: string | null;
  aprovado_automaticamente: boolean;
  categoria: string | null;
  hipotese: string | null;
}

export const TRATAMENTO: Record<string, string> = {
  beneficio: "Benefício (redução/alíquota zero)",
  regime_especifico: "Regime específico",
  regra_geral: "Tributação integral",
  nao_incidencia: "Não incidência",
};

export type DossieDecisao = Schemas["DossieDecisao"];

/** Item ainda passando pelos agentes (na fila ou em processamento). */
export function emAndamento(status: string | null | undefined): boolean {
  return status === "pendente" || status === "processando";
}

export function useDossieItem(id: string | null) {
  return useQuery({
    queryKey: ["dossie-item", id],
    queryFn: () => ok(api.GET("/api/itens/{item_id}/dossie", { params: { path: { item_id: id! } } })),
    enabled: !!id,
    // Durante a (re)análise, consulta de novo até o item chegar a um status final.
    refetchInterval: (q) => (emAndamento((q.state.data?.item as { status?: string } | undefined)?.status) ? 2500 : false),
  });
}

export function usePendencias(auditId: string, status: string = "aberta") {
  return useQuery({
    queryKey: ["pendencias", auditId, status],
    queryFn: () => ok(api.GET("/api/auditorias/{audit_id}/pendencias", { params: { path: { audit_id: auditId }, query: { status } } })),
  });
}

export function useItens(auditId: string) {
  return useQuery({
    queryKey: ["itens", auditId],
    queryFn: async () => {
      const d = await ok(api.GET("/api/auditorias/{audit_id}/itens", { params: { path: { audit_id: auditId } } }));
      const campos = d.campos;
      return d.linhas.map((l) => Object.fromEntries(campos.map((c, i) => [c, l[i]])) as unknown as LinhaItem);
    },
    staleTime: 10_000,
    // Enquanto houver item na fila ou em processamento, a lista se atualiza sozinha.
    refetchInterval: (q) => (q.state.data?.some((i) => emAndamento(i.status)) ? 4000 : false),
  });
}

export type ItemDetalhe = Schemas["ItemDetalhe"];

export function useItemDetalhe(id: string | null) {
  return useQuery({
    queryKey: ["item", id],
    queryFn: () => ok(api.GET("/api/itens/{item_id}", { params: { path: { item_id: id! } } })),
    enabled: !!id,
  });
}
