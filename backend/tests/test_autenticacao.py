"""Login, refresh com rotação e detecção de reuso, CSRF e força bruta."""

from __future__ import annotations

import uuid

import httpx
import pytest

from tests.conftest import dono

pytestmark = pytest.mark.usefixtures("limpo")
SENHA = "Senha-Forte-123!"


def _usuario() -> None:
    from app.core.security import hash_senha

    org, user = uuid.uuid4(), uuid.uuid4()
    with dono() as c:
        c.execute(
            "INSERT INTO organizations (id, nome, tipo, ativo, created_at) VALUES (%s, 'Org', 'empresa', true, now())",
            (org,),
        )
        c.execute(
            "INSERT INTO users (id, email, nome, password_hash, is_platform_admin, ativo, created_at) "
            "VALUES (%s, 'ana@teste.com.br', 'Ana', %s, false, true, now())",
            (user, hash_senha(SENHA)),
        )
        c.execute(
            "INSERT INTO memberships (id, org_id, user_id, papel, ativo, created_at) VALUES (%s, %s, %s, 'revisor', true, now())",
            (uuid.uuid4(), org, user),
        )
    from app.core.redis import redis_sync

    for k in redis_sync().scan_iter("login:*"):
        redis_sync().delete(k)


async def test_login_refresh_rotacao_e_reuso():
    from app.main import app

    _usuario()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://teste") as cli:
        r = await cli.post("/api/auth/login", json={"email": "ANA@teste.com.br", "senha": SENHA})
        assert r.status_code == 200, r.text
        s = r.json()
        assert s["org_atual"]["papel"] == "revisor" and "revisar" in s["permissoes"]
        rt_antigo = cli.cookies.get("rt")
        csrf = cli.cookies.get("csrf_token")
        assert rt_antigo and csrf

        # Sem o cabeçalho CSRF, o refresh é recusado.
        assert (await cli.post("/api/auth/refresh")).status_code == 403
        r2 = await cli.post("/api/auth/refresh", headers={"X-CSRF-Token": csrf})
        assert r2.status_code == 200
        assert cli.cookies.get("rt") != rt_antigo

        # Reuso do token antigo (possível roubo): a família inteira é revogada.
        cli.cookies.set("rt", rt_antigo, path="/api/auth")
        r3 = await cli.post("/api/auth/refresh", headers={"X-CSRF-Token": cli.cookies.get("csrf_token")})
        assert r3.status_code == 401
    with dono() as c:
        assert c.execute("SELECT count(*) FROM refresh_tokens WHERE revogado_em IS NULL").fetchone()[0] == 0
        assert c.execute("SELECT count(*) FROM audit_log WHERE acao = 'reuso_refresh_token'").fetchone()[0] == 1


async def test_senha_errada_e_bloqueio_por_tentativas():
    from app.main import app

    _usuario()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://teste") as cli:
        for _ in range(5):
            r = await cli.post("/api/auth/login", json={"email": "ana@teste.com.br", "senha": "errada"})
            assert r.status_code == 401
            assert r.json()["erro"]["mensagem"] == "E-mail ou senha incorretos."
        r = await cli.post("/api/auth/login", json={"email": "ana@teste.com.br", "senha": SENHA})
        assert r.status_code == 429
    with dono() as c:
        assert c.execute("SELECT count(*) FROM audit_log WHERE acao = 'login_falhou'").fetchone()[0] == 5


async def test_token_invalido_e_erros_em_portugues():
    from app.main import app

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://teste") as cli:
        r = await cli.get("/api/empresas", headers={"Authorization": "Bearer abc"})
        assert r.status_code == 401 and "sessão" in r.json()["erro"]["mensagem"].lower()
        r = await cli.get("/api/nao-existe")
        assert r.status_code == 404 and r.json()["erro"]["mensagem"] == "O endereço solicitado não existe."
        assert r.headers["x-content-type-options"] == "nosniff" and r.headers.get("x-request-id")
