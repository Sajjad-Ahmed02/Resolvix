"""Select and construct the configured LLM provider."""

from __future__ import annotations

from app.ai.providers.base import (
    LLMProvider,
    ProviderConfigurationError,
)
from app.ai.providers.gemini import DEFAULT_GEMINI_MODEL, GeminiProvider
from app.ai.providers.ollama import OllamaProvider
from app.core.config import Settings, settings


def create_provider(config: Settings | None = None) -> LLMProvider:
    """Build the provider selected by ``LLM_PROVIDER``.

    Invalid or incomplete configuration raises
    :class:`ProviderConfigurationError`. The FastAPI dependency converts that
    into a provider that returns a controlled fallback at request time.
    """
    active = config or settings
    provider_name = (active.LLM_PROVIDER or "").strip().lower()

    if provider_name == "gemini":
        api_key = (
            (active.GEMINI_API_KEY or "").strip()
            or (active.LLM_API_KEY or "").strip()
        )
        if not api_key:
            raise ProviderConfigurationError(
                "GEMINI_API_KEY is not configured.",
                provider="gemini",
            )
        model = (active.LLM_MODEL or "").strip() or DEFAULT_GEMINI_MODEL
        return GeminiProvider(
            api_key=api_key,
            model=model,
            timeout=active.LLM_TIMEOUT,
            temperature=active.LLM_TEMPERATURE,
            max_tokens=active.LLM_MAX_TOKENS,
        )

    if provider_name == "ollama":
        model = (active.OLLAMA_MODEL or "").strip()
        if not model:
            raise ProviderConfigurationError(
                "OLLAMA_MODEL is not configured.",
                provider="ollama",
            )
        return OllamaProvider(
            base_url=active.OLLAMA_BASE_URL,
            model=model,
            timeout=active.LLM_TIMEOUT,
            temperature=active.LLM_TEMPERATURE,
            max_tokens=active.LLM_MAX_TOKENS,
        )

    raise ProviderConfigurationError(
        "LLM_PROVIDER must be 'gemini' or 'ollama'.",
        provider=provider_name or "unknown",
    )
