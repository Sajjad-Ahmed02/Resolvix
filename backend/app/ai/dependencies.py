"""FastAPI dependencies for LLM access."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from app.ai.factory import create_provider
from app.ai.providers.base import (
    LLMProvider,
    ProviderConfigurationError,
    UnavailableProvider,
)

logger = logging.getLogger(__name__)


async def get_llm_provider() -> AsyncIterator[LLMProvider]:
    """Yield the configured provider and close its resources afterwards.

    Configuration errors are logged once per request and replaced with a
    provider that raises a normalized error on use. The chat service turns
    that error into a persisted fallback reply instead of an HTTP 500.
    """
    try:
        provider = create_provider()
    except ProviderConfigurationError as error:
        logger.error("LLM provider configuration error: %s", error)
        provider = UnavailableProvider(str(error))

    try:
        yield provider
    finally:
        await provider.aclose()
