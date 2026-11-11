"""Redis cache client – thin wrapper around redis.asyncio."""

from __future__ import annotations

from collections.abc import AsyncGenerator

import redis.asyncio as aioredis
from redis.asyncio import Redis

from app.config import get_settings

settings = get_settings()

_pool: aioredis.ConnectionPool | None = None


def _get_pool() -> aioredis.ConnectionPool:
    global _pool
    if _pool is None:
        _pool = aioredis.ConnectionPool.from_url(
            settings.redis_url,
            max_connections=20,
            decode_responses=True,
        )
    return _pool


async def get_redis() -> AsyncGenerator[Redis, None]:
    """FastAPI dependency – yields a Redis connection from the pool."""
    client: Redis = aioredis.Redis(connection_pool=_get_pool())
    try:
        yield client
    finally:
        await client.aclose()


async def close_redis_pool() -> None:
    """Call on application shutdown to release all connections."""
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None


def redis_client() -> Redis:
    """Short-lived client sharing the application pool; use as an async context manager."""
    return aioredis.Redis(connection_pool=_get_pool())
