from collections.abc import AsyncGenerator
import contextlib
from redis import asyncio as aioredis
from redis.asyncio import ConnectionPool, Redis
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings, Settings
from app.db.session import async_session

_redis_pool: ConnectionPool | None = None


async def get_settings_dep() -> Settings:
    return get_settings()


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session


def _ensure_redis_pool(url: str) -> ConnectionPool:
    global _redis_pool
    settings = get_settings()
    if not url.startswith("rediss://") and settings.environment != "development":
        raise RuntimeError("Redis URL must use TLS (rediss://) for production safety")
    if _redis_pool is None:
        _redis_pool = ConnectionPool.from_url(
            url,
            max_connections=64,
            decode_responses=True,
            socket_timeout=1.0,
            socket_connect_timeout=1.0,
            health_check_interval=30,
        )
    return _redis_pool


async def get_redis(settings: Settings = Depends(get_settings_dep)):
    pool = _ensure_redis_pool(settings.redis_url)
    client: Redis = aioredis.Redis(connection_pool=pool)
    try:
        yield client
    finally:
        # do not close the pool; just disconnect this client object
        await client.aclose()
