import uuid
from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import insert
from redis import asyncio as aioredis

from app.schemas.signal import HeartbeatIn, HeartbeatAck
from app.core.deps import get_db_session, get_redis, get_settings_dep
from app.core.config import Settings
from app.workers.celery_app import analyze_signal
from app.models.signal import Signal
from app.core.auth import get_current_claims, assert_device_access
from app.services.tokens import revoke_and_block
import datetime as dt

router = APIRouter()


@router.post("/heartbeat", response_model=HeartbeatAck)
async def ingest_signal(
    heartbeat: HeartbeatIn,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db_session),
    redis = Depends(get_redis),
    settings: Settings = Depends(get_settings_dep),
    claims = Depends(get_current_claims),
):
    assert_device_access(heartbeat.device_id, claims)

    state_key = f"device:{heartbeat.device_id}:state"
    rl_key = f"hb:{claims.sub}:{heartbeat.device_id}"
    pipe = redis.pipeline(transaction=False)
    pipe.get(state_key)
    pipe.incr(rl_key)
    pipe.expire(rl_key, 60)
    state, rl_count, _ = await pipe.execute()
    if state == "blocked":
        raise HTTPException(status_code=423, detail="Device blocked")

    # Device admin / accessibility enforcement
    if not heartbeat.payload.device_admin_enabled or not heartbeat.payload.accessibility_enabled:
        await revoke_and_block(redis, claims.sub, heartbeat.device_id, publish_block=True)
        raise HTTPException(status_code=403, detail="Trust breach: admin/accessibility revoked")

    result = await session.execute(
        insert(Signal).values(device_id=heartbeat.device_id, payload=heartbeat.payload.dict())
    )
    signal_id = result.inserted_primary_key[0]
    await session.commit()

    # Store recent payloads for stateful analysis
    sig_key = f"sig:{heartbeat.device_id}"
    pipe2 = redis.pipeline(transaction=False)
    pipe2.lpush(sig_key, heartbeat.payload.json())
    pipe2.ltrim(sig_key, 0, 9)  # keep last 10
    await pipe2.execute()

    background_tasks.add_task(
        analyze_signal.delay,
        signal_id=signal_id,
        payload=heartbeat.payload.dict(),
        device_id=heartbeat.device_id,
        user_id=claims.sub,
        enqueued_at=dt.datetime.now(dt.timezone.utc).isoformat(),
    )

    trust_hint = max(0, 100 - int(heartbeat.payload.overlay * 100))
    return HeartbeatAck(status="queued", trust_hint=trust_hint)
