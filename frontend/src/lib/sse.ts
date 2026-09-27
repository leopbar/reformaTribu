/**
 * Server-Sent Events via fetch (o EventSource nativo não permite o cabeçalho Authorization).
 * Reconecta automaticamente com espera crescente.
 */
export interface EventoSSE {
  event: string;
  data: string;
}

export function assinarSSE(
  url: string,
  obterToken: () => Promise<string | null>,
  aoEvento: (e: EventoSSE) => void,
): () => void {
  let ativo = true;
  let controle: AbortController | null = null;
  let espera = 1000;

  const conectar = async () => {
    while (ativo) {
      controle = new AbortController();
      try {
        const token = await obterToken();
        const resp = await fetch(url, {
          headers: { Accept: "text/event-stream", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
          signal: controle.signal,
          credentials: "same-origin",
        });
        if (!resp.ok || !resp.body) throw new Error(`SSE ${resp.status}`);
        espera = 1000;
        const leitor = resp.body.pipeThrough(new TextDecoderStream()).getReader();
        let buffer = "";
        while (ativo) {
          const { value, done } = await leitor.read();
          if (done) break;
          buffer += value;
          let fim: number;
          while ((fim = buffer.search(/\r?\n\r?\n/)) >= 0) {
            const bloco = buffer.slice(0, fim);
            buffer = buffer.slice(fim).replace(/^\r?\n\r?\n/, "");
            let event = "message";
            const dados: string[] = [];
            for (const linha of bloco.split(/\r?\n/)) {
              if (linha.startsWith("event:")) event = linha.slice(6).trim();
              else if (linha.startsWith("data:")) dados.push(linha.slice(5).trimStart());
            }
            if (dados.length) aoEvento({ event, data: dados.join("\n") });
          }
        }
      } catch {
        if (!ativo) return;
      }
      if (!ativo) return;
      await new Promise((r) => setTimeout(r, espera));
      espera = Math.min(espera * 2, 15000);
    }
  };
  void conectar();
  return () => {
    ativo = false;
    controle?.abort();
  };
}
