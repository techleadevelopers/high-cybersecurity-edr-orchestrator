import datetime as dt
import uuid
from typing import Optional
from jose import jwt, JWTError
from fastapi import HTTPException, status
from pydantic import BaseModel, ValidationError


class TokenClaims(BaseModel):
    sub: str
    device_id: str
    exp: int
    typ: str = "access"
    jti: str | None = None


def create_access_token(
    subject: str,
    device_id: str,
    secret_key: str,
    algorithm: str,
    expires_minutes: int,
) -> str:
    expire = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=expires_minutes)
    jti = str(uuid.uuid4())
    to_encode = {"sub": subject, "device_id": device_id, "exp": expire, "typ": "access", "jti": jti}
    return jwt.encode(to_encode, secret_key, algorithm=algorithm)


def create_refresh_token(
    subject: str,
    device_id: str,
    secret_key: str,
    algorithm: str,
    expires_minutes: int,
) -> tuple[str, str]:
    expire = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=expires_minutes)
    jti = str(uuid.uuid4())
    to_encode = {"sub": subject, "device_id": device_id, "exp": expire, "typ": "refresh", "jti": jti}
    return jwt.encode(to_encode, secret_key, algorithm=algorithm), jti


def verify_token(token: str, secret_key: str, algorithms: list[str]) -> TokenClaims:
    try:
        payload = jwt.decode(token, secret_key, algorithms=algorithms)
        claims = TokenClaims(**payload)
        return claims
    except (JWTError, ValidationError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token verification failed") from exc


def verify_mtls(cert: Optional[str]) -> None:
    # Placeholder for mTLS verification: in production, FastAPI would be behind a reverse proxy terminating TLS
    if cert is None:
        return
    # Implement CA validation here or rely on ingress controller configuration
    return
