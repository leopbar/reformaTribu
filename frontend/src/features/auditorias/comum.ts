import { useQuery } from "@tanstack/react-query";
import { api, ok, type Schemas } from "@/api/client";

export const ROTULO_STATUS_AUDITORIA: Record<string, string> = {
  rascunho: "Rascunho",
  preparando: "Lendo a planilha",
  pronta: "Pronta para iniciar",
  processando: "Em processamento",
  aguardando_lote: "Aguardando lote da IA",
  pausada_orcamento: "Pausada (orçamento de IA)",
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
  enquadrar: "Enquadramento legal",
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
  confianca: number | null;
  revisao_status: string;
  anexo: string | null;
  cclasstrib_sugerido: string | null;
  cst_sugerido: string | null;
  imposto_seletivo: boolean;
  perguntas: number;
  origem: string | null;
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
