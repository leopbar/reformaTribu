"""Clientes Redis (assíncrono para a API, síncrono para os workers)."""

from __future__ import annotations

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
