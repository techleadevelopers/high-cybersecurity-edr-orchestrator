from fastapi import Header, HTTPException, status, Depends
from app.core.config import get_settings, Settings
from app.core.security import verify_token, TokenClaims
from app.core.deps import get_redis


async def get_current_claims(
    authorization: str | None = Header(default=None, convert_underscores=False),
    settings: Settings = Depends(lambda: get_settings()),
    redis=Depends(get_redis),
) -> TokenClaims:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1]
    claims = verify_token(token, settings.jwt_secret_key, [settings.jwt_algorithm])
    # Revocation check per device
    if await redis.get(f"revoked:device:{claims.device_id}"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Device revoked")
    if claims.jti and await redis.get(f"revoked:jti:{claims.jti}"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Token revoked")
    return claims


def decode_token_raw(token: str, settings: Settings) -> TokenClaims:
    return verify_token(token, settings.jwt_secret_key, [settings.jwt_algorithm])


def assert_device_access(target_device_id: str, claims: TokenClaims) -> None:
    if claims.device_id != target_device_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Token not authorized for this device")


# Backward compatibility helper
def get_current_device(
    authorization: str | None = Header(default=None, convert_underscores=False),
    settings: Settings = Depends(lambda: get_settings()),
) -> str:
    return get_current_claims(authorization=authorization, settings=settings).sub
