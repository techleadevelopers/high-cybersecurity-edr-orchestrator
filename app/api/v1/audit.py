from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.schemas.signal import AuditLogOut
from app.models.signal import AuditLog
from app.core.deps import get_db_session
from app.core.auth import get_current_claims, assert_device_access

router = APIRouter()


@router.get("/logs", response_model=list[AuditLogOut])
async def list_logs(
    device_id: str,
    session: AsyncSession = Depends(get_db_session),
    claims = Depends(get_current_claims),
):
    assert_device_access(device_id, claims)
    stmt = (
        select(AuditLog)
        .where(AuditLog.user_id == claims.sub, AuditLog.device_id == device_id)
        .order_by(AuditLog.created_at.desc())
        .limit(200)
    )
    result = await session.execute(stmt)
    return result.scalars().all()
