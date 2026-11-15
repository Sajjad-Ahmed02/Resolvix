"""Shared contracts for LLM providers.

Business logic depends on :class:`LLMProvider` and the message/response
dataclasses in this module. Vendor SDKs, HTTP details, and error handling stay
inside the concrete provider modules.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

ChatRole = Literal["system", "user", "assistant", "tool"]

VALID_CHAT_ROLES: frozenset[str] = frozenset(
    {"system", "user", "assistant", "tool"}
)


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """One provider-neutral chat message."""

    role: ChatRole
    content: str

    def __post_init__(self) -> None:
        if self.role not in VALID_CHAT_ROLES:
            raise ValueError(f"Unsupported chat role: {self.role!r}")
        if not isinstance(self.content, str) or not self.content.strip():
            raise ValueError("Chat message content must not be blank")


@dataclass(frozen=True, slots=True)
class LLMResponse:
    """Normalized content returned by any provider."""

    content: str
    provider: str
    model: str
    finish_reason: str | None = None
    usage: dict[str, int] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.content, str) or not self.content.strip():
            raise ValueError("LLM response content must not be blank")


class ProviderError(Exception):
    """Base class for safe, normalized provider failures.

    The message is suitable for server logs and fallback metadata. Raw vendor
    response bodies are never included in API responses.
    """

    code = "provider_error"
    default_message = "The AI provider could not complete the request."

    def __init__(
        self,
        message: str | None = None,
        *,
        provider: str = "unknown",
    ) -> None:
        self.provider = provider
        self.safe_message = message or self.default_message
        super().__init__(self.safe_message)


class ProviderConfigurationError(ProviderError):
    code = "configuration_error"
    default_message = "The AI provider is not configured correctly."


class ProviderAuthenticationError(ProviderError):
    code = "authentication_error"
    default_message = "The AI provider rejected its credentials."


class ProviderRateLimitError(ProviderError):
    code = "rate_limit"
    default_message = "The AI provider is rate limited. Try again shortly."


class ProviderTimeoutError(ProviderError):
    code = "timeout"
    default_message = "The AI provider did not respond in time."


class ProviderUnavailableError(ProviderError):
    code = "unavailable"
    default_message = "The AI provider is temporarily unavailable."


class ProviderModelNotFoundError(ProviderError):
    code = "model_not_found"
    default_message = "The requested AI model is not available."


class ProviderInvalidRequestError(ProviderError):
    code = "invalid_request"
    default_message = "The AI provider rejected the request."


class ProviderInvalidResponseError(ProviderError):
    code = "invalid_response"
    default_message = "The AI provider returned an invalid response."


class LLMProvider(ABC):
    """Common async interface implemented by every model vendor."""

    name: str
    model: str

    @abstractmethod
    async def generate(self, messages: Sequence[ChatMessage]) -> LLMResponse:
        """Generate one assistant reply from a complete chat history."""

    async def aclose(self) -> None:
        """Release provider resources. The default implementation is a no-op."""

    async def __aenter__(self) -> "LLMProvider":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.aclose()


class UnavailableProvider(LLMProvider):
    """Provider used when configuration is invalid.

    Raising a normalized error on first use lets the conversation service
    persist a controlled fallback reply instead of returning an HTTP 500.
    """

    name = "unavailable"
    model = ""

    def __init__(self, reason: str) -> None:
        self._reason = reason

    async def generate(self, messages: Sequence[ChatMessage]) -> LLMResponse:
        raise ProviderConfigurationError(self._reason, provider=self.name)


def normalize_messages(
    messages: Sequence[ChatMessage],
) -> list[ChatMessage]:
    """Trim messages and reject empty provider input."""
    if not messages:
        raise ProviderInvalidRequestError(
            "At least one chat message is required.",
            provider="unknown",
        )

    normalized: list[ChatMessage] = []
    for message in messages:
        content = message.content.strip()
        if not content:
            raise ProviderInvalidRequestError(
                "Chat messages must not be blank.",
                provider="unknown",
            )
        normalized.append(ChatMessage(role=message.role, content=content))

    if not any(message.role != "system" for message in normalized):
        raise ProviderInvalidRequestError(
            "At least one non-system message is required.",
            provider="unknown",
        )
    return normalized


def split_system_messages(
    messages: Sequence[ChatMessage],
) -> tuple[str | None, list[ChatMessage]]:
    """Separate system instructions from the provider dialogue."""
    system_parts = [
        message.content for message in messages if message.role == "system"
    ]
    dialogue = [message for message in messages if message.role != "system"]
    system_instruction = "\n\n".join(system_parts) if system_parts else None
    return system_instruction, dialogue
