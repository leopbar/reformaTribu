import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, CircleHelp, Lightbulb, Pencil, Sparkles, Users } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { api, ok, type Schemas } from "@/api/client";
import { useAuth } from "@/auth/auth";
import { EstadoErro, EstadoVazio, mensagemErro } from "@/components/dominio";
import { Aviso, Button, Input, Painel, Skeleton } from "@/components/ui/primitives";
import { fmtDataHora, fmtNum, plural } from "@/lib/format";
import { usePendencias } from "./comum";

type Pendencia = Schemas["PendenciaOut"];
type Opcao = { valor: string; rotulo?: string; efeito?: string };

export function useResponder(auditId: string, aoConcluir?: () => void) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, valor, respostas_itens, observacao }: { id: string; valor?: string; respostas_itens?: Record<string, string>; observacao?: string }) =>
      ok(api.POST("/api/pendencias/{pendencia_id}/responder", { params: { path: { pendencia_id: id } }, body: { valor: valor ?? null, respostas_itens: respostas_itens ?? {}, observacao: observacao ?? null } })),
    onSuccess: (r) => {
      toast.success(r.mensagem);
      void qc.invalidateQueries({ queryKey: ["pendencias", auditId] });
      void qc.invalidateQueries({ queryKey: ["itens", auditId] });
      void qc.invalidateQueries({ queryKey: ["auditoria", auditId] });
      void qc.invalidateQueries({ queryKey: ["dossie-item"] });
      void qc.invalidateQueries({ queryKey: ["teses", auditId] });
      aoConcluir?.();
    },
    onError: (e) => toast.error(mensagemErro(e)),
  });
}

/** Perguntas decisivas do analista, agrupadas: uma resposta vale para os itens listados na pergunta. */
export function PerguntasPainel({ auditId }: { auditId: string }) {
  const [verRespondidas, setVerRespondidas] = useState(false);
  const q = usePendencias(auditId, verRespondidas ? "respondida" : "aberta");
  if (q.isError) return <EstadoErro erro={q.error} aoTentar={() => void q.refetch()} />;
  if (!q.data) return <Skeleton className="h-64" />;
  const total = q.data.reduce((s, p) => s + p.total_itens, 0);
  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <p className="max-w-3xl text-sm text-tinta-2">
          O analista só pergunta o que <strong>muda o enquadramento</strong>. Perguntas sobre a empresa têm uma resposta só;
          perguntas sobre o produto juntam os itens parecidos (a mesma categoria do ERP ou o mesmo NCM), mas cada item recebe a
          <strong> sua resposta</strong>, com a lista à vista (“Marcar todos” agiliza quando todos são iguais). Errou? Em “Ver
          perguntas respondidas”, use “Corrigir respostas”. Os itens são reclassificados na hora, sem novo custo de IA.
        </p>
        <Button variant="fantasma" tamanho="sm" className="ml-auto" onClick={() => setVerRespondidas((v) => !v)}>
          {verRespondidas ? "Ver perguntas abertas" : "Ver perguntas respondidas"}
        </Button>
      </div>
      {!verRespondidas && q.data.length > 0 ? (
        <Aviso tom="atencao" titulo={`${plural(q.data.length, "pergunta aberta destrava", "perguntas abertas destravam")} ${plural(total, "item", "itens")}`} />
      ) : null}
      {q.data.length === 0 ? (
        <EstadoVazio
          icone={<CheckCircle2 className="size-8 text-conferido" />}
          titulo={verRespondidas ? "Nenhuma pergunta respondida ainda" : "Nenhuma pergunta aberta"}
          descricao={verRespondidas ? undefined : "O analista tem todas as informações de que precisa para os itens desta auditoria."}
        />
      ) : (
        q.data.map((p) => <CartaoPergunta key={p.id} p={p} auditId={auditId} />)
      )}
    </div>
  );
}

const ESCOPO: Record<string, string> = { empresa: "Toda a empresa", grupo: "Grupo de itens", item: "Um item" };

