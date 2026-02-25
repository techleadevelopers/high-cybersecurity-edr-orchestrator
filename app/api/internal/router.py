from fastapi import APIRouter

from app.api.internal import jwks

internal_router = APIRouter(prefix="/internal", tags=["internal"])
internal_router.include_router(jwks.router)
