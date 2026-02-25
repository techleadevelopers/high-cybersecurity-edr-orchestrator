from fastapi import APIRouter, Depends
from fastapi import HTTPException
from pydantic import BaseModel
from app.core.deps import get_settings_dep, get_redis
from app.core.config import Settings
from app.services.tokens import refresh_tokens, revoke_and_block
from app.core.auth import get_current_claims, assert_device_access

router = APIRouter()


class RefreshIn(BaseModel):
    refresh_token: str
    fingerprint: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str


class LogoutIn(BaseModel):
    device_id: str
    block: bool = False


@router.post("/refresh", response_model=TokenPair)
async def refresh(payload: RefreshIn, settings: Settings = Depends(get_settings_dep), redis=Depends(get_redis)):
    access, refresh_tok = await refresh_tokens(settings, redis, payload.refresh_token, payload.fingerprint)
    return TokenPair(access_token=access, refresh_token=refresh_tok)


@router.post("/logout")
async def logout(
    payload: LogoutIn,
    claims = Depends(get_current_claims),
    redis=Depends(get_redis),
):
    assert_device_access(payload.device_id, claims)
    await revoke_and_block(redis, claims.sub, payload.device_id, publish_block=payload.block)
    return {"detail": "Logged out"}
