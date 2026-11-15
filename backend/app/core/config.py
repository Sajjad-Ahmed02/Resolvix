from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central application configuration, loaded from environment variables.

    Values in ``backend/.env`` provide local development defaults. Real
    environment variables always take precedence over the file. Secrets are
    never committed: ``.env`` is gitignored and ``.env.example`` documents the
    required keys with safe placeholders.
    """

    # ==========================================
    # APPLICATION CONFIGURATION
    # ==========================================

    APP_NAME: str = "Resolvix"
    APP_VERSION: str = "0.2.0"
    APP_ENV: str = "development"
    DEBUG: bool = True

    # ==========================================
    # DATABASE CONFIGURATION
    # ==========================================

    DATABASE_URL: str

    # Seconds to wait for a new PostgreSQL connection before failing.
    DB_CONNECT_TIMEOUT: int = Field(default=5, ge=1, le=60)

    # ==========================================
    # AUTHENTICATION CONFIGURATION
    # ==========================================

    # Required. Generate with:
    #   python -c "import secrets; print(secrets.token_urlsafe(48))"
    JWT_SECRET_KEY: str = Field(min_length=32)
    JWT_ALGORITHM: Literal["HS256", "HS384", "HS512"] = "HS256"
    JWT_ISSUER: str = "resolvix"
    JWT_AUDIENCE: str = "resolvix-api"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=30, ge=1, le=1440)

    # ==========================================
    # CORS CONFIGURATION
    # ==========================================

    # Vite's default development origin. Add deployed origins explicitly;
    # credentials are allowed, so "*" is not appropriate.
    CORS_ORIGINS: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    # ==========================================
    # LLM CONFIGURATION
    # ==========================================

    # Active provider: gemini, ollama, openai,
    # openrouter, groq, or another supported provider.

    LLM_PROVIDER: str = "gemini"

    # Model identifier for the active provider
    LLM_MODEL: str = ""

    # Generic API credentials and endpoint
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = ""

    # Generation settings
    LLM_TIMEOUT: int = 60
    LLM_TEMPERATURE: float = 0.7
    LLM_MAX_TOKENS: int = 2048

    # ==========================================
    # OLLAMA CONFIGURATION
    # ==========================================

    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3.2"

    # ==========================================
    # PROVIDER-SPECIFIC API KEYS
    # ==========================================

    GEMINI_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    OPENROUTER_API_KEY: str = ""
    GROQ_API_KEY: str = ""

    # ==========================================
    # PYDANTIC SETTINGS
    # ==========================================

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("JWT_SECRET_KEY")
    @classmethod
    def validate_jwt_secret(cls, value: str) -> str:
        """Reject obvious placeholders before the API can start."""
        normalized = value.strip()
        if normalized != value:
            raise ValueError("JWT_SECRET_KEY must not start or end with whitespace")
        if normalized.lower().startswith(("replace", "change-me", "changeme")):
            raise ValueError(
                "JWT_SECRET_KEY still contains a placeholder; generate a "
                "random secret instead"
            )
        return normalized


# Global settings instance
settings = Settings()
