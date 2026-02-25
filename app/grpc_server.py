import asyncio
import datetime as dt
import logging
import grpc
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from redis import asyncio as aioredis

from app.core.config import get_settings
from app.core.deps import _ensure_redis_pool
from app.services.trust import compute_trust_score
from app.schemas.signal import SensorPayload
from app.services.access import compute_paywall_state
from app.core.security import verify_token
from app.core.auth import assert_device_access
from app.db.session import async_session

try:
    from app.grpc import signals_pb2, signals_pb2_grpc
except Exception as exc:  # pragma: no cover - only when proto not generated
    raise RuntimeError("Generate gRPC stubs with grpcio-tools before running server") from exc

logger = logging.getLogger(__name__)


class SignalIngestService(signals_pb2_grpc.SignalIngestServicer):
    def __init__(self, settings):
        self.settings = settings
        self.redis = aioredis.Redis(connection_pool=_ensure_redis_pool(settings.redis_url))

    async def SendHeartbeat(self, request, context):
        # Metadata: expect Authorization: Bearer <token>
        meta = dict(context.invocation_metadata())
        auth = meta.get("authorization")
        if not auth or not auth.lower().startswith("bearer "):
            await context.abort(grpc.StatusCode.UNAUTHENTICATED, "Missing bearer token")
        token = auth.split(" ", 1)[1]
        claims = verify_token(token, self.settings.jwt_secret_key, [self.settings.jwt_algorithm])
        device_id = request.device_id
        assert_device_access(device_id, claims)

        # Paywall check
        async with async_session() as session:
            is_premium, trial_expired, _ = await compute_paywall_state(
                session, claims.sub, device_id, dt.datetime.now(dt.timezone.utc), settings=self.settings
            )
        if trial_expired and not is_premium:
            await context.abort(grpc.StatusCode.PERMISSION_DENIED, "Payment required")

        payload = SensorPayload(
            accelerometer=list(request.payload.accelerometer),
            gyroscope=list(request.payload.gyroscope),
            overlay=request.payload.overlay,
            proximity=request.payload.proximity,
        )

        state_key = f"device:{device_id}:state"
        rl_key = f"hb:{claims.sub}:{device_id}"
        pipe = self.redis.pipeline(transaction=False)
        pipe.get(state_key)
        pipe.incr(rl_key)
        pipe.expire(rl_key, 60)
        state, *_ = await pipe.execute()
        if state == "blocked":
            await context.abort(grpc.StatusCode.FAILED_PRECONDITION, "Device blocked")

        score = compute_trust_score(payload)
        verdict = "safe" if score >= 50 else "block"
        return signals_pb2.TrustScore(device_id=device_id, score=score, verdict=verdict)


def create_server(settings):
    server = grpc.aio.server(options=[("grpc.default_compression_algorithm", grpc.Compression.Gzip)])
    signals_pb2_grpc.add_SignalIngestServicer_to_server(SignalIngestService(settings), server)
    server.add_insecure_port(f"0.0.0.0:{settings.grpc_port}")
    return server


async def serve():
    settings = get_settings()
    server = create_server(settings)
    await server.start()
    logger.info("gRPC server listening on %s", settings.grpc_port)
    await server.wait_for_termination()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(serve())
