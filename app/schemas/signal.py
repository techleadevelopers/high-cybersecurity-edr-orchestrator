from pydantic import BaseModel, Field
from typing import Optional


class SensorPayload(BaseModel):
    accelerometer: list[float] = Field(..., min_items=3, max_items=3)
    gyroscope: list[float] = Field(..., min_items=3, max_items=3)
    overlay: float
    proximity: float
    touch_event: bool = False
    motion_delta: float = 0.0


class HeartbeatIn(BaseModel):
    device_id: str = Field(..., max_length=64)
    payload: SensorPayload


class HeartbeatAck(BaseModel):
    status: str = "queued"
    trust_hint: Optional[int] = None


class TrustScore(BaseModel):
    device_id: str
    score: int
    verdict: str


class AuditLogOut(BaseModel):
    id: int
    user_id: str
    device_id: str
    threat_level: str
    reason: str
    created_at: str

    class Config:
        orm_mode = True
