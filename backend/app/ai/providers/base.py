"""Shared contracts for LLM providers.

Business logic depends on :class:`LLMProvider` and the message/response
dataclasses in this module. Vendor SDKs, HTTP details, and error handling stay
inside the concrete provider modules.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal


ChatRole = Literal["system", "user", "assistant", "tool"]

VALID_CHAT_ROLES: frozenset[str] = frozenset(
    {"system", "user", "assistant", "tool"}
)

TOOL_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,63}$")


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """A provider-neutral declaration of one executable backend tool.

    The tool schema is owned by ``app.tools``. Providers only translate this
    declaration into their vendor-specific request format.
    """

    name: str
    description: str
    parameters: dict[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not TOOL_NAME_PATTERN.match(
            self.name
        ):
            raise ValueError(f"Invalid tool name: {self.name!r}")
        if not isinstance(self.description, str) or not self.description.strip():
            raise ValueError("Tool description must not be blank")
        if not isinstance(self.parameters, dict):
            raise ValueError("Tool parameters must be a JSON schema object")
        object.__setattr__(self, "parameters", dict(self.parameters))


@dataclass(frozen=True, slots=True)
class ToolCall:
    """One tool invocation requested by a model.

    ``arguments`` are untrusted model output. They must be validated against
    the registered tool schema before any backend function is executed.
    ``provider_data`` carries opaque continuation values such as Gemini thought
    signatures; it is never exposed to the customer or persisted.
    """

    id: str
    name: str
    arguments: dict[str, Any]
    provider_data: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id.strip():
            raise ValueError("Tool call id must not be blank")
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Tool call name must not be blank")
        if not isinstance(self.arguments, dict):
            raise ValueError("Tool call arguments must be an object")
        object.__setattr__(self, "arguments", dict(self.arguments))
        if self.provider_data is not None:
            object.__setattr__(
                self,
                "provider_data",
                dict(self.provider_data),
            )


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """One provider-neutral chat message."""

    role: ChatRole
    content: str
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None
    tool_name: str | None = None

    def __post_init__(self) -> None:
        if self.role not in VALID_CHAT_ROLES:
            raise ValueError(f"Unsupported chat role: {self.role!r}")
        if not isinstance(self.content, str):
            raise ValueError("Chat message content must be a string")
        if not isinstance(self.tool_calls, tuple):
            object.__setattr__(self, "tool_calls", tuple(self.tool_calls))

        if self.tool_calls and self.role != "assistant":
            raise ValueError("Only assistant messages may request tool calls")
        if self.role == "assistant":
            if not self.content.strip() and not self.tool_calls:
                raise ValueError(
                    "Assistant messages must contain text or tool calls"
                )
        elif not self.content.strip():
            raise ValueError("Chat message content must not be blank")

        if self.role == "tool":
            if not self.tool_call_id or not self.tool_call_id.strip():
                raise ValueError("Tool results require a tool call id")
            if not self.tool_name or not self.tool_name.strip():
                raise ValueError("Tool results require a tool name")
        elif self.tool_call_id is not None or self.tool_name is not None:
            raise ValueError(
                "Only tool result messages may carry tool call metadata"
            )


@dataclass(frozen=True, slots=True)
class LLMResponse:
    """Normalized content returned by any provider."""

    content: str
    provider: str
    model: str
    finish_reason: str | None = None
    usage: dict[str, int] | None = None
    tool_calls: tuple[ToolCall, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.content, str):
            raise ValueError("LLM response content must be a string")
        if not isinstance(self.tool_calls, tuple):
            object.__setattr__(self, "tool_calls", tuple(self.tool_calls))
        if not self.content.strip() and not self.tool_calls:
            raise ValueError(
                "LLM response must contain text or at least one tool call"
            )


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
    async def generate(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolDefinition] | None = None,
    ) -> LLMResponse:
        """Generate one assistant reply from a complete chat history.

        When ``tools`` is supplied, the provider may return tool calls instead
        of, or in addition to, customer-visible text. The application validates
        and executes those calls; models never execute backend code directly.
        """

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

    async def generate(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolDefinition] | None = None,
    ) -> LLMResponse:
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
        if not content and not (
            message.role == "assistant" and message.tool_calls
        ):
            raise ProviderInvalidRequestError(
                "Chat messages must not be blank.",
                provider="unknown",
            )
        normalized.append(
            ChatMessage(
                role=message.role,
                content=content,
                tool_calls=message.tool_calls,
                tool_call_id=message.tool_call_id,
                tool_name=message.tool_name,
            )
        )

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
