"""Comandos de administração: `python -m app.cli <comando>`.

migrate                      Aplica as migrações e prepara as tabelas de checkpoint do LangGraph.
bootstrap-admin              Cria o primeiro superadministrador (senha temporária exibida uma vez).
seed-reference [--fonte X]   Importa as fontes oficiais (download, com fallback para data/reference/raw).
seed-dicionario              Carrega o dicionário global de abreviações.
indexar-embeddings           Gera embeddings pendentes (síncrono).
seed-demo                    Cria organização, empresas e usuários de demonstração (ambiente local).
mermaid                      Imprime o diagrama do grafo de auditoria.
"""

from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import select, text

from app.config import get_settings

RAIZ = Path(__file__).resolve().parents[1]
DADOS_REF = Path(os.environ.get("REFERENCE_RAW_DIR", "/data/reference/raw"))


def migrate() -> None:
    import psycopg

    s = get_settings()
    url = s.migrations_database_url
    if not url:
        sys.exit("Defina MIGRATIONS_DATABASE_URL.")
    env = {**os.environ, "MIGRATIONS_DATABASE_URL": url}
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=RAIZ, env=env, check=True)
    from langgraph.checkpoint.postgres import PostgresSaver

    dsn = url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(dsn, autocommit=True) as conn:
        PostgresSaver(conn).setup()  # type: ignore[arg-type]
        conn.execute(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON checkpoints, checkpoint_blobs, checkpoint_writes, "
            "checkpoint_migrations TO reforma_app"
        )
    ajustar_dimensao_embeddings(dsn, s.embeddings_dim, s.embeddings_modelo)
    print("Migrações aplicadas.")


def ajustar_dimensao_embeddings(dsn: str, dim: int, modelo: str) -> None:
    """Alinha a coluna vector à dimensão do modelo configurado. Troca de modelo = reindexação."""
    import psycopg

    with psycopg.connect(dsn, autocommit=True) as conn:
        atual = conn.execute(
            "SELECT atttypmod FROM pg_attribute WHERE attrelid = 'ncm_nodes'::regclass AND attname = 'embedding'"
        ).fetchone()
        modelos = {
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT embeddings_modelo FROM ref_versions WHERE embeddings_modelo IS NOT NULL"
            )
        }
        if atual and atual[0] == dim and modelos <= {modelo}:
            return
        print(f"Ajustando embeddings para {modelo} ({dim} dimensões); os vetores serão regenerados.")
        for t in ("ncm_nodes", "nbs_nodes"):
            conn.execute(f"DROP INDEX IF EXISTS ix_{t}_embedding")
            conn.execute(f"ALTER TABLE {t} ALTER COLUMN embedding TYPE vector({dim}) USING NULL")
            conn.execute(f"CREATE INDEX ix_{t}_embedding ON {t} USING hnsw (embedding vector_cosine_ops) WHERE folha")
        conn.execute(
            "UPDATE ref_versions SET embeddings_status = 'pendente', embeddings_modelo = NULL "
            "WHERE fonte IN ('ncm', 'nbs') AND status = 'ativa'"
        )


def bootstrap_admin(email: str, nome: str) -> None:
    from app.api.orgs import gerar_senha_temporaria
    from app.core.security import hash_senha
    from app.db.session import TenantContext, sync_tenant_session
    from app.models import User

    with sync_tenant_session(TenantContext(org_id=None, platform_admin=True)) as s:
        existente = s.scalar(text("SELECT sys_usuario_por_email(:e)"), {"e": email.lower()})
        if existente:
            u = s.get(User, existente)
            assert u is not None
            u.is_platform_admin = True
            print(f"Usuário {email} já existia e agora é superadministrador.")
            return
        senha = gerar_senha_temporaria()
        s.add(User(email=email.lower(), nome=nome, password_hash=hash_senha(senha), is_platform_admin=True))
    print(f"Superadministrador criado: {email}\nSenha temporária (anote; não será exibida de novo): {senha}")


def seed_dicionario() -> None:
    from app.db.session import TenantContext, sync_reference_admin_session
    from app.models import Abbreviation

    arq = Path(__file__).with_name("seeds") / "abreviacoes.csv"
    with (
        sync_reference_admin_session(TenantContext(org_id=None, platform_admin=True)) as s,
        arq.open(encoding="utf-8") as f,
    ):
        existentes = set(s.scalars(select(Abbreviation.abreviacao).where(Abbreviation.org_id.is_(None))))
        n = 0
        for linha in csv.DictReader(f, delimiter=";"):
            if linha["abreviacao"] not in existentes:
                s.add(Abbreviation(org_id=None, abreviacao=linha["abreviacao"], expansao=linha["expansao"]))
                n += 1
    print(f"{n} abreviações globais adicionadas.")


ARQUIVOS_LOCAIS = {
    "ncm": ["ncm.json"],
    "nbs": ["nbs.csv"],
    "cclasstrib": ["cclasstrib.html", "cclasstrib.json"],
    "lc214": ["lc214.htm", "lc214.html"],
}


