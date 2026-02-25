from fastapi import APIRouter
from app.api.v1 import signals, security, security_priority, audit, billing, auth, edr

api_router = APIRouter(prefix="/v1")
api_router.include_router(signals.router, prefix="/signals", tags=["signals"])
api_router.include_router(security.router, prefix="/security", tags=["security"])
api_router.include_router(security_priority.router, prefix="/security", tags=["security-priority"])
api_router.include_router(audit.router, prefix="/audit", tags=["audit"])
api_router.include_router(billing.router, prefix="/billing", tags=["billing"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(edr.router, prefix="/edr", tags=["edr"])
