"""Exercita o fluxo de entrada de dados com as planilhas de exemplo, via API (sem IA).

    uv run --project backend python infra/scripts/fluxo_amostras.py <email> <senha> [--api http://localhost:8100]

Para cada planilha: envia, aceita o mapeamento sugerido, cria a auditoria, espera a prévia e
imprime o resumo dos problemas e a estimativa de custo. Não inicia a análise por IA.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import httpx

AMOSTRAS = Path(__file__).resolve().parents[2] / "data" / "samples"
PLANILHAS = {
    "supermercado_ficticio.xlsx": "Supermercado Fictício Bom Preço Ltda",
    "padaria_ficticia.csv": "Padaria Fictícia Pão Dourado Ltda",
    "farmacia_ficticia.xlsx": "Farmácia Fictícia Saúde Total Ltda",
    "servicos_ficticios.xlsx": "Consultoria Fictícia Exata Ltda",
}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("email")
    p.add_argument("senha")
    p.add_argument("--api", default="http://localhost:8100")
    a = p.parse_args()
    c = httpx.Client(base_url=a.api, timeout=120)
    r = c.post("/api/auth/login", json={"email": a.email, "senha": a.senha})
    r.raise_for_status()
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    empresas = {e["razao_social"]: e["id"] for e in c.get("/api/empresas").json()}
    ids = []
    for arquivo, empresa in PLANILHAS.items():
        with (AMOSTRAS / arquivo).open("rb") as f:
            up = c.post("/api/uploads", files={"arquivo": (arquivo, f)}, data={"company_id": empresas[empresa]})
        up.raise_for_status()
        u = up.json()
        mapa = u["mapeamento_sugerido"]
        print(f"\n== {arquivo}: {u['total_linhas']} linhas, cabeçalho na linha {u['linha_cabecalho'] + 1}, "
              f"formato {u['formato']} {u.get('encoding') or ''}")
        print("   mapeamento detectado:", {k: v for k, v in mapa.items() if v})
        aud = c.post("/api/auditorias", json={
            "company_id": empresas[empresa], "arquivo_id": u["arquivo_id"], "nome": f"Exemplo — {arquivo}",
            "mapeamento": mapa, "contexto_operacao": {},
        })
        if aud.status_code >= 400:
            print("   ERRO:", aud.json())
            continue
        ids.append((arquivo, aud.json()["id"]))
    for arquivo, aid in ids:
        for _ in range(60):
            d = c.get(f"/api/auditorias/{aid}").json()
            if d["status"] != "preparando":
                break
            time.sleep(2)
        pr = d["problemas_resumo"]
        est = d["estimativa"]
        print(f"\n== {arquivo}: status {d['status']}; {pr.get('itens_validos')} itens válidos, "
              f"{pr.get('com_problemas')} com problemas")
        for k, n in (pr.get("por_problema") or {}).items():
            print(f"   {n:>4}  {k}")
        rec = est.get("modo_recomendado")
        e = est.get(rec, {})
        print(f"   estimativa ({rec}): US$ {e.get('custo_usd_estimado')} — {e.get('tempo_texto')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
