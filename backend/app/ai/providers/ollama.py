"""Local Ollama provider using the native ``/api/chat`` HTTP endpoint."""

from __future__ import annotations

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

    async def generate(self, messages: Sequence[ChatMessage]) -> LLMResponse:
        normalized = normalize_messages(messages)
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": self._role_for(message),
                    "content": message.content,
                }
                for message in normalized
            ],
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "num_predict": self.max_tokens,
            },
        }

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
        if not isinstance(content, str) or not content.strip():
            raise ProviderInvalidResponseError(
                "Ollama returned an empty response.",
                provider=self.name,
            )

        model = body.get("model") if isinstance(body, dict) else None
        finish_reason = body.get("done_reason") if isinstance(body, dict) else None
        return LLMResponse(
            content=content.strip(),
            provider=self.name,
            model=model if isinstance(model, str) and model.strip() else self.model,
            finish_reason=(
                finish_reason
                if isinstance(finish_reason, str) and finish_reason.strip()
                else "stop"
            ),
            usage=self._usage(body),
        )

    @staticmethod
    def _role_for(message: ChatMessage) -> str:
        if message.role in {"system", "assistant"}:
            return message.role
        return "user"

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
