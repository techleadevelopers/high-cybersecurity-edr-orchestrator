from functools import lru_cache
from pydantic import BaseSettings, AnyHttpUrl, Field
from typing import List, Optional


class Settings(BaseSettings):
    app_name: str = "BlockRemote API"
    environment: str = Field(default="development", env="ENVIRONMENT")
    debug: bool = Field(default=False, env="DEBUG")

    database_url: str = Field(..., env="DATABASE_URL")
    redis_url: str = Field(..., env="REDIS_URL")

    jwt_secret_key: str = Field(..., env="JWT_SECRET_KEY")
    jwt_algorithm: str = Field(default="HS256", env="JWT_ALGORITHM")
    jwt_expire_minutes: int = Field(default=15, env="JWT_EXPIRE_MINUTES")

    mtls_ca_cert: Optional[str] = Field(default=None, env="MTLS_CA_CERT")

    cors_origins: List[AnyHttpUrl] = Field(default_factory=list, env="CORS_ORIGINS")

    billing_webhook_secret: str = Field(..., env="BILLING_WEBHOOK_SECRET")

    class Config:
        case_sensitive = True
        env_file = ".env"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
