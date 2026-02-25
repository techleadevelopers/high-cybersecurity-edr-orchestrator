import datetime as dt
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import insert
from redis import asyncio as aioredis

from app.schemas.edr import EdrReportIn, EdrReportOut
from app.core.auth import get_current_claims, assert_device_access
from app.core.deps import get_db_session, get_redis, get_settings_dep, _ensure_redis_pool
from app.core.config import Settings
from app.services.threat import compute_risk
from app.services.tokens import revoke_and_block
from app.models.signal import AuditLog

router = APIRouter()


@router.post("/report", response_model=EdrReportOut)
async def edr_report(
    payload: EdrReportIn,
    claims = Depends(get_current_claims),
    session: AsyncSession = Depends(get_db_session),
    redis=Depends(get_redis),
    settings: Settings = Depends(get_settings_dep),
):
    assert_device_access(payload.device_id, claims)
    risk_score, risk_level, actions = compute_risk(payload)

    # Persist audit trail
    if risk_level in ("high", "critical"):
        await session.execute(
            insert(AuditLog).values(
                user_id=claims.sub,
                device_id=payload.device_id,
                threat_level=risk_level,
                reason=";".join(actions) or "edr_report",
                created_at=dt.datetime.now(dt.timezone.utc),
            )
        )
        await session.commit()

    # Quarantine / revoke on critical
    if risk_level == "critical":
        await revoke_and_block(redis, claims.sub, payload.device_id, publish_block=True)
        await redis.publish("kill-switch", f"IMMEDIATE_QUARANTINE:{payload.device_id}")

    return EdrReportOut(device_id=payload.device_id, risk_score=risk_score, risk_level=risk_level, actions=actions)
