import asyncio
import datetime as dt
from typing import Optional

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from redis import asyncio as aioredis

from app.schemas.signal import TrustScore
from app.core.deps import get_redis, get_settings_dep, _ensure_redis_pool
from app.core.config import Settings
from app.services.kill_switch import KillSwitchHub, relay_kill_switch
from app.core.auth import get_current_claims, assert_device_access, decode_token_raw
from app.services.access import compute_paywall_state
from app.db.session import async_session

router = APIRouter()
kill_switch_hub = KillSwitchHub()
stop_event = asyncio.Event()
listener_task: asyncio.Task | None = None


@router.get("/trust-score", response_model=TrustScore)
async def trust_score(
    device_id: str,
    redis=Depends(get_redis),
    settings: Settings = Depends(get_settings_dep),
    claims = Depends(get_current_claims),
):
    assert_device_access(device_id, claims)
    score = await redis.get(f"device:{device_id}:trust")
    if score is None:
        score = 80
    return TrustScore(device_id=device_id, score=int(score), verdict="safe" if int(score) >= 50 else "block")


@router.websocket("/kill-switch")
async def websocket_kill_switch(websocket: WebSocket, settings: Settings = Depends(get_settings_dep)):
    global listener_task
    # Enforce Origin allowlist if configured
    origin = websocket.headers.get("origin")
    if settings.ws_allowed_origins and origin not in [str(o) for o in settings.ws_allowed_origins]:
        await websocket.close(code=1008)
        return

    # Token via Sec-WebSocket-Protocol: bearer,<JWT> or Authorization header
    token: Optional[str] = None
    proto_header = websocket.headers.get("sec-websocket-protocol")
    if proto_header:
        parts = [p.strip() for p in proto_header.split(",") if p.strip()]
        bearer_entry = next((p for p in parts if p.lower().startswith("bearer")), None)
        if bearer_entry and "," in proto_header:
            token_candidate = parts[1] if len(parts) > 1 else None
        else:
            token_candidate = bearer_entry.split("bearer", 1)[1].strip() if bearer_entry else None
        token = token_candidate or token
    if not token:
        auth = websocket.headers.get("authorization") or websocket.headers.get("Authorization")
        if auth and auth.lower().startswith("bearer "):
            token = auth.split(" ", 1)[1]

    if not token:
        await websocket.close(code=1008)  # policy violation
        return

    redis = aioredis.Redis(connection_pool=_ensure_redis_pool(settings.redis_url))
    try:
        claims = decode_token_raw(token, settings)
        device_id = websocket.query_params.get("device_id") or claims.device_id
        assert_device_access(device_id, claims)

        # per-IP/device connection rate limit
        client_ip = websocket.client.host if websocket.client else "unknown"
        rl_key = f"ws:conn:{client_ip}:{device_id}"
        count = await redis.incr(rl_key)
        if count == 1:
            await redis.expire(rl_key, settings.ws_rate_limit_window)
        if count > settings.ws_rate_limit_max:
            await websocket.close(code=1013)  # try again later
            return

        # Paywall enforcement
        async with async_session() as session:
            is_premium, trial_expired, _ = await compute_paywall_state(
                session, claims.sub, device_id, dt.datetime.now(dt.timezone.utc), settings=settings
            )
        if trial_expired and not is_premium:
            await websocket.close(code=4003)  # custom close for payment required
            return
    except Exception:
        await websocket.close(code=1008)
        return

    websocket.app.state.settings = settings  # used for initial force overlay fetch
    await kill_switch_hub.register(websocket, device_id, subprotocol="bearer" if proto_header else None)
    if listener_task is None or listener_task.done():
        listener_task = asyncio.create_task(relay_kill_switch(kill_switch_hub, settings.redis_url, stop_event))

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await kill_switch_hub.unregister(websocket)
    finally:
        await redis.aclose()
        if not kill_switch_hub.connections and listener_task:
            stop_event.set()
            await listener_task
            stop_event.clear()
            listener_task = None
