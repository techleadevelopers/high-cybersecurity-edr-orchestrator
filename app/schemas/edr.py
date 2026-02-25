from pydantic import BaseModel, Field
from typing import List, Optional

class SuspiciousApp(BaseModel):
    package: str
    hash_sha256: str
    sideloaded: bool = False

class DnsLog(BaseModel):
    domain: str
    ip: str

class EdrReportIn(BaseModel):
    device_id: str = Field(..., max_length=64)
    suspicious_apps: List[SuspiciousApp] = Field(default_factory=list)
    dangerous_permissions: List[str] = Field(default_factory=list)
    dns_logs: Optional[List[DnsLog]] = None

class EdrReportOut(BaseModel):
    device_id: str
    risk_score: int
    risk_level: str
    actions: List[str]
