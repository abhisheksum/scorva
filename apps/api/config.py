import json
from typing import List, Literal, Union
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Platform configuration settings loaded from environment variables."""

    # General Environment
    SCORVA_ENV: Literal["development", "test", "staging", "production"] = "development"
    DEBUG: bool = True
    PORT: int = 8000
    HOST: str = "0.0.0.0"

    # API & CORS
    API_V1_PREFIX: str = "/api/v1"
    CORS_ORIGINS: Union[List[str], str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    # Security & Encryption
    SECRET_KEY: str = "insecure-development-secret-key-change-in-production-min-32-chars"
    ENCRYPTION_MASTER_KEY: str = "insecure-encryption-key-for-dev-only-32bytes!"
    SESSION_COOKIE_NAME: str = "scorva_session"
    SESSION_TTL_SECONDS: int = 43200
    SESSION_COOKIE_SECURE: bool = False
    SESSION_COOKIE_SAMESITE: Literal["lax", "strict", "none"] = "lax"

    # MFA Configuration
    MFA_ENROLLMENT_TTL_SECONDS: int = 600
    MFA_CHALLENGE_TTL_SECONDS: int = 300
    MFA_MAX_ATTEMPTS: int = 5

    # Reverse Proxy
    TRUSTED_PROXIES: Union[List[str], str] = ["127.0.0.1", "::1"]

    # Dependencies (Configured for future phases)
    DATABASE_URL: str = "postgresql+asyncpg://scorva:scorva_dev_password@localhost:5432/scorva"
    REDIS_URL: str = "redis://localhost:6379/0"
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    S3_ENDPOINT_URL: str = "http://localhost:9000"

    @field_validator("CORS_ORIGINS", "TRUSTED_PROXIES", mode="before")
    @classmethod
    def assemble_origins_and_proxies(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str):
            clean_v = v.strip()
            # If it's valid JSON array, parse directly
            if clean_v.startswith("[") and clean_v.endswith("]"):
                try:
                    parsed = json.loads(clean_v)
                    if isinstance(parsed, list):
                        return [str(item).strip() for item in parsed if item]
                except Exception:
                    clean_v = clean_v[1:-1].strip()
            return [i.strip().strip("'\"") for i in clean_v.split(",") if i.strip().strip("'\"")]
        elif isinstance(v, list):
            return [str(item).strip() for item in v if item]
        raise ValueError("Invalid format for list parameter")

    @model_validator(mode="after")
    def validate_production_security(self) -> "Settings":
        if self.SCORVA_ENV == "production":
            if self.DEBUG:
                raise ValueError("DEBUG mode must be False in production.")
            if not self.SESSION_COOKIE_SECURE:
                raise ValueError("SESSION_COOKIE_SECURE must be True in production.")
            if len(self.SECRET_KEY) < 32 or any(
                term in self.SECRET_KEY.lower() for term in ["insecure", "change-in-production", "development"]
            ):
                raise ValueError(
                    "SECRET_KEY must be a cryptographically random string (min 32 chars) and not a development default."
                )
            if len(self.ENCRYPTION_MASTER_KEY) < 32 or any(
                term in self.ENCRYPTION_MASTER_KEY.lower() for term in ["insecure", "dev-only", "development"]
            ):
                raise ValueError(
                    "ENCRYPTION_MASTER_KEY must be a cryptographically random string (min 32 chars) and not a development default."
                )
            if "scorva_dev_password" in self.DATABASE_URL:
                raise ValueError("DATABASE_URL must not use the default development password in production.")
            for origin in self.CORS_ORIGINS:
                if origin == "*":
                    raise ValueError("CORS_ORIGINS must not use wildcard '*' when credentials are supported.")
        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()
