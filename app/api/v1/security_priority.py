import asyncio
from typing import Optional

from fastapi import APIRouter, WebSocket, Depends, WebSocketDisconnect
from redis import asyncio as aioredis

from app.core.auth import decode_token_raw, assert_device_access
from app.core.config import Settings
from app.core.deps import get_settings_dep, _ensure_redis_pool

router = APIRouter()
priority_stop = asyncio.Event()
priority_task: asyncio.Task | None = None


@router.websocket("/priority")
async def priority_ws(websocket: WebSocket, settings: Settings = Depends(get_settings_dep)):
    # Origin enforcement
    origin = websocket.headers.get("origin")
    if settings.ws_allowed_origins and origin not in [str(o) for o in settings.ws_allowed_origins]:
        await websocket.close(code=1008)
        return

    # Token via Sec-WebSocket-Protocol bearer,<jwt> or Authorization header
    token: Optional[str] = None
    proto_header = websocket.headers.get("sec-websocket-protocol")
    if proto_header:
        parts = [p.strip() for p in proto_header.split(",") if p.strip()]
        bearer_entry = next((p for p in parts if p.lower().startswith("bearer")), None)
        token = parts[1] if bearer_entry and len(parts) > 1 else token
    if not token:
        auth = websocket.headers.get("authorization") or websocket.headers.get("Authorization")
        if auth and auth.lower().startswith("bearer "):
            token = auth.split(" ", 1)[1]
    device_id = websocket.query_params.get("device_id")

    if not token:
        await websocket.close(code=1008)
        return

    redis = aioredis.Redis(connection_pool=_ensure_redis_pool(settings.redis_url))
    try:
        claims = decode_token_raw(token, settings)
        device_id = device_id or claims.device_id
        assert_device_access(device_id, claims)

        # rate limit per device/IP
        client_ip = websocket.client.host if websocket.client else "unknown"
        rl_key = f"ws:priority:{client_ip}:{device_id}"
        attempts = await redis.incr(rl_key)
        if attempts == 1:
            await redis.expire(rl_key, settings.ws_rate_limit_window)
        if attempts > settings.ws_rate_limit_max:
            await websocket.close(code=1013)
            return

        await websocket.accept(subprotocol="bearer", compression=None)
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
