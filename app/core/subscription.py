import datetime as dt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from redis import asyncio as aioredis
from app.core.config import get_settings
from app.core.security import verify_token, TokenClaims
from app.core.deps import _ensure_redis_pool
from app.services.access import compute_paywall_state
from app.db.session import async_session

PROTECTED_PREFIXES = ("/v1/signals", "/v1/security")
PLAN_RATE_LIMITS = {
    "trial": {"limit": 120, "window": 60},
    "paid_basic": {"limit": 600, "window": 60},
    "paid": {"limit": 1200, "window": 60},
    "android_accessibility": {"limit": 1800, "window": 60},
}


def _needs_guard(path: str) -> bool:
    return any(path.startswith(p) for p in PROTECTED_PREFIXES)


async def check_rate_limit(redis, key: str, limit: int, window: int) -> bool:
    current = await redis.incr(key)
    if current == 1:
        await redis.expire(key, window)
    return current <= limit


class SubscriptionGuardMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if not _needs_guard(request.url.path):
            return await call_next(request)

        auth = request.headers.get("Authorization")
        if not auth or not auth.lower().startswith("bearer "):
            return JSONResponse({"detail": "Missing bearer token"}, status_code=401)
        token = auth.split(" ", 1)[1]

        settings = get_settings()
        try:
            claims: TokenClaims = verify_token(token, settings, expected_typ="access")
        except Exception:
            return JSONResponse({"detail": "Invalid token"}, status_code=401)
        subject = claims.sub

        redis = aioredis.Redis(connection_pool=_ensure_redis_pool(settings.redis_url))
        device_id = request.headers.get("X-Device-Id", "").strip() or claims.device_id
        if claims.device_id != device_id:
            await redis.close()
            return JSONResponse({"detail": "Token not authorized for this device"}, status_code=403)
        # Revoked/blocked device short-circuit
        if await redis.get(f"revoked:device:{device_id}") or await redis.get(f"device:{device_id}:state") == "blocked":
            await redis.close()
            return JSONResponse({"detail": "Device revoked"}, status_code=403)

        cache_key = f"sub:{subject}:{device_id}"
        data = await redis.hgetall(cache_key)

        if not data:
            async with async_session() as session:
                is_premium, trial_expired, _ = await compute_paywall_state(
                    session, subject, device_id, dt.datetime.now(dt.timezone.utc), settings=settings
                )
            if trial_expired and not is_premium:
                await redis.close()
                return JSONResponse({"detail": "Subscription required"}, status_code=402)
            status = "trial"
            plan_tier = "trial"
        else:
            status = data.get("status", "trial")
            expires_at = data.get("expires_at")
            if expires_at:
                try:
                    if dt.datetime.fromisoformat(expires_at) < dt.datetime.now(dt.timezone.utc):
                        await redis.close()
                        return JSONResponse({"detail": "Subscription expired"}, status_code=402)
                except ValueError:
                    pass

            if status not in ("active", "trial"):
                await redis.close()
                return JSONResponse({"detail": "Subscription inactive"}, status_code=402)

        plan_tier = data.get("plan_tier", "trial")
        # Adaptive prioritization for Android accessibility telemetry
        if request.headers.get("X-Platform") == "android" and request.headers.get("X-Accessibility-Telemetry") == "true":
            plan_tier = "android_accessibility"
            if status == "trial":
                async with async_session() as session:
                    is_premium, trial_expired, _ = await compute_paywall_state(
                        session, subject, device_id, dt.datetime.now(dt.timezone.utc), settings=settings
                    )
                if trial_expired and not is_premium:
                    await redis.close()
                    return JSONResponse({"detail": "Subscription required"}, status_code=402)

        request.state.plan_tier = plan_tier

        # Rate limiting por plano
        limits = PLAN_RATE_LIMITS.get(plan_tier, PLAN_RATE_LIMITS["trial"])
        rl_key = f"rl:{plan_tier}:{subject}:{device_id or 'na'}"
        allowed = await check_rate_limit(redis, rl_key, limits["limit"], limits["window"])
        if not allowed:
            await redis.close()
            return JSONResponse({"detail": "Rate limit exceeded"}, status_code=429)

        await redis.close()
        response = await call_next(request)
        response.headers["X-Plan-Tier"] = request.state.plan_tier
        return response
