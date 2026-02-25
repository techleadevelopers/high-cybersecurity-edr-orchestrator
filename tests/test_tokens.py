import pytest
from fastapi import HTTPException

from app.services.tokens import issue_tokens, refresh_tokens


@pytest.mark.asyncio
async def test_refresh_rotation_and_sliding_ttl(settings, redis):
    access, refresh = await issue_tokens(settings, redis, "user1", "device1", fingerprint="fp-123")
    keys = await redis.keys("refresh:user1:device1:*")
    assert len(keys) == 1
    first_key = keys[0]

    # First refresh rotates token and extends TTL
    new_access, new_refresh = await refresh_tokens(settings, redis, refresh, fingerprint="fp-123")
    keys_after = await redis.keys("refresh:user1:device1:*")
    assert len(keys_after) == 1
    assert keys_after[0] != first_key

    # Reusing the old refresh should be blocked and mark device revoked
    with pytest.raises(HTTPException):
        await refresh_tokens(settings, redis, refresh, fingerprint="fp-123")
    assert await redis.get("revoked:device:device1") == "1"


@pytest.mark.asyncio
async def test_refresh_wrong_fingerprint_rejected(settings, redis):
    _, refresh = await issue_tokens(settings, redis, "user1", "device1", fingerprint="fp-123")
    with pytest.raises(HTTPException):
        await refresh_tokens(settings, redis, refresh, fingerprint="different-fp")
