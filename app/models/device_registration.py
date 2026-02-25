import datetime as dt
import uuid
from sqlalchemy import String, DateTime, Index
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class DeviceRegistration(Base):
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    device_id: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc)
    )
    attestation_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    attestation_nonce: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attested_public_key_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    verified_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    risk_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)

    __table_args__ = (
        Index("ix_devicereg_user_device", "user_id", "device_id", unique=True),
    )
