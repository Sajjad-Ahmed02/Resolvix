from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from google.genai import errors, types

from app.ai.factory import create_provider
from app.ai.providers.base import (
    ChatMessage,
    ProviderAuthenticationError,
    ProviderConfigurationError,
    ProviderInvalidRequestError,
    ProviderInvalidResponseError,
    ProviderModelNotFoundError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.ai.providers.gemini import GeminiProvider
from app.ai.providers.ollama import OllamaProvider

MESSAGES = [
    ChatMessage(role="system", content="System rules"),
    ChatMessage(role="user", content="Where is my order?"),
    ChatMessage(role="assistant", content="Please share the order number."),
    ChatMessage(role="user", content="RX-2026-1001"),
]


class _FakeGeminiModels:
    def __init__(self, *, response=None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.kwargs: dict | None = None

    async def generate_content(self, **kwargs):
        self.kwargs = kwargs
        if self.error is not None:
            raise self.error
        return self.response


class _FakeGeminiAio:
    def __init__(self, **kwargs) -> None:
        self.models = _FakeGeminiModels(**kwargs)
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class _FakeGeminiClient:
    def __init__(self, **kwargs) -> None:
        self.aio = _FakeGeminiAio(**kwargs)


def _gemini_response(text: str = "Hello from Gemini"):
    return SimpleNamespace(
        text=text,
        candidates=[
            SimpleNamespace(finish_reason=types.FinishReason.STOP),
        ],
        usage_metadata=SimpleNamespace(
            prompt_token_count=11,
            candidates_token_count=7,
            total_token_count=18,
        ),
        model_version="gemini-3.5-flash-lite-001",
    )


def _run(coroutine):
    return asyncio.run(coroutine)


def test_gemini_provider_builds_request_and_normalizes_response() -> None:
    fake_client = _FakeGeminiClient(response=_gemini_response())
    provider = GeminiProvider(
        model="gemini-test",
        timeout=15,
        temperature=0.3,
        max_tokens=128,
        client=fake_client,
    )

    response = _run(provider.generate(MESSAGES))

    assert response.content == "Hello from Gemini"
    assert response.provider == "gemini"
    assert response.model == "gemini-3.5-flash-lite-001"
    assert response.finish_reason == "stop"
    assert response.usage == {
        "input_tokens": 11,
        "output_tokens": 7,
        "total_tokens": 18,
    }

    request = fake_client.aio.models.kwargs
    assert request is not None
    assert request["model"] == "gemini-test"
    assert request["config"].system_instruction == "System rules"
    assert request["config"].temperature == 0.3
    assert request["config"].max_output_tokens == 128
    assert [content.role for content in request["contents"]] == [
        "user",
        "model",
        "user",
    ]
    assert [
        content.parts[0].text for content in request["contents"]
    ] == [
        "Where is my order?",
        "Please share the order number.",
        "RX-2026-1001",
    ]


def test_gemini_provider_maps_rate_limit_and_auth_errors() -> None:
    rate_limited = _FakeGeminiClient(
        error=errors.ClientError(
            429,
            {
                "error": {
                    "code": 429,
                    "status": "RESOURCE_EXHAUSTED",
                    "message": "quota",
                }
            },
        )
    )
    with pytest.raises(ProviderRateLimitError) as rate_error:
        _run(
            GeminiProvider(client=rate_limited).generate(MESSAGES)
        )
    assert rate_error.value.code == "rate_limit"

    unauthorized = _FakeGeminiClient(
        error=errors.ClientError(
            401,
            {
                "error": {
                    "code": 401,
                    "status": "UNAUTHENTICATED",
                    "message": "bad key",
                }
            },
        )
    )
    with pytest.raises(ProviderAuthenticationError):
        _run(
            GeminiProvider(client=unauthorized).generate(MESSAGES)
        )


def test_gemini_provider_maps_timeout_and_model_not_found() -> None:
    timed_out = _FakeGeminiClient(error=httpx.ReadTimeout("slow"))
    with pytest.raises(ProviderTimeoutError):
        _run(GeminiProvider(client=timed_out).generate(MESSAGES))

    missing_model = _FakeGeminiClient(
        error=errors.ClientError(
            404,
            {
                "error": {
                    "code": 404,
                    "status": "NOT_FOUND",
                    "message": "model not found",
                }
            },
        )
    )
    with pytest.raises(ProviderModelNotFoundError):
        _run(
            GeminiProvider(
                model="missing-model",
                client=missing_model,
            ).generate(MESSAGES)
        )


def test_gemini_provider_rejects_empty_text_and_validates_configuration() -> None:
    empty = _FakeGeminiClient(response=_gemini_response(text="   "))
    with pytest.raises(ProviderInvalidResponseError):
        _run(GeminiProvider(client=empty).generate(MESSAGES))

    with pytest.raises(ProviderConfigurationError):
        GeminiProvider(api_key="", model="gemini-test")


def test_ollama_provider_normalizes_a_successful_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == "http://ollama.test/api/chat"
        body = json.loads(request.content)
        assert body["model"] == "llama3.2:3b"
        assert body["stream"] is False
        assert body["options"] == {
            "temperature": 0.4,
            "num_predict": 256,
        }
        assert [
            (message["role"], message["content"])
            for message in body["messages"]
        ] == [
            ("system", "System rules"),
            ("user", "Where is my order?"),
            ("assistant", "Please share the order number."),
            ("user", "RX-2026-1001"),
        ]
        return httpx.Response(
            200,
            json={
                "model": "llama3.2:3b",
                "message": {
                    "role": "assistant",
                    "content": "Your order is on the way.",
                },
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": 21,
                "eval_count": 9,
            },
        )

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
        ) as client:
            provider = OllamaProvider(
                base_url="http://ollama.test/",
                model="llama3.2:3b",
                timeout=15,
                temperature=0.4,
                max_tokens=256,
                client=client,
            )
            return await provider.generate(MESSAGES)

    response = _run(run())

    assert response.content == "Your order is on the way."
    assert response.provider == "ollama"
    assert response.model == "llama3.2:3b"
    assert response.finish_reason == "stop"
    assert response.usage == {
        "input_tokens": 21,
        "output_tokens": 9,
        "total_tokens": 30,
    }


@pytest.mark.parametrize(
    ("status_code", "expected_error"),
    [
        (404, ProviderModelNotFoundError),
        (429, ProviderRateLimitError),
        (500, ProviderUnavailableError),
        (400, ProviderInvalidRequestError),
    ],
)
def test_ollama_provider_maps_http_errors(
    status_code: int,
    expected_error: type[Exception],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code,
            json={"error": "model 'llama3.2:3b' not found"},
        )

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
        ) as client:
            provider = OllamaProvider(client=client)
            await provider.generate(MESSAGES)

    with pytest.raises(expected_error):
        _run(run())


