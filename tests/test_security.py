import datetime as dt

import pytest
from fastapi import HTTPException
from jose import jwt

from app.core.security import create_access_token, verify_token


@pytest.mark.asyncio
async def test_access_token_roundtrip(settings):
    token = create_access_token("user123", "deviceA", settings)
    claims = verify_token(token, settings, expected_typ="access")
    assert claims.sub == "user123"
    assert claims.device_id == "deviceA"
    assert claims.typ == "access"
    assert claims.aud == settings.jwt_audience
    assert claims.iss == settings.jwt_issuer


def test_typ_enforced(settings):
    token = create_access_token("user123", "deviceA", settings)
    with pytest.raises(HTTPException):
        verify_token(token, settings, expected_typ="refresh")


def test_future_iat_rejected(settings):
    now = dt.datetime.now(dt.timezone.utc)
    payload = {
        "sub": "u",
        "device_id": "d",
        "typ": "access",
        "jti": "123",
        "exp": int((now + dt.timedelta(minutes=5)).timestamp()),
        "iat": int((now + dt.timedelta(seconds=settings.jwt_clock_skew_seconds + 10)).timestamp()),
        "nbf": int(now.timestamp()),
        "aud": settings.jwt_audience,
        "iss": settings.jwt_issuer,
    }
    token = jwt.encode(payload, settings.jwt_private_key, algorithm=settings.jwt_algorithm, headers={"kid": settings.jwt_active_kid})
    with pytest.raises(HTTPException):
        verify_token(token, settings, expected_typ="access")
