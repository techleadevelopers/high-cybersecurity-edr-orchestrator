from functools import lru_cache
from pydantic import BaseSettings, AnyHttpUrl, Field
from typing import List, Optional


class Settings(BaseSettings):
    app_name: str = "BlockRemote API"
    environment: str = Field(default="development", env="ENVIRONMENT")
    debug: bool = Field(default=False, env="DEBUG")

    database_url: str = Field(..., env="DATABASE_URL")
    redis_url: str = Field(..., env="REDIS_URL")

    # JWT / JWKS
    jwt_secret_key: Optional[str] = Field(default=None, env="JWT_SECRET_KEY")  # legacy HS256 only for dev
    jwt_private_key: Optional[str] = Field(default=None, env="JWT_PRIVATE_KEY_PEM")  # used only in dev; prod should rely on KMS/HSM
    jwt_public_key: Optional[str] = Field(default=None, env="JWT_PUBLIC_KEY_PEM")  # fallback when JWKS unavailable
    jwks_url: Optional[str] = Field(default=None, env="JWKS_URL")
    jwks_cache_ttl_seconds: int = Field(default=300, env="JWKS_CACHE_TTL_SECONDS")
    jwt_algorithm: str = Field(default="RS256", env="JWT_ALGORITHM")
    jwt_expire_minutes: int = Field(default=15, env="JWT_EXPIRE_MINUTES")
    jwt_issuer: Optional[str] = Field(default=None, env="JWT_ISSUER")
    jwt_audience: Optional[str] = Field(default=None, env="JWT_AUDIENCE")
    jwt_clock_skew_seconds: int = Field(default=30, env="JWT_CLOCK_SKEW_SECONDS")
    jwt_active_kid: Optional[str] = Field(default=None, env="JWT_ACTIVE_KID")

    # Refresh / fingerprinting
    refresh_fingerprint_secret: Optional[str] = Field(default=None, env="REFRESH_FINGERPRINT_SECRET")
    refresh_base_ttl_minutes: int = Field(default=60 * 24 * 7, env="REFRESH_BASE_TTL_MINUTES")
    refresh_max_ttl_minutes: int = Field(default=60 * 24 * 14, env="REFRESH_MAX_TTL_MINUTES")
    refresh_extend_minutes: int = Field(default=60 * 24, env="REFRESH_EXTEND_MINUTES")

    mtls_ca_cert: Optional[str] = Field(default=None, env="MTLS_CA_CERT")

    cors_origins: List[AnyHttpUrl] = Field(default_factory=list, env="CORS_ORIGINS")
    ws_allowed_origins: List[AnyHttpUrl] = Field(default_factory=list, env="WS_ALLOWED_ORIGINS")
    ws_rate_limit_window: int = Field(default=60, env="WS_RATE_LIMIT_WINDOW")
    ws_rate_limit_max: int = Field(default=20, env="WS_RATE_LIMIT_MAX")

    billing_webhook_secret: str = Field(..., env="BILLING_WEBHOOK_SECRET")
    play_integrity_api_key: Optional[str] = Field(default=None, env="PLAY_INTEGRITY_API_KEY")
    app_attest_validator_url: Optional[str] = Field(default=None, env="APP_ATTEST_VALIDATOR_URL")
    grpc_port: int = Field(default=50051, env="GRPC_PORT")

    class Config:
        case_sensitive = True
        env_file = ".env"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