def seed_reference(fontes: list[str]) -> None:
    from app.reference import service
    from app.storage import files

    service.garantir_catalogo_base()
    for fonte in fontes:
        try:
            r = service.importar(fonte)
            print(f"[{fonte}] {'nova versão importada' if r['criada'] else 'já estava atualizada'} (download).")
            continue
        except Exception as e:
            print(f"[{fonte}] download indisponível: {str(e)[:200]}")
        local = next((DADOS_REF / n for n in ARQUIVOS_LOCAIS[fonte] if (DADOS_REF / n).exists()), None)
        if local is None:
            print(
                f"[{fonte}] PENDENTE: coloque o arquivo em {DADOS_REF}/ ({', '.join(ARQUIVOS_LOCAIS[fonte])}) ou "
                f"envie pela tela Base de referência. Onde obter: {service.INSTRUCOES_UPLOAD[fonte]}"
            )
            continue
        rel = files.salvar(f"referencia/_uploads/{fonte}", local.read_bytes(), local.suffix.lstrip("."))
        r = service.importar(fonte, arquivo_rel=rel, nome_arquivo=local.name)
        print(f"[{fonte}] {'nova versão importada' if r['criada'] else 'já estava atualizada'} (arquivo local).")


def indexar() -> None:
    from app.reference import embed_index

    for v in embed_index.versoes_pendentes():
        print(f"Indexando versão {v} ...")
        print(f"  {embed_index.indexar_versao(v)} embeddings gerados.")


def seed_demo() -> None:
    from app.api.orgs import gerar_senha_temporaria
    from app.core.security import hash_senha
    from app.db.session import TenantContext, sync_tenant_session
    from app.models import Company, Membership, Organization, OrgSettings, User

    if get_settings().em_producao:
        sys.exit("seed-demo não pode ser executado em produção.")
    with sync_tenant_session(TenantContext(org_id=None, platform_admin=True)) as s:
        org = s.scalar(select(Organization).where(Organization.nome == "Escritório Demonstração Contábil"))
        if org is None:
            org = Organization(nome="Escritório Demonstração Contábil", tipo="escritorio_contabil")
            s.add(org)
            s.flush()
        org_id = org.id
    senhas: dict[str, str] = {}
    with sync_tenant_session(TenantContext(org_id=org_id, platform_admin=True)) as s:
        if s.get(OrgSettings, org_id) is None:
            s.add(OrgSettings(org_id=org_id))
        # CNPJs fictícios com dígitos verificadores válidos.
        empresas = [
            (
                "Supermercado Fictício Bom Preço Ltda",
                "11222333000181",
                "lucro_presumido",
                "SP",
                "Comércio varejista de mercadorias em geral",
            ),
            ("Padaria Fictícia Pão Dourado Ltda", "22333444000181", "simples_nacional", "MG", "Padaria e confeitaria"),
            (
                "Farmácia Fictícia Saúde Total Ltda",
                "33444555000181",
                "lucro_real",
                "RJ",
                "Comércio varejista de produtos farmacêuticos",
            ),
            (
                "Consultoria Fictícia Exata Ltda",
                "44555666000181",
                "lucro_presumido",
                "PR",
                "Atividades de consultoria em gestão",
            ),
        ]
        for razao, cnpj, regime, uf, ativ in empresas:
            if s.scalar(select(Company).where(Company.cnpj == cnpj)) is None:
                s.add(
                    Company(
                        org_id=org_id,
                        razao_social=razao,
                        cnpj=cnpj,
                        regime_tributario=regime,
                        uf=uf,
                        atividade_principal=ativ,
                    )
                )
        for email, nome, papel in [
            ("admin@demo.exemplo.com.br", "Administradora Demo", "administrador"),
            ("revisor@demo.exemplo.com.br", "Revisor Demo", "revisor"),
            ("operador@demo.exemplo.com.br", "Operadora Demo", "operador"),
        ]:
            uid = s.scalar(text("SELECT sys_usuario_por_email(:e)"), {"e": email})
            if uid is None:
                senha = gerar_senha_temporaria()
                u = User(email=email, nome=nome, password_hash=hash_senha(senha))
                s.add(u)
                s.flush()
                uid = u.id
                senhas[email] = senha
            if s.scalar(select(Membership).where(Membership.user_id == uid, Membership.org_id == org_id)) is None:
                s.add(Membership(org_id=org_id, user_id=uid, papel=papel))
    print("Organização de demonstração pronta: Escritório Demonstração Contábil (dados fictícios).")
    for e, p in senhas.items():
        print(f"  {e}  senha temporária: {p}")
    if not senhas:
        print("  Usuários já existiam (senhas não são exibidas novamente).")


def main() -> None:
    p = argparse.ArgumentParser(prog="app.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate")
    b = sub.add_parser("bootstrap-admin")
    b.add_argument("--email", default=os.environ.get("BOOTSTRAP_ADMIN_EMAIL"))
    b.add_argument("--nome", default=os.environ.get("BOOTSTRAP_ADMIN_NAME", "Administrador da Plataforma"))
    r = sub.add_parser("seed-reference")
    r.add_argument("--fonte", action="append", choices=["cclasstrib", "lc214", "ncm", "nbs"])
    sub.add_parser("seed-dicionario")
    sub.add_parser("indexar-embeddings")
    sub.add_parser("seed-demo")
    sub.add_parser("mermaid")
    a = p.parse_args()
    if a.cmd == "migrate":
        migrate()
    elif a.cmd == "bootstrap-admin":
        if not a.email:
            sys.exit("Informe --email ou defina BOOTSTRAP_ADMIN_EMAIL.")
        bootstrap_admin(a.email, a.nome)
    elif a.cmd == "seed-reference":
        seed_reference(a.fonte or ["ncm", "nbs", "cclasstrib", "lc214"])
    elif a.cmd == "seed-dicionario":
        seed_dicionario()
    elif a.cmd == "indexar-embeddings":
        indexar()
    elif a.cmd == "seed-demo":
        seed_demo()
    elif a.cmd == "mermaid":
        from app.pipeline.graph import mermaid

        print(mermaid())


if __name__ == "__main__":
    main()
