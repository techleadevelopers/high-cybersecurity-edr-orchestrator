import datetime as dt
import uuid
from typing import Optional, Any

import httpx
from fastapi import HTTPException, status
from jose import jwt, JWTError
from pydantic import BaseModel, ValidationError

from app.core.config import Settings


class TokenClaims(BaseModel):
    sub: str
    device_id: str
    exp: int
    typ: str
    jti: str | None = None
    aud: str | list[str] | None = None
    iss: str | None = None
    nbf: int | None = None
    iat: int | None = None
    kid: str | None = None


class JWKSCache:
    """Very small in-process JWKS cache; relies on signed JWKS endpoint."""

    def __init__(self):
        self.cached_at: dt.datetime | None = None
        self.jwks: dict[str, Any] | None = None

    def is_fresh(self, ttl_seconds: int) -> bool:
        return self.cached_at is not None and (dt.datetime.now(dt.timezone.utc) - self.cached_at).total_seconds() < ttl_seconds

    def load(self, settings: Settings) -> dict[str, Any] | None:
        if settings.jwks_url is None:
            return None
        if self.is_fresh(settings.jwks_cache_ttl_seconds) and self.jwks:
            return self.jwks
        try:
            resp = httpx.get(settings.jwks_url, timeout=2.0)
            resp.raise_for_status()
            data = resp.json()
            if "keys" not in data:
                raise ValueError("JWKS missing keys")
            self.cached_at = dt.datetime.now(dt.timezone.utc)
            self.jwks = data
            return data
        except Exception as exc:  # pragma: no cover - defensive: fallback handled by callers
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Unable to fetch JWKS") from exc


jwks_cache = JWKSCache()


def _select_jwk(kid: str | None, settings: Settings) -> dict[str, Any]:
    # Prefer JWKS endpoint
    if settings.jwks_url:
        jwks = jwks_cache.load(settings)
        if jwks:
            for key in jwks.get("keys", []):
                if kid and key.get("kid") == kid:
                    return key
            # Allow graceful rotation: fall back to first key if kid absent/mismatched
            if not kid and jwks.get("keys"):
                return jwks["keys"][0]
            if kid:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown KID")

    # Fallbacks for development
    if settings.jwt_public_key:
        return settings.jwt_public_key
    if settings.jwt_secret_key and settings.jwt_algorithm.startswith("HS"):
        return settings.jwt_secret_key

    raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="No verification key available")


def _get_leeway(settings: Settings) -> int:
    return max(0, settings.jwt_clock_skew_seconds)


def _decode_with_jwk(token: str, jwk: dict[str, Any], settings: Settings) -> dict[str, Any]:
    options = {
        "verify_aud": settings.jwt_audience is not None,
        "verify_iss": settings.jwt_issuer is not None,
    }
    return jwt.decode(
        token,
        jwk,
        algorithms=[settings.jwt_algorithm],
        audience=settings.jwt_audience,
        issuer=settings.jwt_issuer,
        options=options,
        leeway=_get_leeway(settings),
    )


def verify_token(token: str, settings: Settings, expected_typ: str = "access") -> TokenClaims:
    """
    Verify JWT (RS/ES preferred) using JWKS; enforce aud/iss/nbf/iat and typ.
    """
    try:
        header = jwt.get_unverified_header(token)
    except JWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token header") from exc

    jwk = _select_jwk(header.get("kid"), settings)
    try:
        payload = _decode_with_jwk(token, jwk, settings)
        claims = TokenClaims(**payload, kid=header.get("kid"))
    except (JWTError, ValidationError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token verification failed") from exc

    # typ enforcement
    if claims.typ != expected_typ:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unexpected token type")

    # nbf/iat manual skew checks (python-jose handles but we double-check for ±30s rule)
    now_ts = int(dt.datetime.now(dt.timezone.utc).timestamp())
    leeway = _get_leeway(settings)
    if claims.nbf and claims.nbf - leeway > now_ts:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token not yet valid")
    if claims.iat and claims.iat - leeway > now_ts:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token issued in the future")

    return claims


def _sign_payload(payload: dict[str, Any], settings: Settings, headers: Optional[dict[str, Any]] = None) -> str:
    """
    Signs a JWT. In production this should be replaced by a KMS/HSM client; we intentionally
    support only local PEM for development/testing to avoid secret sprawl.
    """
    if settings.jwt_private_key:
        return jwt.encode(payload, settings.jwt_private_key, algorithm=settings.jwt_algorithm, headers=headers)
    if settings.jwt_secret_key and settings.jwt_algorithm.startswith("HS"):
        return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm, headers=headers)
    raise RuntimeError("No signing key configured; expected KMS/HSM signer in production")


def create_access_token(
    subject: str,
    device_id: str,
    settings: Settings,
) -> str:
    now = dt.datetime.now(dt.timezone.utc)
    expire = now + dt.timedelta(minutes=settings.jwt_expire_minutes)
    jti = str(uuid.uuid4())
    payload = {
        "sub": subject,
        "device_id": device_id,
        "exp": int(expire.timestamp()),
        "nbf": int(now.timestamp()),
        "iat": int(now.timestamp()),
        "typ": "access",
        "jti": jti,
    }
    if settings.jwt_audience:
        payload["aud"] = settings.jwt_audience
    if settings.jwt_issuer:
        payload["iss"] = settings.jwt_issuer

    headers = {"kid": settings.jwt_active_kid} if settings.jwt_active_kid else None
    return _sign_payload(payload, settings, headers=headers)


def create_refresh_token(
    subject: str,
    device_id: str,
    settings: Settings,
) -> tuple[str, str]:
    now = dt.datetime.now(dt.timezone.utc)
    expire = now + dt.timedelta(minutes=settings.refresh_base_ttl_minutes)
    jti = str(uuid.uuid4())
    payload = {
        "sub": subject,
        "device_id": device_id,
        "exp": int(expire.timestamp()),
        "nbf": int(now.timestamp()),
        "iat": int(now.timestamp()),
        "typ": "refresh",
        "jti": jti,
    }
    if settings.jwt_audience:
        payload["aud"] = settings.jwt_audience
    if settings.jwt_issuer:
        payload["iss"] = settings.jwt_issuer

    headers = {"kid": settings.jwt_active_kid} if settings.jwt_active_kid else None
    return _sign_payload(payload, settings, headers=headers), jti


def verify_mtls(cert: Optional[str]) -> None:
    # Placeholder for mTLS verification: in production, FastAPI would be behind a reverse proxy terminating TLS
    if cert is None:
        return
    # Implement CA validation here or rely on ingress controller configuration
    return
