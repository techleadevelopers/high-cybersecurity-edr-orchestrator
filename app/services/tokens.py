import datetime as dt
import uuid
from fastapi import HTTPException
from redis.asyncio import Redis
from app.core.security import create_access_token, create_refresh_token, TokenClaims, verify_token
from app.core.config import Settings

REFRESH_TTL_MINUTES = 60 * 24 * 7  # 7 days


def _refresh_key(user_id: str, device_id: str, jti: str) -> str:
    return f"refresh:{user_id}:{device_id}:{jti}"


async def issue_tokens(settings: Settings, redis: Redis, user_id: str, device_id: str) -> tuple[str, str]:
    access = create_access_token(user_id, device_id, settings.jwt_secret_key, settings.jwt_algorithm, settings.jwt_expire_minutes)
    refresh, jti = create_refresh_token(user_id, device_id, settings.jwt_secret_key, settings.jwt_algorithm, REFRESH_TTL_MINUTES)
    await redis.set(_refresh_key(user_id, device_id, jti), "1", ex=REFRESH_TTL_MINUTES * 60)
    return access, refresh


async def refresh_tokens(settings: Settings, redis: Redis, refresh_token: str) -> tuple[str, str]:
    claims = verify_token(refresh_token, settings.jwt_secret_key, [settings.jwt_algorithm])
    if claims.typ != "refresh" or not claims.jti:
        raise HTTPException(status_code=403, detail="Invalid refresh token")
    key = _refresh_key(claims.sub, claims.device_id, claims.jti)
    exists = await redis.exists(key)
    if not exists:
        raise HTTPException(status_code=403, detail="Refresh token revoked")
    # rotate
    await redis.delete(key)
    new_access, new_refresh = await issue_tokens(settings, redis, claims.sub, claims.device_id)
    return new_access, new_refresh


async def revoke_device_tokens(redis: Redis, user_id: str, device_id: str):
    pattern = f"refresh:{user_id}:{device_id}:*"
    cursor = 0
    while True:
        cursor, keys = await redis.scan(cursor=cursor, match=pattern, count=100)
        if keys:
            await redis.delete(*keys)
        if cursor == 0:
            break
