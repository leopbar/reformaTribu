"""Prova de isolamento entre organizações: Row-Level Security no PostgreSQL + filtros na API.

Os dados são criados como dono do schema (fora da RLS) e lidos com o papel da aplicação.
"""

from __future__ import annotations

import uuid

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from tests.conftest import dono

pytestmark = pytest.mark.usefixtures("limpo")


def _criar_cenario() -> dict[str, uuid.UUID]:
    ids = {k: uuid.uuid4() for k in ("org_a", "org_b", "user_a", "user_b", "emp_a", "emp_b", "aud_b", "item_b")}
    with dono() as c:
        for org, nome in (("org_a", "Escritório A"), ("org_b", "Escritório B")):
            c.execute(
                "INSERT INTO organizations (id, nome, tipo, ativo, created_at) VALUES (%s, %s, 'escritorio_contabil', true, now())",
                (ids[org], nome),
            )
            c.execute(
                "INSERT INTO org_settings (org_id, limiar_confirmado, limiar_corrigido, limiar_escalonamento, "
                "usar_modelo_leve, alerta_orcamento_pct, imposto_seletivo_exige_analise, retencao_arquivos_dias, "
                "extras, updated_at) VALUES (%s, 0.9, 0.85, 0.8, false, 80, true, 30, '{}', now())",
                (ids[org],),
            )
        for user, org, email in (("user_a", "org_a", "a@a.com.br"), ("user_b", "org_b", "b@b.com.br")):
            c.execute(
                "INSERT INTO users (id, email, nome, password_hash, is_platform_admin, ativo, created_at) "
                "VALUES (%s, %s, %s, 'x', false, true, now())",
                (ids[user], email, email),
            )
            c.execute(
                "INSERT INTO memberships (id, org_id, user_id, papel, ativo, created_at) VALUES (%s, %s, %s, "
                "'administrador', true, now())",
                (uuid.uuid4(), ids[org], ids[user]),
            )
        for emp, org, cnpj in (("emp_a", "org_a", "11222333000181"), ("emp_b", "org_b", "22333444000181")):
            c.execute(
                "INSERT INTO companies (id, org_id, razao_social, cnpj, regime_tributario, uf, atributos, ativo, "
                "created_at) VALUES (%s, %s, %s, %s, 'lucro_real', 'SP', '{}', true, now())",
                (ids[emp], ids[org], f"Empresa {emp}", cnpj),
            )
        c.execute(
            "INSERT INTO audits (id, org_id, company_id, nome, mapeamento, status, data_referencia, "
            "contexto_operacao, total_itens, contadores, problemas_resumo, estimativa, custo_usd, tokens, "
            "configuracao, created_at, updated_at) VALUES (%s, %s, %s, 'Auditoria B', '{}', 'concluida', "
            "current_date, '{}', 1, '{}', '{}', '{}', 0, '{}', '{}', now(), now())",
            (ids["aud_b"], ids["org_b"], ids["emp_b"]),
        )
        c.execute(
            "INSERT INTO audit_items (id, org_id, audit_id, company_id, linha, codigo_interno, "
            "codigo_interno_gerado, descricao, problemas, ignorado, tentativa, status, motivos, perguntas, "
            "regras_consideradas, imposto_seletivo, confianca_componentes, atributos, julgamento, escalonamento, "
            "estrutura, custo_usd, revisao_status, updated_at) VALUES (%s, %s, %s, %s, 2, 'X1', false, "
            "'SEGREDO DO CLIENTE B', '[]', false, 1, 'confirmado', '{}', '[]', '[]', false, '{}', '{}', '{}', "
            "'{}', '{}', 0, 'pendente', now())",
            (ids["item_b"], ids["org_b"], ids["aud_b"], ids["emp_b"]),
        )
        for org in ("org_a", "org_b"):
            c.execute(
                "INSERT INTO audit_log (org_id, acao, detalhes, created_at) VALUES (%s, 'login', '{}', now())",
                (ids[org],),
            )
    return ids


