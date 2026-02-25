import hashlib
import datetime as dt
from typing import Optional
import httpx

from fastapi import HTTPException


class AttestationPayload(dict):
    """Generic holder; concrete payloads depend on platform."""
    pass


def _hash_public_key(key_pem: str) -> str:
    return hashlib.sha256(key_pem.encode()).hexdigest()


async def _verify_play_integrity(payload: dict, api_key: str) -> tuple[str, str, str]:
    """
    Calls Google Play Integrity API.
    Expects payload to contain `token` (integrity_token) and `nonce`.
    """
    token = payload.get("token")
    nonce = payload.get("nonce")
    if not token or not nonce:
        raise HTTPException(status_code=403, detail="Attestation payload incomplete")
    if not api_key:
        raise HTTPException(status_code=500, detail="Play Integrity API key not configured")
    url = f"https://playintegrity.googleapis.com/v1/verifyIntegrityToken?key={api_key}"
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.post(url, json={"integrity_token": token, "nonce": nonce})
    if resp.status_code != 200:
        raise HTTPException(status_code=403, detail="Play Integrity verification failed")
    data = resp.json()
    summary = data.get("tokenPayloadExternal", {}).get("deviceIntegrity", [])
    if "MEETS_DEVICE_INTEGRITY" not in summary:
        raise HTTPException(status_code=403, detail="Device integrity not met")
    # Use app certificate digest as pseudo public key hash
    certs = data.get("tokenPayloadExternal", {}).get("certificateSha256Digest", [])
    pubhash = certs[0] if certs else _hash_public_key(payload.get("public_key", ""))
    return "play_integrity", nonce, pubhash


async def _verify_app_attest(payload: dict, endpoint: str) -> tuple[str, str, str]:
    """
    Delegates to an attestation validation endpoint (Apple App Attest).
    Expects `attestation_object`, `client_data_hash`, `nonce`.
    """
    att_obj = payload.get("attestation_object")
    client_hash = payload.get("client_data_hash")
    nonce = payload.get("nonce")
    if not (att_obj and client_hash and nonce):
        raise HTTPException(status_code=403, detail="Attestation payload incomplete")
    if not endpoint:
        raise HTTPException(status_code=500, detail="App Attest validator URL not configured")
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.post(endpoint, json={"attestation_object": att_obj, "client_data_hash": client_hash, "nonce": nonce})
    if resp.status_code != 200:
        raise HTTPException(status_code=403, detail="App Attest verification failed")
    data = resp.json()
    if not data.get("valid"):
        raise HTTPException(status_code=403, detail="App Attest invalid")
    pubhash = data.get("public_key_hash") or _hash_public_key(payload.get("public_key", ""))
    return "app_attest", nonce, pubhash


async def validate_attestation(attestation: Optional[dict], settings) -> tuple[str, str, str]:
    """
    Returns (attestation_type, nonce, pubkey_hash).
    """
    if not attestation:
        raise HTTPException(status_code=403, detail="Attestation required")

    platform = attestation.get("platform")
    if platform == "play_integrity":
        return await _verify_play_integrity(attestation, settings.play_integrity_api_key)
    if platform == "app_attest":
        return await _verify_app_attest(attestation, settings.app_attest_validator_url)

    # Fallback: legacy validation for tests/dev
    att_type = attestation.get("type")
    nonce = attestation.get("nonce")
    pubkey = attestation.get("public_key", "")
    ok = attestation.get("valid", False)
    if not (att_type and nonce and pubkey and ok):
        raise HTTPException(status_code=403, detail="Attestation failed")
    return att_type, nonce, _hash_public_key(pubkey)


async def build_attestation_record(attestation: dict, verified_at: dt.datetime, settings) -> dict:
    att_type, nonce, pubhash = await validate_attestation(attestation, settings)
    return {
        "attestation_type": att_type,
        "attestation_nonce": nonce,
        "attested_public_key_hash": pubhash,
        "verified_at": verified_at,
        "risk_reason": attestation.get("risk_reason"),
    }
