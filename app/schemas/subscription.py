from pydantic import BaseModel, Field
import datetime as dt


class PlanOut(BaseModel):
    code: str
    name: str
    price_cents: int
    currency: str
    features: dict

    class Config:
        orm_mode = True


class SubscriptionOut(BaseModel):
    user_id: str
    device_id: str
    plan_code: str
    status: str
    plan_tier: str
    expires_at: dt.datetime | None

    class Config:
        orm_mode = True


class BillingWebhookIn(BaseModel):
    provider: str = Field(..., max_length=32)
    event_id: str = Field(..., max_length=128)
    user_id: str = Field(..., max_length=64)
    device_id: str = Field(..., max_length=64)
    plan_code: str = Field(..., max_length=32)
    plan_tier: str = Field(..., max_length=16)
    status: str = Field(..., max_length=16)
    expires_at: dt.datetime | None = None
    auto_renew: bool = True
    payload: dict = Field(default_factory=dict)


class BillingStatusOut(BaseModel):
    user_id: str
    device_id: str
    is_premium: bool
    trial_expired: bool
    trial_started_at: dt.datetime
    now: dt.datetime


class AttestationPayload(BaseModel):
    type: str
    nonce: str
    public_key: str
    valid: bool = True
    risk_reason: str | None = None


class BillingStatusIn(BaseModel):
    device_id: str = Field(..., max_length=64)
    attestation: AttestationPayload | None = None
