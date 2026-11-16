"""Google Gemini provider backed by the official ``google-genai`` SDK."""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from typing import Any

import httpx
from google import genai
from google.genai import errors, types

from app.ai.providers.base import (
    ChatMessage,
    LLMProvider,
    LLMResponse,
    ProviderAuthenticationError,
    ProviderConfigurationError,
    ProviderError,
    ProviderInvalidRequestError,
    ProviderInvalidResponseError,
    ProviderModelNotFoundError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    ToolCall,
    ToolDefinition,
    normalize_messages,
    split_system_messages,
)

DEFAULT_GEMINI_MODEL = "gemini-3.5-flash-lite"

logger = logging.getLogger(__name__)


class GeminiProvider(LLMProvider):
    """Generate replies with the Gemini Developer API."""

    name = "gemini"

    def __init__(
        self,
        *,
        api_key: str = "",
        model: str = DEFAULT_GEMINI_MODEL,
        timeout: int = 60,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        client: genai.Client | None = None,
    ) -> None:
        self.model = model.strip() or DEFAULT_GEMINI_MODEL
        self.timeout = timeout
        self.temperature = temperature
        self.max_tokens = max_tokens

        if client is None:
            key = api_key.strip()
            if not key:
                raise ProviderConfigurationError(
                    "GEMINI_API_KEY is not configured.",
                    provider=self.name,
                )
            client = genai.Client(
                api_key=key,
                http_options=types.HttpOptions(
                    timeout=self.timeout * 1000,
                ),
            )
        self._client = client

    async def generate(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolDefinition] | None = None,
    ) -> LLMResponse:
        normalized = normalize_messages(messages)
        system_instruction, dialogue = split_system_messages(normalized)
        if not dialogue:
            raise ProviderInvalidRequestError(
                "At least one user or assistant message is required.",
                provider=self.name,
            )

        contents = [self._content_for(message) for message in dialogue]
        config_kwargs: dict[str, Any] = {
            "system_instruction": system_instruction,
            "temperature": self.temperature,
            "max_output_tokens": self.max_tokens,
        }
        if tools:
            config_kwargs["tools"] = [
                types.Tool(
                    function_declarations=[
                        types.FunctionDeclaration(
                            name=definition.name,
                            description=definition.description,
                            parameters_json_schema=definition.parameters,
                        )
                        for definition in tools
                    ]
                )
            ]
        config = types.GenerateContentConfig(**config_kwargs)

        try:
            response = await self._client.aio.models.generate_content(
                model=self.model,
                contents=contents,
                config=config,
            )
        except errors.APIError as error:
            raise self._map_api_error(error) from error
        except (TimeoutError, httpx.TimeoutException) as error:
            raise ProviderTimeoutError(
                "Gemini did not respond in time.",
                provider=self.name,
            ) from error
        except httpx.RequestError as error:
            raise ProviderUnavailableError(
                "Gemini could not be reached.",
                provider=self.name,
            ) from error
        except ProviderError:
            raise
        except Exception as error:  # pragma: no cover - defensive boundary
            logger.exception("Unexpected Gemini provider failure")
            raise ProviderUnavailableError(
                "Gemini could not complete the request.",
                provider=self.name,
            ) from error

        content = self._response_text(response) or ""
        tool_calls = self._response_tool_calls(response)
        if not content.strip() and not tool_calls:
            finish_reason = self._finish_reason(response)
            raise ProviderInvalidResponseError(
                "Gemini returned no text or tool calls"
                + (f" (finish reason: {finish_reason})." if finish_reason else "."),
                provider=self.name,
            )

        return LLMResponse(
            content=content.strip(),
            provider=self.name,
            model=self._response_model(response),
            finish_reason=self._finish_reason(response),
            usage=self._usage(response),
            tool_calls=tool_calls,
        )

    @staticmethod
    def _content_for(message: ChatMessage) -> types.Content:
        """Translate a provider-neutral message into one Gemini content."""
        if message.role == "tool":
            try:
                payload = json.loads(message.content)
            except ValueError:
                payload = {"result": message.content}
            if not isinstance(payload, dict):
                payload = {"result": payload}
            return types.Content(
                role="user",
                parts=[
                    types.Part(
                        function_response=types.FunctionResponse(
                            id=message.tool_call_id,
                            name=message.tool_name,
                            response=payload,
                        )
                    )
                ],
            )

        if message.role == "assistant":
            parts: list[types.Part] = []
            if message.content.strip():
                parts.append(types.Part.from_text(text=message.content))
            for call in message.tool_calls:
                provider_data = call.provider_data or {}
                signature = provider_data.get("thought_signature")
                parts.append(
                    types.Part(
                        function_call=types.FunctionCall(
                            id=call.id,
                            name=call.name,
                            args=call.arguments,
                        ),
                        thought_signature=(
                            signature
                            if isinstance(signature, bytes)
                            else None
                        ),
                    )
                )
            return types.Content(role="model", parts=parts)

        return types.Content(
            role="user",
            parts=[types.Part.from_text(text=message.content)],
        )

    def _map_api_error(self, error: errors.APIError) -> ProviderError:
        code = self._error_code(error)
        status = str(getattr(error, "status", "") or "").upper()
        detail = getattr(error, "message", None) or str(error)
        logger.warning(
            "Gemini API error (code=%s status=%s): %s",
            code,
            status or "unknown",
            detail[:500],
        )

        if code == 429 or status == "RESOURCE_EXHAUSTED":
            return ProviderRateLimitError(
                "Gemini rate limit reached. Try again shortly.",
                provider=self.name,
            )
        if code in {401, 403} or status in {
            "UNAUTHENTICATED",
            "PERMISSION_DENIED",
        }:
            return ProviderAuthenticationError(
                "Gemini rejected the configured API key.",
                provider=self.name,
            )
        if code == 404 or status == "NOT_FOUND":
            return ProviderModelNotFoundError(
                f"Gemini model '{self.model}' is not available.",
                provider=self.name,
            )
        if code in {408, 504} or status == "DEADLINE_EXCEEDED":
            return ProviderTimeoutError(
                "Gemini did not respond in time.",
                provider=self.name,
            )
        if (code is not None and 500 <= code < 600) or status in {
            "UNAVAILABLE",
            "INTERNAL",
            "UNKNOWN",
        }:
            return ProviderUnavailableError(
                "Gemini is temporarily unavailable.",
                provider=self.name,
            )
        if code == 400:
            return ProviderInvalidRequestError(
                "Gemini rejected the request.",
                provider=self.name,
            )
        return ProviderError(
            "Gemini could not complete the request.",
            provider=self.name,
        )

    @staticmethod
    def _error_code(error: errors.APIError) -> int | None:
        code = getattr(error, "code", None)
        if isinstance(code, int):
            return code
        if isinstance(code, str) and code.isdigit():
            return int(code)
        return None

    @staticmethod
    def _response_text(response: Any) -> str | None:
        candidates = getattr(response, "candidates", None) or []
        if candidates:
            content = getattr(candidates[0], "content", None)
            parts = getattr(content, "parts", None) or []
            if parts:
                texts = [
                    part.text
                    for part in parts
                    if isinstance(getattr(part, "text", None), str)
                    and part.text.strip()
                    and not getattr(part, "thought", False)
                ]
                joined = "".join(texts).strip()
                return joined or None

        try:
            text = response.text
        except Exception:
            return None
        return text if isinstance(text, str) and text.strip() else None

    @staticmethod
    def _response_tool_calls(response: Any) -> tuple[ToolCall, ...]:
        candidates = getattr(response, "candidates", None) or []
        if not candidates:
            return ()
        content = getattr(candidates[0], "content", None)
        parts = getattr(content, "parts", None) or []

        calls: list[ToolCall] = []
        for index, part in enumerate(parts):
            function_call = getattr(part, "function_call", None)
            if function_call is None:
                continue
            name = getattr(function_call, "name", None)
            if not isinstance(name, str) or not name.strip():
                continue
            arguments = getattr(function_call, "args", None) or {}
            if not isinstance(arguments, dict):
                logger.warning(
                    "Gemini returned non-object arguments for function call %r",
                    name,
                )
                continue
            raw_id = getattr(function_call, "id", None)
            call_id = (
                raw_id.strip()
                if isinstance(raw_id, str) and raw_id.strip()
                else f"call_{index + 1}"
            )
            signature = getattr(part, "thought_signature", None)
            provider_data = (
                {"thought_signature": signature}
                if isinstance(signature, bytes) and signature
                else None
            )
            calls.append(
                ToolCall(
                    id=call_id,
                    name=name.strip(),
                    arguments=arguments,
                    provider_data=provider_data,
                )
            )
        return tuple(calls)

    @staticmethod
    def _finish_reason(response: Any) -> str | None:
        candidates = getattr(response, "candidates", None) or []
        if not candidates:
            return None
        finish_reason = getattr(candidates[0], "finish_reason", None)
        if finish_reason is None:
            return None
        name = getattr(finish_reason, "name", None)
        if name:
            return str(name).lower()
        return str(finish_reason).rsplit(".", 1)[-1].lower()

    def _response_model(self, response: Any) -> str:
        model = getattr(response, "model_version", None)
        return model.strip() if isinstance(model, str) and model.strip() else self.model

    @staticmethod
    def _usage(response: Any) -> dict[str, int] | None:
        metadata = getattr(response, "usage_metadata", None)
        if metadata is None:
            return None

        usage: dict[str, int] = {}
        for source, target in (
            ("prompt_token_count", "input_tokens"),
            ("candidates_token_count", "output_tokens"),
            ("total_token_count", "total_tokens"),
        ):
            value = getattr(metadata, source, None)
            if isinstance(value, int):
                usage[target] = value
        return usage or None

    async def aclose(self) -> None:
        await self._client.aio.aclose()