function CartaoPergunta({ p, auditId }: { p: Pendencia; auditId: string }) {
  const { pode } = useAuth();
  const [obs, setObs] = useState("");
  const [respostas, setRespostas] = useState<Record<string, string>>({});
  const [corrigindo, setCorrigindo] = useState(false);
  const responder = useResponder(auditId, () => {
    setRespostas({});
    setCorrigindo(false);
  });
  const empresa = p.escopo === "empresa";
  const aberta = p.status === "aberta";
  // Pergunta sobre o produto com vários itens (ADR 0030): cada item recebe a sua resposta, com a lista à vista.
  const varios = !empresa && p.total_itens > 1;
  // A lista traz só uma amostra dos itens; quando eles precisam de resposta (ou de correção), busca todos.
  const completa = useQuery({
    queryKey: ["pendencia", p.id],
    queryFn: () => ok(api.GET("/api/pendencias/{pendencia_id}", { params: { path: { pendencia_id: p.id } } })),
    enabled: !empresa && p.total_itens > p.itens.length,
  });
  const itens = completa.data?.itens ?? p.itens;
  const opcoes = (p.opcoes as Opcao[]) ?? [];
  const rotulo = (v: string | null | undefined) => opcoes.find((o) => o.valor === v)?.rotulo ?? v ?? "";
  const sugestoes = p.itens.filter((i) => i.sugestao);
  const podeResponder = pode("responder") && aberta;
  const podeCorrigir = pode("responder") && p.status === "respondida" && !empresa && itens.length > 0;
  const editando = (podeResponder && varios) || corrigindo;
  const faltam = p.total_itens - itens.length;
  const [buscando, setBuscando] = useState(false);
  // Na correção, só vão os itens cuja resposta mudou.
  const enviar = corrigindo
    ? Object.fromEntries(Object.entries(respostas).filter(([id, v]) => itens.find((i) => i.id === id)?.resposta !== v))
    : respostas;
  const nEnviar = Object.keys(enviar).length;

  function marcarTodos(valor: string) {
    setRespostas(Object.fromEntries(itens.map((i) => [i.id, valor])));
  }

  // Confirma de uma vez as suposições da IA (cada item com a sua); itens sem suposição continuam abertos.
  async function confirmarSugestoes() {
    setBuscando(true);
    try {
      const todos =
        completa.data?.itens ??
        (p.total_itens > p.itens.length
          ? (await ok(api.GET("/api/pendencias/{pendencia_id}", { params: { path: { pendencia_id: p.id } } }))).itens
          : p.itens);
      const respostasSugeridas: Record<string, string> = {};
      for (const i of todos) if (i.sugestao?.valor) respostasSugeridas[i.id] = i.sugestao.valor;
      if (Object.keys(respostasSugeridas).length) responder.mutate({ id: p.id, respostas_itens: respostasSugeridas, observacao: obs || "suposições da IA conferidas e confirmadas" });
    } catch (e) {
      toast.error(mensagemErro(e));
    } finally {
      setBuscando(false);
    }
  }

  return (
    <Painel className="p-5">
      <div className="flex flex-wrap items-center gap-2 text-2xs text-tinta-3">
        <span className="inline-flex items-center gap-1 rounded-full border border-regua bg-superficie-2 px-2 py-0.5 font-medium text-tinta-2">
          <Users className="size-3" aria-hidden /> {p.grupo_rotulo ?? ESCOPO[p.escopo]}
        </span>
        {empresa && !aberta ? null : <span>{plural(p.total_itens, "item", "itens")}</span>}
        {p.status === "respondida" ? (
          <span className="text-conferido">
            Respondida {p.resposta === "por item" ? "item a item" : `“${rotulo(p.resposta)}”`} por {p.respondido_por_email} · {fmtDataHora(p.respondido_em)}
          </span>
        ) : null}
        {podeCorrigir && !corrigindo ? (
          <Button variant="fantasma" tamanho="sm" className="ml-auto" onClick={() => setCorrigindo(true)}>
            <Pencil className="size-3.5" aria-hidden /> Corrigir respostas
          </Button>
        ) : null}
      </div>
      <h3 className="mt-2 flex items-start gap-2 text-base font-semibold">
        <CircleHelp className="mt-0.5 size-5 shrink-0 text-ocre" aria-hidden />
        {p.pergunta}
      </h3>
      {!opcoes.some((o) => o.efeito) && p.motivo ? <p className="mt-2 pl-7 text-xs text-tinta-2">{p.motivo}</p> : null}
      {opcoes.some((o) => o.efeito) ? (
        <ul className="mt-2 grid gap-1 pl-7 text-xs text-tinta-2">
          {opcoes.map((o) => (
            <li key={o.valor}>
              <span className="font-medium text-tinta">Se “{o.rotulo ?? o.valor}”</span> → {o.efeito}
            </li>
          ))}
        </ul>
      ) : null}

      {aberta && sugestoes.length ? (
        <p className="mt-3 flex items-start gap-1.5 pl-7 text-xs text-caneta">
          <Lightbulb className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          A IA supõe uma resposta para {plural(sugestoes.length, "item", "itens")}, mas suposição não vira fato: confira os itens e confirme.
          {podeResponder ? (
            <Button variant="fantasma" tamanho="sm" className="ml-1 h-auto px-1.5 py-0.5 text-xs" disabled={responder.isPending || buscando} onClick={() => void confirmarSugestoes()}>
              Confirmar as suposições
            </Button>
          ) : null}
        </p>
      ) : null}

      {/* Empresa ou um item só: uma resposta. */}
      {podeResponder && !varios ? (
        <div className="mt-4 flex flex-wrap items-center gap-2 pl-7">
          {opcoes.map((o) => (
            <Button key={o.valor} variant="secundario" disabled={responder.isPending} onClick={() => responder.mutate({ id: p.id, valor: o.valor, observacao: obs || undefined })}>
              {o.rotulo ?? o.valor}
              {empresa ? <span className="text-tinta-3">para a empresa</span> : null}
            </Button>
          ))}
          <Input value={obs} onChange={(e) => setObs(e.target.value)} placeholder="Observação (opcional, fica no histórico)" className="ml-auto max-w-xs" aria-label="Observação" />
        </div>
      ) : null}

      {editando ? (
        <div className="mt-4 flex flex-wrap items-center gap-2 pl-7 text-xs text-tinta-2">
          <span>
            {corrigindo
              ? "Escolha a resposta certa de cada item. Só os itens que mudarem são reavaliados."
              : "A resposta pode variar de um produto para outro: responda cada item. Itens sem resposta continuam na pergunta."}
          </span>
          <span className="ml-auto flex flex-wrap items-center gap-1">
            Marcar todos:
            {opcoes.map((o) => (
              <Button key={o.valor} tamanho="sm" variant="fantasma" onClick={() => marcarTodos(o.valor)}>
                {o.rotulo ?? o.valor}
              </Button>
            ))}
          </span>
        </div>
      ) : null}

      {!empresa && itens.length ? (
        <ul className="mt-3 ml-7 divide-y divide-regua rounded-md border border-regua">
          {itens.map((i) => {
            const escolhida = respostas[i.id] ?? (corrigindo ? (i.resposta ?? undefined) : undefined);
            return (
              <li key={i.id} className="flex flex-wrap items-center gap-3 px-3 py-2 text-sm">
                <span className="num w-10 text-2xs text-tinta-3">{i.linha}</span>
                <span className="codigo w-20 text-2xs text-tinta-3">{i.codigo_interno}</span>
                <span className="min-w-0 flex-1 truncate">{i.descricao}</span>
                {aberta && i.sugestao ? (
                  <span className="flex items-center gap-1 text-2xs text-caneta" title={i.sugestao.evidencia}>
                    <Sparkles className="size-3" aria-hidden /> IA supõe “{rotulo(i.sugestao.valor)}”
                  </span>
                ) : null}
                {!editando && i.resposta ? <span className="text-2xs text-tinta-2">Resposta: “{rotulo(i.resposta)}”</span> : null}
                {editando ? (
                  <span className="flex gap-1">
                    {opcoes.map((o) => (
                      <Button
                        key={o.valor}
                        tamanho="sm"
                        variant={escolhida === o.valor ? "primario" : "secundario"}
                        onClick={() => setRespostas((r) => ({ ...r, [i.id]: o.valor }))}
                        aria-pressed={escolhida === o.valor}
                      >
                        {o.rotulo ?? o.valor}
                      </Button>
                    ))}
                  </span>
                ) : null}
              </li>
            );
          })}
          {faltam > 0 ? <li className="px-3 py-2 text-2xs text-tinta-3">Carregando os outros {fmtNum(faltam)} itens…</li> : null}
        </ul>
      ) : null}

      {editando ? (
        <div className="mt-3 flex flex-wrap items-center justify-end gap-2 pl-7">
          <Input value={obs} onChange={(e) => setObs(e.target.value)} placeholder="Observação (opcional, fica no histórico)" className="mr-auto max-w-xs" aria-label="Observação" />
          {corrigindo ? (
            <Button
              variant="fantasma"
              onClick={() => {
                setCorrigindo(false);
                setRespostas({});
              }}
            >
              Cancelar
            </Button>
          ) : null}
          <Button variant="primario" disabled={!nEnviar || responder.isPending} onClick={() => responder.mutate({ id: p.id, respostas_itens: enviar, observacao: obs || undefined })}>
            {corrigindo ? `Salvar ${plural(nEnviar, "correção", "correções")}` : `Enviar ${plural(nEnviar, "resposta", "respostas")} de ${fmtNum(p.total_itens)}`}
          </Button>
        </div>
      ) : null}
    </Painel>
  );
}
