import asyncio
import datetime as dt
from celery import Celery
from redis import asyncio as aioredis
from redis.asyncio import ConnectionPool
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from app.core.config import get_settings
from app.services.trust import compute_trust_score
from app.schemas.signal import SensorPayload
from app.models.signal import Signal, AuditLog
from sqlalchemy import insert
from app.core.deps import _ensure_redis_pool
import json
import statistics

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

            if queue_depth and queue_depth > 1000:
                # Circuit breaker: keep last decision
                await redis.aclose()
                return

            payload_obj = SensorPayload(**payload)
            base_score = compute_trust_score(payload_obj)

            sig_key = f"sig:{device_id}"
            history_raw = await redis.lrange(sig_key, 0, 9)
            movements = []
            for item in history_raw:
                try:
                    p = SensorPayload(**json.loads(item))
                    movements.append(sum(abs(x) for x in p.accelerometer + p.gyroscope))
                except Exception:
                    continue
            variation_penalty = 0
            if len(movements) >= 3:
                stddev = statistics.pstdev(movements)
                if stddev < 0.05:  # very flat signals -> possível automação
                    variation_penalty = 15

            score = max(0, base_score - variation_penalty)
            decision_key = f"decision:{device_id}"
            await redis.set(decision_key, score, ex=300)

            # Metrics: store last 50 samples of enqueue latency and runtime
            start_proc = dt.datetime.now(dt.timezone.utc)

            if score < 40:
                await session.execute(
                    insert(AuditLog).values(
                        user_id=user_id,
                        device_id=device_id,
                        threat_level="high" if score < 20 else "medium",
                        reason="Static device with active overlay",
                        signal_id=signal_id,
                    )
                )
                await session.commit()
                await redis.publish("kill-switch", f"block:{device_id}:score:{score}")
            runtime_ms = int((dt.datetime.now(dt.timezone.utc) - start_proc).total_seconds() * 1000)
            metrics_pipe = redis.pipeline()
            if enqueue_latency_ms is not None:
                metrics_pipe.lpush("metrics:celery:enqueue_ms", enqueue_latency_ms)
                metrics_pipe.ltrim("metrics:celery:enqueue_ms", 0, 49)
            metrics_pipe.lpush("metrics:celery:runtime_ms", runtime_ms)
            metrics_pipe.ltrim("metrics:celery:runtime_ms", 0, 49)
            await metrics_pipe.execute()
            await redis.aclose()
    asyncio.run(_run())
