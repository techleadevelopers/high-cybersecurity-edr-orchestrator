import hmac
import hashlib
import datetime as dt
from fastapi import APIRouter, Header, HTTPException, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, insert, update

from app.core.config import Settings
from app.core.deps import get_settings_dep, get_db_session, get_redis
from app.schemas.subscription import BillingWebhookIn, SubscriptionOut, BillingStatusOut, BillingStatusIn
from app.models.subscription import Subscription, BillingEvent, Plan
from app.core.auth import get_current_claims, assert_device_access
from app.services.access import compute_paywall_state

router = APIRouter()


def verify_signature(secret: str, signature: str | None, body: bytes):
    if not signature:
        raise HTTPException(status_code=401, detail="Missing signature")
    mac = hmac.new(secret.encode(), msg=body, digestmod=hashlib.sha256).hexdigest()
    if not hmac.compare_digest(mac, signature):
        raise HTTPException(status_code=401, detail="Invalid signature")


async def get_raw_body(request: Request) -> bytes:
    return await request.body()


@router.post("/webhook", response_model=SubscriptionOut)
async def billing_webhook(
    payload: BillingWebhookIn,
    x_signature: str | None = Header(default=None, convert_underscores=False, alias="X-Signature"),
    raw_body: bytes = Depends(get_raw_body),
    settings: Settings = Depends(get_settings_dep),
    session: AsyncSession = Depends(get_db_session),
    redis = Depends(get_redis),
):
    verify_signature(settings.billing_webhook_secret, x_signature, raw_body)

    # Idempotência
    existing_event = await session.execute(select(BillingEvent).where(BillingEvent.event_id == payload.event_id))
    if existing_event.scalar_one_or_none():
        sub_stmt = select(Subscription).where(Subscription.user_id == payload.user_id, Subscription.device_id == payload.device_id)
        sub = (await session.execute(sub_stmt)).scalar_one_or_none()
        if not sub:
            raise HTTPException(status_code=404, detail="Subscription not found")
        return SubscriptionOut.from_orm(sub)

    await session.execute(
        insert(BillingEvent).values(
            provider=payload.provider,
            event_id=payload.event_id,
            payload=payload.payload,
        )
    )

    sub_stmt = select(Subscription).where(Subscription.user_id == payload.user_id, Subscription.device_id == payload.device_id)
    sub = (await session.execute(sub_stmt)).scalar_one_or_none()
    expires_at = payload.expires_at if payload.expires_at else dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=7)

    if sub:
        await session.execute(
            update(Subscription)
            .where(Subscription.id == sub.id)
            .values(
                plan_code=payload.plan_code,
                plan_tier=payload.plan_tier,
                status=payload.status,
                expires_at=expires_at,
                auto_renew=payload.auto_renew,
            )
        )
    else:
        await session.execute(
            insert(Subscription).values(
                user_id=payload.user_id,
                device_id=payload.device_id,
                plan_code=payload.plan_code,
                plan_tier=payload.plan_tier,
                status=payload.status,
                expires_at=expires_at,
                auto_renew=payload.auto_renew,
            )
        )

    await session.commit()

    # Cache em Redis
    cache_key = f"sub:{payload.user_id}:{payload.device_id}"
    await redis.hset(
        cache_key,
        mapping={
            "status": payload.status,
            "plan_tier": payload.plan_tier,
            "plan_code": payload.plan_code,
            "expires_at": expires_at.isoformat() if expires_at else "",
        },
    )
    await redis.expire(cache_key, 900)

    sub_row = (await session.execute(sub_stmt)).scalar_one()
    return SubscriptionOut.from_orm(sub_row)


@router.get("/subscription", response_model=SubscriptionOut)
async def get_subscription(
    device_id: str,
    claims = Depends(get_current_claims),
    session: AsyncSession = Depends(get_db_session),
    redis = Depends(get_redis),
):
    assert_device_access(device_id, claims)
    subject = claims.sub
    cache_key = f"sub:{subject}:{device_id}"
    cached = await redis.hgetall(cache_key)
    if cached and cached.get("plan_tier"):
        expires = cached.get("expires_at") or None
        expires_at = dt.datetime.fromisoformat(expires) if expires else None
        return SubscriptionOut(
            user_id=subject,
            device_id=device_id,
            plan_code=cached.get("plan_code", "unknown"),
            status=cached.get("status", "trial"),
            plan_tier=cached.get("plan_tier", "trial"),
            expires_at=expires_at,
        )

    stmt = select(Subscription).where(Subscription.user_id == subject, Subscription.device_id == device_id)
    sub = (await session.execute(stmt)).scalar_one_or_none()
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")
    # refresh cache
    await redis.hset(
        cache_key,
        mapping={
            "status": sub.status,
            "plan_tier": sub.plan_tier,
            "plan_code": sub.plan_code,
            "expires_at": sub.expires_at.isoformat() if sub.expires_at else "",
        },
    )
    await redis.expire(cache_key, 900)
    return SubscriptionOut.from_orm(sub)


@router.post("/status", response_model=BillingStatusOut)
async def billing_status(
    payload: BillingStatusIn,
    claims = Depends(get_current_claims),
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings_dep),
):
    assert_device_access(payload.device_id, claims)
    now = dt.datetime.now(dt.timezone.utc)
    is_premium, trial_expired, created_at = await compute_paywall_state(
        session,
        claims.sub,
        payload.device_id,
        now,
        attestation_payload=payload.attestation.dict() if payload.attestation else None,
        settings=settings,
    )
    if trial_expired and not is_premium:
        raise HTTPException(status_code=402, detail="Payment required")
    return BillingStatusOut(
        user_id=claims.sub,
        device_id=payload.device_id,
        is_premium=is_premium,
        trial_expired=trial_expired,
        trial_started_at=created_at,
        now=now,
    )
