import datetime as dt
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, insert, update
from app.models.subscription import Subscription
from app.models.device_registration import DeviceRegistration
from app.services.attestation import build_attestation_record
from fastapi import HTTPException


async def ensure_device_registration(
    session: AsyncSession,
    user_id: str,
    device_id: str,
    attestation_payload: dict | None = None,
) -> DeviceRegistration:
    stmt = select(DeviceRegistration).where(DeviceRegistration.user_id == user_id, DeviceRegistration.device_id == device_id)
    reg = (await session.execute(stmt)).scalar_one_or_none()
    if reg:
        # If attestation provided later, update once
        if attestation_payload and reg.verified_at is None:
            att_data = build_attestation_record(attestation_payload, dt.datetime.now(dt.timezone.utc))
            await session.execute(
                update(DeviceRegistration)
                .where(DeviceRegistration.id == reg.id)
                .values(**att_data)
            )
            await session.commit()
            reg = (await session.execute(stmt)).scalar_one()
        return reg
    if not attestation_payload:
        raise HTTPException(status_code=403, detail="Attestation required for new device")
    values = {"user_id": user_id, "device_id": device_id}
    if attestation_payload:
        values.update(build_attestation_record(attestation_payload, dt.datetime.now(dt.timezone.utc)))
    result = await session.execute(
        insert(DeviceRegistration)
        .values(**values)
        .returning(DeviceRegistration)
    )
    reg = result.scalar_one()
    await session.commit()
    return reg


def is_subscription_premium(sub: Subscription | None, now: dt.datetime) -> bool:
    if not sub:
        return False
    if sub.status != "active":
        return False
    if sub.expires_at and sub.expires_at < now:
        return False
    return True


async def compute_paywall_state(
    session: AsyncSession,
    user_id: str,
    device_id: str,
    now: dt.datetime,
    attestation_payload: dict | None = None,
) -> tuple[bool, bool, dt.datetime]:
    reg = await ensure_device_registration(session, user_id, device_id, attestation_payload=attestation_payload)
    sub_stmt = select(Subscription).where(Subscription.user_id == user_id, Subscription.device_id == device_id)
    sub = (await session.execute(sub_stmt)).scalar_one_or_none()
    is_premium = is_subscription_premium(sub, now)
    trial_expired = (now - reg.created_at) > dt.timedelta(days=7)
    return is_premium, trial_expired, reg.created_at
