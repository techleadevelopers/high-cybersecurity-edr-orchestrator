import hashlib
import datetime as dt
from typing import Optional

from fastapi import HTTPException


class AttestationPayload(dict):
    """Placeholder type to avoid tight coupling with platform SDKs."""
    pass


def _hash_public_key(key_pem: str) -> str:
    return hashlib.sha256(key_pem.encode()).hexdigest()


def validate_attestation(attestation: Optional[dict]) -> tuple[str, str, str]:
    """
    Stub: replace with calls to App Attest / Play Integrity.
    Returns (attestation_type, nonce, pubkey_hash).
    """
    if not attestation:
        raise HTTPException(status_code=403, detail="Attestation required")

    att_type = attestation.get("type")
    nonce = attestation.get("nonce")
    pubkey = attestation.get("public_key", "")
    ok = attestation.get("valid", False)
    if not (att_type and nonce and pubkey and ok):
        raise HTTPException(status_code=403, detail="Attestation failed")
    return att_type, nonce, _hash_public_key(pubkey)


def build_attestation_record(attestation: dict, verified_at: dt.datetime) -> dict:
    att_type, nonce, pubhash = validate_attestation(attestation)
    return {
        "attestation_type": att_type,
        "attestation_nonce": nonce,
        "attested_public_key_hash": pubhash,
        "verified_at": verified_at,
        "risk_reason": attestation.get("risk_reason"),
    }
