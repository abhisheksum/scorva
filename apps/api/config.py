import json
from typing import List, Literal, Union
from pydantic import field_validator
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

    # Security
    SECRET_KEY: str = "insecure-development-secret-key-change-in-production-min-32-chars"
    SESSION_COOKIE_NAME: str = "scorva_session"
    SESSION_TTL_SECONDS: int = 43200

    # Dependencies (Configured for future phases)
    DATABASE_URL: str = "postgresql+asyncpg://scorva:scorva_dev_password@localhost:5432/scorva"
    REDIS_URL: str = "redis://localhost:6379/0"
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    S3_ENDPOINT_URL: str = "http://localhost:9000"

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str):
            if v.strip().startswith("[") and v.strip().endswith("]"):
                try:
                    return json.loads(v)
                except Exception:
                    pass
            return [i.strip() for i in v.split(",") if i.strip()]
        elif isinstance(v, list):
            return v
        raise ValueError("Invalid CORS_ORIGINS format")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()
