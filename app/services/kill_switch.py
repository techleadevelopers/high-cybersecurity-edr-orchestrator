import asyncio
from typing import Set, Tuple
from fastapi import WebSocket
from redis import asyncio as aioredis
from app.core.deps import _ensure_redis_pool


class KillSwitchHub:
    def __init__(self):
        self.connections: Set[Tuple[WebSocket, str]] = set()

    async def register(self, websocket: WebSocket, device_id: str, subprotocol: str | None = None):
        await websocket.accept(subprotocol=subprotocol, compression=None)  # disable permessage-deflate for menor latência
        self.connections.add((websocket, device_id))

    async def unregister(self, websocket: WebSocket):
        self.connections = {(ws, did) for (ws, did) in self.connections if ws != websocket}

    async def broadcast(self, message: str):
        target_device = None
        if message.startswith("block:"):
            parts = message.split(":")
            if len(parts) >= 2:
                target_device = parts[1]

        for ws, device_id in list(self.connections):
            if target_device and device_id != target_device:
                continue
            try:
                await ws.send_text(message)
            except Exception:
                await self.unregister(ws)


async def relay_kill_switch(hub: KillSwitchHub, redis_url: str, stop_event: asyncio.Event):
    redis = aioredis.Redis(connection_pool=_ensure_redis_pool(redis_url))
    pubsub = redis.pubsub()
    await pubsub.subscribe("kill-switch")
    try:
        while not stop_event.is_set():
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message and message.get("data"):
                await hub.broadcast(str(message["data"]))
    finally:
        await pubsub.unsubscribe("kill-switch")
        await pubsub.close()
        await redis.close()
