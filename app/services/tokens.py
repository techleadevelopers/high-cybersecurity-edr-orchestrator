import datetime as dt
import hashlib
import hmac
import uuid
from fastapi import HTTPException, status
from redis.asyncio import Redis

from app.core.security import (
    create_access_token,
    create_refresh_token,
    TokenClaims,
    verify_token,
)
from app.core.config import Settings


def _refresh_key(user_id: str, device_id: str, jti: str, fp_hash: str) -> str:
    return f"refresh:{user_id}:{device_id}:{jti}:{fp_hash}"


def _hash_fp(fingerprint: str, secret: str) -> str:
    return hmac.new(secret.encode(), fingerprint.encode(), hashlib.sha256).hexdigest()


async def _enforce_device_refresh_rate(redis: Redis, device_id: str, window: int = 60, max_attempts: int = 10):
    key = f"refresh_attempts:{device_id}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, window)
    if count > max_attempts:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many refresh attempts")


async def issue_tokens(settings: Settings, redis: Redis, user_id: str, device_id: str, fingerprint: str) -> tuple[str, str]:
    if not settings.refresh_fingerprint_secret:
        raise RuntimeError("REFRESH_FINGERPRINT_SECRET missing")
    fp_hash = _hash_fp(fingerprint, settings.refresh_fingerprint_secret)

    access = create_access_token(user_id, device_id, settings)
    refresh, jti = create_refresh_token(user_id, device_id, settings)
    ttl_seconds = settings.refresh_base_ttl_minutes * 60
    await redis.set(_refresh_key(user_id, device_id, jti, fp_hash), "1", ex=ttl_seconds)
    return access, refresh


async def refresh_tokens(settings: Settings, redis: Redis, refresh_token: str, fingerprint: str) -> tuple[str, str]:
    if not settings.refresh_fingerprint_secret:
        raise RuntimeError("REFRESH_FINGERPRINT_SECRET missing")
    claims = verify_token(refresh_token, settings, expected_typ="refresh")
    fp_hash = _hash_fp(fingerprint, settings.refresh_fingerprint_secret)

    # Rate limit per device_id now that we know it
    await _enforce_device_refresh_rate(redis, claims.device_id)

    key = _refresh_key(claims.sub, claims.device_id, claims.jti, fp_hash)
    ttl_seconds = await redis.ttl(key)
    if ttl_seconds == -2:
        # Reuse / revoked
        await redis.set(f"revoked:device:{claims.device_id}", "1", ex=3600)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Refresh token reused or revoked")

    # Rotate on use: delete old key to prevent replay
    await redis.delete(key)

    # Compute sliding TTL (base + extend, capped)
    base_ttl = settings.refresh_base_ttl_minutes * 60
    extend = settings.refresh_extend_minutes * 60
    max_ttl = settings.refresh_max_ttl_minutes * 60
    existing = ttl_seconds if ttl_seconds and ttl_seconds > 0 else base_ttl
    new_session_ttl = min(max_ttl, max(base_ttl, existing + extend))

    new_access = create_access_token(claims.sub, claims.device_id, settings)
    new_refresh, new_jti = create_refresh_token(claims.sub, claims.device_id, settings)
    await redis.set(_refresh_key(claims.sub, claims.device_id, new_jti, fp_hash), "1", ex=new_session_ttl)
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


async def revoke_and_block(redis: Redis, user_id: str, device_id: str, publish_block: bool = False):
    await revoke_device_tokens(redis, user_id, device_id)
    if publish_block:
        await redis.publish("kill-switch", f"block:{device_id}:logout")
    await redis.set(f"device:{device_id}:state", "blocked", ex=3600)
    await redis.set(f"revoked:device:{device_id}", "1", ex=3600)
    await redis.set(f"force_overlay:{device_id}", "1", ex=3600)
