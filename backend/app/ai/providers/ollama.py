"""Local Ollama provider using the native ``/api/chat`` HTTP endpoint."""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from typing import Any

import httpx

from app.ai.providers.base import (
    ChatMessage,
    LLMProvider,
    LLMResponse,
    ProviderConfigurationError,
    ProviderInvalidRequestError,
    ProviderInvalidResponseError,
    ProviderModelNotFoundError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    ToolCall,
    ToolDefinition,
    normalize_messages,
)

DEFAULT_OLLAMA_MODEL = "llama3.2:3b"

logger = logging.getLogger(__name__)


class OllamaProvider(LLMProvider):
    """Generate replies from a locally running Ollama server."""

    name = "ollama"

    def __init__(
        self,
        *,
        base_url: str = "http://localhost:11434",
        model: str = DEFAULT_OLLAMA_MODEL,
        timeout: int = 60,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        normalized_base_url = base_url.strip().rstrip("/")
        if not normalized_base_url.startswith(("http://", "https://")):
            raise ProviderConfigurationError(
                "OLLAMA_BASE_URL must start with http:// or https://.",
                provider=self.name,
            )

        normalized_model = model.strip()
        if not normalized_model:
            raise ProviderConfigurationError(
                "OLLAMA_MODEL is not configured.",
                provider=self.name,
            )

        self.base_url = normalized_base_url
        self.model = normalized_model
        self.timeout = timeout
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
        )

    async def generate(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolDefinition] | None = None,
    ) -> LLMResponse:
        normalized = normalize_messages(messages)
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                self._message_payload(message) for message in normalized
            ],
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "num_predict": self.max_tokens,
            },
        }
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": definition.name,
                        "description": definition.description,
                        "parameters": definition.parameters,
                    },
                }
                for definition in tools
            ]

        try:
            response = await self._client.post(
                f"{self.base_url}/api/chat",
                json=payload,
            )
        except (TimeoutError, httpx.TimeoutException) as error:
            raise ProviderTimeoutError(
                "Ollama did not respond in time.",
                provider=self.name,
            ) from error
        except httpx.RequestError as error:
            raise ProviderUnavailableError(
                "Ollama is not reachable. Start it and try again.",
                provider=self.name,
            ) from error

        if response.status_code == 404:
            detail = self._error_detail(response)
            logger.warning("Ollama returned HTTP 404: %s", detail[:500])
            raise ProviderModelNotFoundError(
                f"Ollama model '{self.model}' is not available. "
                f"Pull it with `ollama pull {self.model}`.",
                provider=self.name,
            )
        if response.status_code == 429:
            raise ProviderRateLimitError(
                "Ollama rate limit reached. Try again shortly.",
                provider=self.name,
            )
        if response.status_code >= 500:
            logger.warning(
                "Ollama returned HTTP %s: %s",
                response.status_code,
                self._error_detail(response)[:500],
            )
            raise ProviderUnavailableError(
                "Ollama is temporarily unavailable.",
                provider=self.name,
            )
        if response.status_code >= 400:
            logger.warning(
                "Ollama returned HTTP %s: %s",
                response.status_code,
                self._error_detail(response)[:500],
            )
            raise ProviderInvalidRequestError(
                "Ollama rejected the request.",
                provider=self.name,
            )

        try:
            body = response.json()
        except ValueError as error:
            raise ProviderInvalidResponseError(
                "Ollama returned invalid JSON.",
                provider=self.name,
            ) from error

        message = body.get("message") if isinstance(body, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        tool_calls = (
            self._response_tool_calls(message)
            if isinstance(message, dict)
            else ()
        )
        if (not isinstance(content, str) or not content.strip()) and not (
            tool_calls
        ):
            raise ProviderInvalidResponseError(
                "Ollama returned an empty response.",
                provider=self.name,
            )

        model = body.get("model") if isinstance(body, dict) else None
        finish_reason = body.get("done_reason") if isinstance(body, dict) else None
        return LLMResponse(
            content=content.strip() if isinstance(content, str) else "",
            provider=self.name,
            model=model if isinstance(model, str) and model.strip() else self.model,
            finish_reason=(
                finish_reason
                if isinstance(finish_reason, str) and finish_reason.strip()
                else "stop"
            ),
            usage=self._usage(body),
            tool_calls=tool_calls,
        )

    @staticmethod
    def _message_payload(message: ChatMessage) -> dict[str, Any]:
        """Translate a provider-neutral message into Ollama chat format."""
        if message.role == "tool":
            return {
                "role": "tool",
                "tool_name": message.tool_name,
                "content": message.content,
            }

        payload: dict[str, Any] = {
            "role": {
                "assistant": "assistant",
                "system": "system",
            }.get(message.role, "user"),
            "content": message.content,
        }
        if message.tool_calls:
            payload["tool_calls"] = [
                {
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": call.arguments,
                    },
                }
                for call in message.tool_calls
            ]
        return payload

    @staticmethod
    def _response_tool_calls(message: dict[str, Any]) -> tuple[ToolCall, ...]:
        raw_calls = message.get("tool_calls")
        if not isinstance(raw_calls, list):
            return ()

        calls: list[ToolCall] = []
        for index, raw_call in enumerate(raw_calls):
            if not isinstance(raw_call, dict):
                continue
            function = raw_call.get("function")
            if not isinstance(function, dict):
                continue
            name = function.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            arguments = function.get("arguments")
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except ValueError:
                    logger.warning(
                        "Ollama returned invalid JSON arguments for tool %r",
                        name,
                    )
                    continue
            if arguments is None:
                arguments = {}
            if not isinstance(arguments, dict):
                logger.warning(
                    "Ollama returned non-object arguments for tool %r",
                    name,
                )
                continue
            raw_id = raw_call.get("id")
            call_id = (
                raw_id.strip()
                if isinstance(raw_id, str) and raw_id.strip()
                else f"call_{index + 1}"
            )
            calls.append(
                ToolCall(
                    id=call_id,
                    name=name.strip(),
                    arguments=arguments,
                )
            )
        return tuple(calls)

    @staticmethod
    def _error_detail(response: httpx.Response) -> str:
        try:
            body = response.json()
        except ValueError:
            return response.text
        if isinstance(body, dict):
            detail = body.get("error") or body.get("message")
            if isinstance(detail, str):
                return detail
        return str(body)

    @staticmethod
    def _usage(body: Any) -> dict[str, int] | None:
        if not isinstance(body, dict):
            return None

        usage: dict[str, int] = {}
        for source, target in (
            ("prompt_eval_count", "input_tokens"),
            ("eval_count", "output_tokens"),
        ):
            value = body.get(source)
            if isinstance(value, int):
                usage[target] = value
        if usage:
            usage["total_tokens"] = sum(usage.values())
        return usage or None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
