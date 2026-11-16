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
    ToolCall,
    ToolDefinition,
)
from app.ai.providers.gemini import GeminiProvider
from app.ai.providers.ollama import OllamaProvider

MESSAGES = [
    ChatMessage(role="system", content="System rules"),
    ChatMessage(role="user", content="Where is my order?"),
    ChatMessage(role="assistant", content="Please share the order number."),
    ChatMessage(role="user", content="RX-2026-1001"),
]

ORDER_TOOL = ToolDefinition(
    name="get_order_details",
    description="Look up an order for the signed-in customer.",
    parameters={
        "type": "object",
        "properties": {
            "order_number": {
                "type": "string",
                "description": "The order number.",
            }
        },
        "required": ["order_number"],
        "additionalProperties": False,
    },
)


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


def test_gemini_provider_maps_function_calls_and_tool_messages() -> None:
    call_part = types.Part(
        function_call=types.FunctionCall(
            id="call_gemini_1",
            name="get_order_details",
            args={"order_number": "RX-2026-1001"},
        ),
        thought_signature=b"opaque-thought-signature",
    )
    tool_response = SimpleNamespace(
        text=None,
        candidates=[
            SimpleNamespace(
                finish_reason=types.FinishReason.STOP,
                content=types.Content(role="model", parts=[call_part]),
            )
        ],
        usage_metadata=SimpleNamespace(
            prompt_token_count=20,
            candidates_token_count=5,
            total_token_count=25,
        ),
        model_version="gemini-test-001",
    )
    first_client = _FakeGeminiClient(response=tool_response)
    provider = GeminiProvider(model="gemini-test", client=first_client)

    response = _run(provider.generate(MESSAGES, tools=[ORDER_TOOL]))

    assert response.content == ""
    assert len(response.tool_calls) == 1
    call = response.tool_calls[0]
    assert call.id == "call_gemini_1"
    assert call.name == "get_order_details"
    assert call.arguments == {"order_number": "RX-2026-1001"}
    assert call.provider_data == {
        "thought_signature": b"opaque-thought-signature"
    }

    request = first_client.aio.models.kwargs
    declarations = request["config"].tools[0].function_declarations
    assert [declaration.name for declaration in declarations] == [
        "get_order_details"
    ]
    assert declarations[0].description == ORDER_TOOL.description
    assert declarations[0].parameters_json_schema == ORDER_TOOL.parameters

    follow_up = list(MESSAGES) + [
        ChatMessage(role="assistant", content="", tool_calls=(call,)),
        ChatMessage(
            role="tool",
            content='{"ok":true,"data":{"status":"processing"}}',
            tool_call_id="call_gemini_1",
            tool_name="get_order_details",
        ),
    ]
    second_client = _FakeGeminiClient(response=_gemini_response("Final reply"))
    second_provider = GeminiProvider(
        model="gemini-test",
        client=second_client,
    )

    final = _run(second_provider.generate(follow_up, tools=[ORDER_TOOL]))

    assert final.content == "Final reply"
    contents = second_client.aio.models.kwargs["contents"]
    assert [content.role for content in contents] == [
        "user",
        "model",
        "user",
        "model",
        "user",
    ]
    tool_call_part = contents[-2].parts[0]
    assert tool_call_part.function_call.name == "get_order_details"
    assert tool_call_part.function_call.args == {
        "order_number": "RX-2026-1001"
    }
    assert tool_call_part.thought_signature == b"opaque-thought-signature"
    tool_result_part = contents[-1].parts[0]
    assert tool_result_part.function_response.name == "get_order_details"
    assert tool_result_part.function_response.id == "call_gemini_1"
    assert tool_result_part.function_response.response == {
        "ok": True,
        "data": {"status": "processing"},
    }
    assert [
        declaration.name
        for declaration in (
            second_client.aio.models.kwargs["config"].tools[0]
            .function_declarations
        )
    ] == ["get_order_details"]


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


def test_ollama_provider_maps_tools_and_tool_messages() -> None:
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        if len(bodies) == 1:
            return httpx.Response(
                200,
                json={
                    "model": "llama3.2:3b",
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "type": "function",
                                "function": {
                                    "name": "get_order_details",
                                    "arguments": {
                                        "order_number": "RX-2026-1001"
                                    },
                                },
                            }
                        ],
                    },
                    "done": True,
                    "done_reason": "stop",
                    "prompt_eval_count": 15,
                    "eval_count": 4,
                },
            )
        return httpx.Response(
            200,
            json={
                "model": "llama3.2:3b",
                "message": {
                    "role": "assistant",
                    "content": "Your order is processing.",
                },
                "done": True,
                "done_reason": "stop",
            },
        )

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
        ) as client:
            provider = OllamaProvider(client=client)
            first = await provider.generate(MESSAGES, tools=[ORDER_TOOL])
            follow_up = list(MESSAGES) + [
                ChatMessage(
                    role="assistant",
                    content="",
                    tool_calls=first.tool_calls,
                ),
                ChatMessage(
                    role="tool",
                    content='{"ok":true,"data":{"status":"processing"}}',
                    tool_call_id=first.tool_calls[0].id,
                    tool_name="get_order_details",
                ),
            ]
            second = await provider.generate(follow_up, tools=[ORDER_TOOL])
            return first, second

    first, second = _run(run())

    assert first.content == ""
    assert first.tool_calls[0].id == "call_1"
    assert first.tool_calls[0].name == "get_order_details"
    assert first.tool_calls[0].arguments == {
        "order_number": "RX-2026-1001"
    }
    assert second.content == "Your order is processing."

    assert bodies[0]["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "get_order_details",
                "description": ORDER_TOOL.description,
                "parameters": ORDER_TOOL.parameters,
            },
        }
    ]
    assert bodies[1]["messages"][-2] == {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "type": "function",
                "function": {
                    "name": "get_order_details",
                    "arguments": {"order_number": "RX-2026-1001"},
                },
            }
        ],
    }
    assert bodies[1]["messages"][-1] == {
        "role": "tool",
        "tool_name": "get_order_details",
        "content": '{"ok":true,"data":{"status":"processing"}}',
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
