import asyncio
import datetime as dt
from fastapi import APIRouter, WebSocket, Depends, WebSocketDisconnect
from app.core.auth import decode_token_raw, assert_device_access
from app.core.config import Settings
from app.core.deps import get_settings_dep, _ensure_redis_pool
from redis import asyncio as aioredis

router = APIRouter()
priority_stop = asyncio.Event()
priority_task: asyncio.Task | None = None


@router.websocket("/priority")
async def priority_ws(websocket: WebSocket, settings: Settings = Depends(get_settings_dep)):
    # Expect token + device_id in query
    token = websocket.query_params.get("token")
    device_id = websocket.query_params.get("device_id")
    if not token or not device_id:
        await websocket.close(code=1008)
        return
    try:
        claims = decode_token_raw(token, settings)
        assert_device_access(device_id, claims)
    except Exception:
        await websocket.close(code=1008)
        return

    redis = aioredis.Redis(connection_pool=_ensure_redis_pool(settings.redis_url))
    await websocket.accept(compression=None)
    # On connect, send forced overlay if needed
    if await redis.get(f"force_overlay:{device_id}"):
        await websocket.send_text(f"force_overlay:{device_id}")

    try:
        while True:
            msg = await websocket.receive_text()
            if msg == "SYNTHETIC_TOUCH_ALARM":
                await redis.publish("kill-switch", f"CRITICAL_LOCK:{device_id}")
    except WebSocketDisconnect:
        pass
    finally:
        await redis.aclose()
