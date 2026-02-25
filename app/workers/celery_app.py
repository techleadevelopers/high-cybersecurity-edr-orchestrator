import asyncio
import datetime as dt
import json
import math
from typing import List

from celery import Celery
from redis import asyncio as aioredis
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.deps import _ensure_redis_pool
from app.models.signal import AuditLog
from app.schemas.signal import SensorPayload
from app.services.tokens import revoke_and_block
from app.services.trust import compute_trust_score_stateful, MAX_HISTORY

settings = get_settings()
celery = Celery(
    "blockremote",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

# Eager config for dev
celery.conf.update(task_serializer="json", accept_content=["json"], result_serializer="json")

engine = create_async_engine(settings.database_url, future=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def _record_hist(redis, key: str, value: int, buckets: list[int]):
    for b in buckets:
        if value <= b:
            await redis.hincrby(key, str(b), 1)
            break
    else:
        await redis.hincrby(key, "inf", 1)


@celery.task(name="analyze_signal")
def analyze_signal(signal_id: int, payload: dict, device_id: str, user_id: str, enqueued_at: str | None = None):
    async def _run():
        async with SessionLocal() as session:
            redis = aioredis.Redis(connection_pool=_ensure_redis_pool(settings.redis_url))

            queue_depth = await redis.llen("celery")
            enqueue_latency_ms = None
            if enqueued_at:
                try:
                    enq_dt = dt.datetime.fromisoformat(enqueued_at)
                    enqueue_latency_ms = int((dt.datetime.now(dt.timezone.utc) - enq_dt).total_seconds() * 1000)
                except Exception:
                    enqueue_latency_ms = None

            # Latency / depth breaker
            if queue_depth and queue_depth > 1000:
                await redis.aclose()
                return

            runtime_samples_raw = await redis.lrange("metrics:celery:runtime_ms", 0, 199)
            runtime_samples = [int(x) for x in runtime_samples_raw if str(x).isdigit()]
            runtime_p95 = None
            if runtime_samples:
                runtime_samples.sort()
                idx = max(0, math.ceil(0.95 * len(runtime_samples)) - 1)
                runtime_p95 = runtime_samples[idx]
            if runtime_p95 and runtime_p95 > 500:
                last_decision = await redis.get(f"decision:{device_id}")
                if last_decision:
                    await redis.aclose()
                    return

            payload_obj = SensorPayload(**payload)
            sig_key = f"sig:{device_id}"
            history_raw = await redis.lrange(sig_key, 0, MAX_HISTORY - 1)
            history: List[SensorPayload] = []
            for item in history_raw:
                try:
                    history.append(SensorPayload(**json.loads(item)))
                except Exception:
                    continue

            score, diagnostics = compute_trust_score_stateful(payload_obj, history)
            await redis.hset(
                f"trust_diag:{device_id}",
                mapping={
                    "accel_z": diagnostics.get("accel_z", 0),
                    "gyro_z": diagnostics.get("gyro_z", 0),
                    "touch_entropy": diagnostics.get("touch_entropy", 0),
                    "corr": diagnostics.get("accel_gyro_corr", 0),
                },
            )

            baseline_key = f"baseline:{device_id}"
            baseline = await redis.hgetall(baseline_key)
            mean = float(baseline.get("mean", 0) or 0)
            m2 = float(baseline.get("m2", 0) or 0)
            count = int(baseline.get("count", 0) or 0)
            count += 1
            delta = score - mean
            mean += delta / count
            m2 += delta * (score - mean)
            std = math.sqrt(m2 / count) if count > 1 else 0.0
            await redis.hset(baseline_key, mapping={"mean": mean, "m2": m2, "std": std, "count": count})
            await redis.expire(baseline_key, 7 * 24 * 3600)

            adaptive_threshold = max(30, mean - 2 * std) if count >= 10 else 50
            decision_key = f"decision:{device_id}"
            await redis.set(decision_key, score, ex=300)
            await redis.lpush(f"trust_hist:{device_id}", score)
            await redis.ltrim(f"trust_hist:{device_id}", 0, MAX_HISTORY - 1)

            start_proc = dt.datetime.now(dt.timezone.utc)

            if score < adaptive_threshold:
                reason = "Trust score below adaptive threshold"
                await session.execute(
                    insert(AuditLog).values(
                        user_id=user_id,
                        device_id=device_id,
                        threat_level="high" if score < 20 else "medium",
                        reason=reason,
                        signal_id=signal_id,
                    )
                )
                await session.commit()
                await revoke_and_block(redis, user_id, device_id, publish_block=True)
                await redis.set(f"revoked:device:{device_id}", "1", ex=3600)
                await redis.publish("kill-switch", f"block:{device_id}:score:{score}")

            runtime_ms = int((dt.datetime.now(dt.timezone.utc) - start_proc).total_seconds() * 1000)

            buckets = [50, 100, 200, 300, 500, 800, 1200]
            if enqueue_latency_ms is not None:
                await _record_hist(redis, "metrics:celery:enqueue_ms_hist", enqueue_latency_ms, buckets)
                await redis.lpush("metrics:celery:enqueue_ms", enqueue_latency_ms)
                await redis.ltrim("metrics:celery:enqueue_ms", 0, 299)
            await _record_hist(redis, "metrics:celery:runtime_ms_hist", runtime_ms, buckets)
            await redis.lpush("metrics:celery:runtime_ms", runtime_ms)
            await redis.ltrim("metrics:celery:runtime_ms", 0, 299)
            await redis.aclose()
    asyncio.run(_run())
