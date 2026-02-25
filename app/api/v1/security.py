import asyncio
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from app.schemas.signal import TrustScore
from app.core.deps import get_redis, get_settings_dep
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
    # Token via Sec-WebSocket-Protocol (preferred) or ?token= query param
    proto_header = websocket.headers.get("sec-websocket-protocol")
    provided_protocols = [p.strip() for p in proto_header.split(",")] if proto_header else []
    token = provided_protocols[0] if provided_protocols else websocket.query_params.get("token")
    device_id = websocket.query_params.get("device_id")

    if not token or not device_id:
        await websocket.close(code=1008)  # policy violation
        return

    try:
        claims = decode_token_raw(token, settings)
        assert_device_access(device_id, claims)
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
    await kill_switch_hub.register(websocket, device_id, subprotocol=provided_protocols[0] if provided_protocols else None)
    if listener_task is None or listener_task.done():
        listener_task = asyncio.create_task(relay_kill_switch(kill_switch_hub, settings.redis_url, stop_event))

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await kill_switch_hub.unregister(websocket)
    finally:
        if not kill_switch_hub.connections and listener_task:
            stop_event.set()
            await listener_task
            stop_event.clear()
            listener_task = None
