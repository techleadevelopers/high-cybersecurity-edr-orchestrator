import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from jose import jwk

from app.core.config import Settings
from app.core.deps import get_settings_dep

router = APIRouter()

_DEFAULT_JWKS_PATH = Path(__file__).resolve().parents[2] / "core" / "jwks.json"


def _load_static_jwks() -> dict | None:
    if _DEFAULT_JWKS_PATH.exists():
        try:
            return json.loads(_DEFAULT_JWKS_PATH.read_text())
        except Exception:
            return None
    return None


def _pem_to_jwk(public_pem: str, kid: str | None, alg: str) -> dict:
    public_key = jwk.construct(public_pem, algorithm=alg)
    public_jwk = public_key.to_dict()
    if kid:
        public_jwk["kid"] = kid
    public_jwk["use"] = "sig"
    public_jwk["alg"] = alg
    return public_jwk


def build_jwks(settings: Settings) -> dict:
    static_jwks = _load_static_jwks()
    if static_jwks:
        return static_jwks

    if settings.jwt_public_key:
        return {"keys": [_pem_to_jwk(settings.jwt_public_key, settings.jwt_active_kid, settings.jwt_algorithm)]}

    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="No JWKS configured")


@router.get("/jwks", summary="Public JWKS for token verification")
async def get_jwks(settings: Settings = Depends(get_settings_dep)):
    return build_jwks(settings)