def test_rls_isola_leitura_e_escrita():
    from app.db.session import TenantContext, sync_tenant_session
    from app.models import AuditItem, AuditLog, Company

    ids = _criar_cenario()
    ctx_a = TenantContext(org_id=ids["org_a"], user_id=ids["user_a"])

    with sync_tenant_session(ctx_a) as s:
        assert {c.id for c in s.scalars(select(Company))} == {ids["emp_a"]}
        assert s.get(Company, ids["emp_b"]) is None
        assert list(s.scalars(select(AuditItem))) == []
        assert {log.org_id for log in s.scalars(select(AuditLog))} == {ids["org_a"]}
        # SQL direto, sem filtro da aplicação: a RLS continua valendo.
        assert s.execute(text("SELECT count(*) FROM audit_items")).scalar() == 0
        assert s.execute(text("SELECT count(*) FROM companies")).scalar() == 1

    # Escrita em nome de outra organização é recusada pelo banco.
    with pytest.raises((ProgrammingError, DBAPIError)), sync_tenant_session(ctx_a) as s:
        s.add(
            Company(
                org_id=ids["org_b"],
                razao_social="Invasora",
                cnpj="33444555000181",
                regime_tributario="mei",
                uf="SP",
                atributos={},
            )
        )
        s.flush()

    # Atualização em massa sem filtro não alcança linhas de outro tenant.
    with sync_tenant_session(ctx_a) as s:
        n = s.execute(text("UPDATE audit_items SET descricao = 'alterado'")).rowcount
        assert n == 0
    with dono() as c:
        assert c.execute("SELECT descricao FROM audit_items").fetchone()[0] == "SEGREDO DO CLIENTE B"

    # Sem contexto de tenant, nada é visível.
    with sync_tenant_session(None) as s:
        assert s.execute(text("SELECT count(*) FROM companies")).scalar() == 0


def test_log_de_auditoria_e_imutavel():
    from app.db.session import TenantContext, sync_tenant_session

    ids = _criar_cenario()
    with pytest.raises((ProgrammingError, DBAPIError)), sync_tenant_session(TenantContext(org_id=ids["org_a"])) as s:
        s.execute(text("UPDATE audit_log SET acao = 'adulterado'"))
    with pytest.raises((ProgrammingError, DBAPIError)), sync_tenant_session(TenantContext(org_id=ids["org_a"])) as s:
        s.execute(text("DELETE FROM audit_log"))
    with dono() as c:
        hashes = c.execute("SELECT hash, hash_anterior FROM audit_log ORDER BY id").fetchall()
    assert all(h[0] for h in hashes)
    assert hashes[1][1] == hashes[0][0]  # cadeia de hash


async def test_api_nao_expoe_dados_de_outra_organizacao():
    from app.core.security import AccessClaims, criar_access_token
    from app.main import app

    ids = _criar_cenario()
    token, _ = criar_access_token(
        AccessClaims(
            user_id=ids["user_a"], org_id=ids["org_a"], papel="administrador", platform_admin=False, email="a@a.com.br"
        )
    )
    h = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://teste") as cli:
        r = await cli.get("/api/empresas", headers=h)
        assert r.status_code == 200
        assert [e["id"] for e in r.json()] == [str(ids["emp_a"])]
        assert (await cli.get(f"/api/empresas/{ids['emp_b']}", headers=h)).status_code == 404
        assert (await cli.get(f"/api/auditorias/{ids['aud_b']}", headers=h)).status_code == 404
        assert (await cli.get(f"/api/itens/{ids['item_b']}", headers=h)).status_code == 404
        assert (await cli.post(f"/api/itens/{ids['item_b']}/aprovar", headers=h, json={})).status_code == 404
        assert (await cli.get(f"/api/auditorias/{ids['aud_b']}/itens", headers=h)).status_code == 404
        # Token forjado para a organização B com o mesmo segredo? A troca exige vínculo.
        r = await cli.post("/api/auth/trocar-organizacao", headers=h, json={"org_id": str(ids["org_b"])})
        assert r.status_code == 403


async def test_sem_token_e_papel_leitura():
    from app.core.security import AccessClaims, criar_access_token
    from app.main import app

    ids = _criar_cenario()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://teste") as cli:
        assert (await cli.get("/api/empresas")).status_code == 401
        token, _ = criar_access_token(
            AccessClaims(
                user_id=ids["user_a"], org_id=ids["org_a"], papel="leitura", platform_admin=False, email="a@a.com.br"
            )
        )
        h = {"Authorization": f"Bearer {token}"}
        # Leitura sem empresas liberadas não vê nenhuma empresa e não pode aprovar.
        assert (await cli.get("/api/empresas", headers=h)).json() == []
        r = await cli.post(
            "/api/empresas",
            headers=h,
            json={"razao_social": "X", "cnpj": "11222333000181", "regime_tributario": "mei", "uf": "SP"},
        )
        assert r.status_code == 403
