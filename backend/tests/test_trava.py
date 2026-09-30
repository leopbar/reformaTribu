"""Trava distribuída que se renova: não expira no meio do trabalho e some logo se o processo morrer."""

from __future__ import annotations

import time
import uuid

import pytest


def test_trava_se_renova_e_libera(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import redis as r

    monkeypatch.setattr(r, "TRAVA_VALIDADE_S", 1.5)
    nome = f"trava:teste:{uuid.uuid4()}"
    with r.trava_viva(nome, espera_s=1) as obtida:
        assert obtida
        time.sleep(3)  # o dobro da validade: sem renovação, a trava já teria expirado
        assert r.redis_sync().exists(nome)
        with r.trava_viva(nome, espera_s=0.2) as segunda:
            assert not segunda  # outro processo espera e segue sem a trava, como antes
    assert not r.redis_sync().exists(nome)


def test_trava_de_processo_morto_expira_sozinha(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import redis as r

    nome = f"trava:teste:{uuid.uuid4()}"
    # Um processo que morreu deixa a trava sem renovação: ela expira pela validade curta.
    r.redis_sync().lock(nome, timeout=1).acquire()
    with r.trava_viva(nome, espera_s=5) as obtida:
        assert obtida
