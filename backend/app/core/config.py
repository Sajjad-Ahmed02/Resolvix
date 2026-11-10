
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):

    # ==========================================
    # APPLICATION CONFIGURATION
    # ==========================================

    APP_NAME: str = "Resolvix"
    APP_ENV: str = "development"
    DEBUG: bool = True


    # ==========================================
    # DATABASE CONFIGURATION
    # ==========================================

    DATABASE_URL: str


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
        extra="ignore"
    )


# Global settings instance
settings = Settings()
