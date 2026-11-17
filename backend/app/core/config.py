from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator
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

    # Active provider: gemini (hosted) or ollama (local inference).
    LLM_PROVIDER: str = "gemini"

    # Gemini model identifier. Ollama uses OLLAMA_MODEL instead.
    LLM_MODEL: str = "gemini-3.5-flash-lite"

    # Generic API key fallback for providers without a dedicated variable.
    # Gemini prefers GEMINI_API_KEY.
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = ""

    # Generation settings
    LLM_TIMEOUT: int = Field(default=60, ge=1, le=300)
    LLM_TEMPERATURE: float = Field(default=0.7, ge=0.0, le=2.0)
    LLM_MAX_TOKENS: int = Field(default=2048, ge=1, le=32768)

    # ==========================================
    # OLLAMA CONFIGURATION
    # ==========================================

    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3.2:3b"

    # ==========================================
    # KNOWLEDGE / RAG CONFIGURATION
    # ==========================================

    # Local sentence-transformers model. The knowledge_chunks column is
    # vector(384), so a different model must also produce 384 dimensions.
    EMBEDDING_MODEL: str = "sentence-transformers/all-MiniLM-L6-v2"
    EMBEDDING_DEVICE: str = "cpu"
    EMBEDDING_BATCH_SIZE: int = Field(default=32, ge=1, le=256)

    # Chunk sizes are measured in model tokens. The model maximum is 256
    # tokens; ingestion rejects settings that exceed it.
    KNOWLEDGE_CHUNK_MAX_TOKENS: int = Field(default=200, ge=32, le=512)
    KNOWLEDGE_CHUNK_OVERLAP_TOKENS: int = Field(default=40, ge=0, le=256)

    # Retrieval returns the nearest chunks. A cosine distance of 0.0 is an
    # exact match; 2.0 is the opposite direction.
    RAG_TOP_K: int = Field(default=4, ge=1, le=20)
    RAG_MAX_DISTANCE: float = Field(default=0.7, ge=0.0, le=2.0)

    # ==========================================
    # SUPPORT AGENT ORCHESTRATION
    # ==========================================

    # Number of recent message rows loaded before building the bounded model
    # history. Tool messages are included so follow-up routing can recover the
    # last successfully looked-up order.
    AGENT_CONTEXT_MESSAGE_LIMIT: int = Field(default=100, ge=10, le=500)

    # Bounded conversation window sent to the provider. Oldest turns are
    # dropped first, and an oversized newest turn is truncated.
    AGENT_MAX_HISTORY_MESSAGES: int = Field(default=40, ge=2, le=200)
    AGENT_MAX_HISTORY_CHARS: int = Field(default=12000, ge=1000, le=100000)

    # Hard limits for the model -> validate -> execute -> tool-result loop.
    AGENT_MAX_TOOL_ROUNDS: int = Field(default=3, ge=1, le=10)
    AGENT_MAX_TOOL_CALLS: int = Field(default=6, ge=1, le=20)

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

    @field_validator("LLM_PROVIDER")
    @classmethod
    def normalize_llm_provider(cls, value: str) -> str:
        """Accept provider names regardless of case or surrounding spaces."""
        return value.strip().lower()

    @field_validator("EMBEDDING_MODEL", "EMBEDDING_DEVICE")
    @classmethod
    def normalize_embedding_settings(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Embedding settings must not be blank")
        return normalized

    @model_validator(mode="after")
    def validate_chunk_settings(self) -> "Settings":
        if self.KNOWLEDGE_CHUNK_OVERLAP_TOKENS >= self.KNOWLEDGE_CHUNK_MAX_TOKENS:
            raise ValueError(
                "KNOWLEDGE_CHUNK_OVERLAP_TOKENS must be smaller than "
                "KNOWLEDGE_CHUNK_MAX_TOKENS"
            )
        return self


# Global settings instance
settings = Settings()
