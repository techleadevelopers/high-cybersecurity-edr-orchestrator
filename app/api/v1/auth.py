from fastapi import APIRouter, Depends
from fastapi import HTTPException
from pydantic import BaseModel
from app.core.deps import get_settings_dep, get_redis
from app.core.config import Settings
from app.services.tokens import refresh_tokens

router = APIRouter()


class RefreshIn(BaseModel):
    refresh_token: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str


@router.post("/refresh", response_model=TokenPair)
async def refresh(payload: RefreshIn, settings: Settings = Depends(get_settings_dep), redis=Depends(get_redis)):
    access, refresh_tok = await refresh_tokens(settings, redis, payload.refresh_token)
    return TokenPair(access_token=access, refresh_token=refresh_tok)
