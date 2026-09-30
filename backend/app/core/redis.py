"""Clientes Redis (assíncrono para a API, síncrono para os workers)."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from functools import lru_cache

import redis
import redis.asyncio as aredis

from app.config import get_settings


@lru_cache
def redis_async() -> aredis.Redis:
    return aredis.from_url(get_settings().redis_url, decode_responses=True)


@lru_cache
def redis_sync() -> redis.Redis:
    return redis.from_url(get_settings().redis_url, decode_responses=True)


# Validade curta, renovada enquanto o trabalho dura: se o processo morrer (ex.: worker reiniciado no meio de
# uma chamada de IA), a trava some em até um minuto, em vez de segurar a fila por 10–15 minutos.
TRAVA_VALIDADE_S = 60


@contextmanager
def trava_viva(nome: str, espera_s: float) -> Iterator[bool]:
    """Trava distribuída que se renova sozinha enquanto o bloco roda. Devolve se a trava foi obtida
    (depois de `espera_s` sem conseguir, o bloco roda assim mesmo, como antes)."""
    trava = redis_sync().lock(nome, timeout=TRAVA_VALIDADE_S, blocking_timeout=espera_s, thread_local=False)
    obtida = bool(trava.acquire())
    parar = threading.Event()

    def renovar() -> None:
        while not parar.wait(TRAVA_VALIDADE_S / 3):
            try:
                trava.reacquire()
            except Exception:
                return

    if obtida:
        threading.Thread(target=renovar, daemon=True, name=f"renova:{nome[:40]}").start()
    try:
        yield obtida
    finally:
        parar.set()
        if obtida:
            with suppress(Exception):
                trava.release()