def test_ollama_provider_maps_connection_and_timeout_errors() -> None:
    def connect_error(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    def timeout_error(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    async def run(handler):
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
        ) as client:
            provider = OllamaProvider(client=client)
            await provider.generate(MESSAGES)

    with pytest.raises(ProviderUnavailableError):
        _run(run(connect_error))
    with pytest.raises(ProviderTimeoutError):
        _run(run(timeout_error))


def test_ollama_provider_rejects_invalid_responses() -> None:
    def invalid_json(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-json")

    def empty_content(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"message": {"role": "assistant", "content": "   "}},
        )

    async def run(handler):
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
        ) as client:
            provider = OllamaProvider(client=client)
            await provider.generate(MESSAGES)

    with pytest.raises(ProviderInvalidResponseError):
        _run(run(invalid_json))
    with pytest.raises(ProviderInvalidResponseError):
        _run(run(empty_content))


def test_ollama_provider_validates_base_url_and_model() -> None:
    with pytest.raises(ProviderConfigurationError):
        OllamaProvider(base_url="localhost:11434")
    with pytest.raises(ProviderConfigurationError):
        OllamaProvider(model="   ")


def _settings(**overrides):
    values = {
        "LLM_PROVIDER": "gemini",
        "LLM_MODEL": "gemini-test",
        "GEMINI_API_KEY": "test-key",
        "LLM_API_KEY": "",
        "OLLAMA_BASE_URL": "http://localhost:11434",
        "OLLAMA_MODEL": "llama3.2:3b",
        "LLM_TIMEOUT": 10,
        "LLM_TEMPERATURE": 0.2,
        "LLM_MAX_TOKENS": 100,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_factory_selects_the_configured_provider() -> None:
    gemini = create_provider(_settings())
    assert isinstance(gemini, GeminiProvider)
    assert gemini.model == "gemini-test"
    _run(gemini.aclose())

    ollama = create_provider(
        _settings(LLM_PROVIDER="OLLAMA", OLLAMA_MODEL="llama3.2:3b")
    )
    assert isinstance(ollama, OllamaProvider)
    assert ollama.model == "llama3.2:3b"
    _run(ollama.aclose())


def test_factory_uses_defaults_and_generic_key_fallback() -> None:
    provider = create_provider(
        _settings(
            LLM_MODEL="",
            GEMINI_API_KEY="",
            LLM_API_KEY="generic-key",
        )
    )
    assert isinstance(provider, GeminiProvider)
    assert provider.model == "gemini-3.5-flash-lite"
    _run(provider.aclose())


def test_factory_rejects_invalid_configuration() -> None:
    with pytest.raises(ProviderConfigurationError):
        create_provider(_settings(GEMINI_API_KEY="", LLM_API_KEY=""))
    with pytest.raises(ProviderConfigurationError):
        create_provider(_settings(LLM_PROVIDER="unknown"))
    with pytest.raises(ProviderConfigurationError):
        create_provider(
            _settings(LLM_PROVIDER="ollama", OLLAMA_MODEL="   ")
        )
