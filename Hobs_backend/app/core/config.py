from pydantic_settings import BaseSettings
from pydantic import field_validator


class Settings(BaseSettings):
    # Core
    PROJECT_NAME: str = "HoBS"
    API_V1_STR: str = "/api/v1"

    # Database
    DATABASE_URL: str

    # Redis (REQUIRED)
    REDIS_URL: str

    # Paystack
    PAYSTACK_SECRET_KEY: str = ""
    PAYSTACK_WEBHOOK_SECRET: str = ""
    PAYSTACK_REDIRECT_URL: str = ""

    # Auth / JWT
    SECRET_KEY: str = "change-me-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 2   # 2 hours

    # Internal team email — receives merchant application alerts
    TEAM_EMAIL: str = ""

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def fix_database_url(cls, v: str) -> str:
        if not v:
            raise ValueError("DATABASE_URL missing")

        if v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql+asyncpg://", 1)

        if v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)

        return v

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()

# Crash at startup if the default or a weak secret key is used outside of
# local dev. Only ENVIRONMENT=local bypasses this — never set that on
# Railway or any hosted env. SECRET_KEY signs every JWT this app issues, so
# a short key is brute-forceable, same reasoning as the ADMIN_SECRET check.
import os as _os
_env = _os.getenv("ENVIRONMENT", "production").lower()
if _env != "local":
    if settings.SECRET_KEY == "change-me-in-production":
        raise RuntimeError(
            "SECRET_KEY is still the default value. "
            "Set a secure SECRET_KEY in Railway environment variables."
        )
    if len(settings.SECRET_KEY) < 32:
        raise RuntimeError(
            f"SECRET_KEY is too short ({len(settings.SECRET_KEY)} chars). Minimum is 32. "
            "Generate one with: python3 -c \"import secrets; print(secrets.token_urlsafe(32))\""
        )