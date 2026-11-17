from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app.ai.orchestrator import (
    ORDER_LOOKUP_UNAVAILABLE_REPLY,
    TOOL_LIMIT_ASSISTANT_MESSAGE,
)
from app.ai.providers.base import ProviderRateLimitError, ToolCall
from app.ai.routing import (
    AMBIGUOUS_CLARIFICATION,
    ORDER_NUMBER_CLARIFICATION,
)
from app.knowledge.retrieval import RetrievedChunk
from app.services.conversations import FALLBACK_ASSISTANT_MESSAGE
from app.tools import order_tools
from app.tools.knowledge_tools import KNOWLEDGE_SEARCH_TOOL_NAME
from app.tools.order_tools import ORDER_DETAILS_TOOL_NAME


def _create_conversation(
    client: TestClient,
    headers: dict[str, str],
) -> dict:
    response = client.post("/conversations", json={}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _send(
    client: TestClient,
    headers: dict[str, str],
    conversation_id: str,
    content: str,
) -> dict:
    response = client.post(
        f"/conversations/{conversation_id}/messages",
        json={"content": content},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _roles(messages: list[dict]) -> list[str]:
    return [message["role"] for message in messages]


def test_order_lookup_then_arrival_follow_up_reuses_order_context(
    client: TestClient,
    accounts,
    login_headers,
    fake_llm_provider,
) -> None:
    headers = login_headers(accounts["customer_a"]["email"])
    conversation = _create_conversation(client, headers)
    order_number = accounts["order_a_number"]
    fake_llm_provider.reply = (
        "Your order is processing and in transit. It is estimated to arrive "
        "today."
    )

    first = _send(
        client,
        headers,
        conversation["id"],
        f"Where is my order {order_number}?",
    )
    assert first["assistant_message"]["metadata"]["intent"] == "order_status"
    assert first["assistant_message"]["metadata"]["context_messages"] == 0

    second = _send(
        client,
        headers,
        conversation["id"],
        "When will it arrive?",
    )

    metadata = second["assistant_message"]["metadata"]
    assert metadata["intent"] == "order_status"
    assert metadata["capabilities"] == ["order_lookup", "llm_response"]
    assert metadata["context_messages"] == 2
    assert metadata["tool_calls"] == [
        {
            "name": ORDER_DETAILS_TOOL_NAME,
            "arguments": {"order_number": order_number},
            "status": "ok",
        }
    ]
    assert ORDER_NUMBER_CLARIFICATION not in second["assistant_message"]["content"]

    assert len(fake_llm_provider.calls) == 2
    second_request = fake_llm_provider.calls[1]
    assert [message.role for message in second_request] == [
        "system",
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert order_number in second_request[1].content
    assert second_request[2].content == f"Where is my order {order_number}?"
    assert second_request[4].content == "When will it arrive?"

    history = client.get(
        f"/conversations/{conversation['id']}/messages",
        headers=headers,
    )
    assert history.status_code == 200
    assert _roles(history.json()) == [
        "user",
        "tool",
        "assistant",
        "user",
        "tool",
        "assistant",
    ]
    assert history.json()[4]["metadata"]["order_number"] == order_number
    assert history.json()[4]["metadata"]["preflight"] is True


def test_return_policy_follow_up_uses_grounded_knowledge(
    client: TestClient,
    accounts,
    login_headers,
    fake_llm_provider,
    fake_knowledge_retriever,
) -> None:
    headers = login_headers(accounts["customer_a"]["email"])
    conversation = _create_conversation(client, headers)
    chunk = RetrievedChunk(
        source_type="faq",
        source_id=uuid.uuid4(),
        title="What is your return window?",
        category="Returns",
        chunk_index=0,
        content=(
            "Unused products in their original packaging can be returned "
            "within 30 days of delivery."
        ),
        distance=0.18,
    )
    fake_knowledge_retriever.results = [chunk]
    fake_llm_provider.reply = (
        "Unused products in their original packaging can be returned within "
        "30 days of delivery."
    )

    first = _send(
        client,
        headers,
        conversation["id"],
        "What is your return policy?",
    )
    assert first["assistant_message"]["metadata"]["intent"] == (
        "return_refund_policy"
    )
    assert first["assistant_message"]["metadata"]["grounded"] is True

    second = _send(
        client,
        headers,
        conversation["id"],
        "What about opened items?",
    )

    metadata = second["assistant_message"]["metadata"]
    assert metadata["intent"] == "return_refund_policy"
    assert metadata["capabilities"] == ["knowledge_search", "llm_response"]
    assert metadata["grounded"] is True
    assert metadata["sources"] == [chunk.as_metadata()]
    assert metadata["tool_calls"] == [
        {
            "name": KNOWLEDGE_SEARCH_TOOL_NAME,
            "arguments": {
                "query": (
                    "What is your return policy? What about opened items?"
                )
            },
            "status": "ok",
        }
    ]
    assert fake_knowledge_retriever.queries == [
        "What is your return policy?",
        "What is your return policy? What about opened items?",
    ]

    second_request = fake_llm_provider.calls[1]
    assert [message.role for message in second_request] == [
        "system",
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert "30 days" in second_request[1].content
    assert "What is your return window?" in second_request[1].content

    history = client.get(
        f"/conversations/{conversation['id']}/messages",
        headers=headers,
    )
    assert history.status_code == 200
    assert _roles(history.json()) == [
        "user",
        "tool",
        "assistant",
        "user",
        "tool",
        "assistant",
    ]
    assert history.json()[4]["metadata"]["tool"] == KNOWLEDGE_SEARCH_TOOL_NAME
    assert history.json()[4]["metadata"]["sources"] == [chunk.as_metadata()]


@pytest.mark.parametrize(
    ("content", "intent"),
    [
        ("How long does standard shipping take?", "shipping_faq"),
        ("What payment methods do you accept?", "payment_faq"),
    ],
)
def test_shipping_and_payment_faqs_use_controlled_knowledge_search(
    client: TestClient,
    accounts,
    login_headers,
    fake_llm_provider,
    fake_knowledge_retriever,
    content: str,
    intent: str,
) -> None:
    headers = login_headers(accounts["customer_a"]["email"])
    conversation = _create_conversation(client, headers)
    chunk = RetrievedChunk(
        source_type="faq",
        source_id=uuid.uuid4(),
        title="Shipping and payment reference",
        category="Policies",
        chunk_index=0,
        content="Reference answer from the Resolvix knowledge base.",
        distance=0.22,
    )
    fake_knowledge_retriever.results = [chunk]
    fake_llm_provider.reply = "Here is the policy information you asked for."

    body = _send(client, headers, conversation["id"], content)

    metadata = body["assistant_message"]["metadata"]
    assert metadata["intent"] == intent
    assert metadata["capabilities"] == ["knowledge_search", "llm_response"]
    assert metadata["grounded"] is True
    assert metadata["sources"] == [chunk.as_metadata()]
    assert metadata["tool_calls"] == [
        {
            "name": KNOWLEDGE_SEARCH_TOOL_NAME,
            "arguments": {"query": content},
            "status": "ok",
        }
    ]
    assert fake_knowledge_retriever.queries == [content]
    request = fake_llm_provider.calls[0]
    assert [message.role for message in request] == ["system", "system", "user"]
    assert "Reference answer" in request[1].content


def test_missing_order_number_asks_for_details_without_calling_the_provider(
    client: TestClient,
    accounts,
    login_headers,
    fake_llm_provider,
    fake_knowledge_retriever,
) -> None:
    headers = login_headers(accounts["customer_a"]["email"])
    conversation = _create_conversation(client, headers)

    body = _send(
        client,
        headers,
        conversation["id"],
        "Where is my order?",
    )

    assert body["assistant_message"]["content"] == ORDER_NUMBER_CLARIFICATION
    metadata = body["assistant_message"]["metadata"]
    assert metadata["source"] == "clarification"
    assert metadata["intent"] == "order_status"
    assert metadata["capabilities"] == ["ask_for_details"]
    assert metadata["clarification_reason"] == "missing_order_number"
    assert metadata["grounded"] is False
    assert metadata["sources"] == []
    assert "tool_calls" not in metadata
    assert fake_llm_provider.calls == []
    assert fake_knowledge_retriever.queries == []

    history = client.get(
        f"/conversations/{conversation['id']}/messages",
        headers=headers,
    )
    assert history.status_code == 200
    assert _roles(history.json()) == ["user", "assistant"]


def test_ambiguous_request_asks_for_details_without_calling_the_provider(
    client: TestClient,
    accounts,
    login_headers,
    fake_llm_provider,
) -> None:
    headers = login_headers(accounts["customer_a"]["email"])
    conversation = _create_conversation(client, headers)

    body = _send(client, headers, conversation["id"], "Please help")

    assert body["assistant_message"]["content"] == AMBIGUOUS_CLARIFICATION
    metadata = body["assistant_message"]["metadata"]
    assert metadata["source"] == "clarification"
    assert metadata["intent"] == "ambiguous"
    assert metadata["capabilities"] == ["ask_for_details"]
    assert metadata["clarification_reason"] == "ambiguous_request"
    assert fake_llm_provider.calls == []


def test_unavailable_knowledge_produces_a_controlled_ungrounded_reply(
    client: TestClient,
    accounts,
    login_headers,
    fake_llm_provider,
    fake_knowledge_retriever,
) -> None:
    headers = login_headers(accounts["customer_a"]["email"])
    conversation = _create_conversation(client, headers)
    fake_knowledge_retriever.error = RuntimeError(
        "vector backend password=super-secret"
    )
    fake_llm_provider.reply = (
        "I cannot confirm that policy right now. Please try again shortly."
    )

    body = _send(
        client,
        headers,
        conversation["id"],
        "What is your return policy?",
    )

    assert body["assistant_message"]["content"] == fake_llm_provider.reply
    metadata = body["assistant_message"]["metadata"]
    assert metadata["intent"] == "return_refund_policy"
    assert metadata["capabilities"] == ["knowledge_search", "llm_response"]
    assert metadata["grounded"] is False
    assert metadata["sources"] == []
    assert metadata["tool_calls"] == [
        {
            "name": KNOWLEDGE_SEARCH_TOOL_NAME,
            "arguments": {"query": "What is your return policy?"},
            "status": "error",
            "error": "knowledge_unavailable",
        }
    ]

    request = fake_llm_provider.calls[0]
    assert [message.role for message in request] == ["system", "system", "user"]
    assert "could not complete" in request[1].content
    assert "super-secret" not in request[1].content
    assert "super-secret" not in body["assistant_message"]["content"]

    history = client.get(
        f"/conversations/{conversation['id']}/messages",
        headers=headers,
    )
    assert history.status_code == 200
    assert _roles(history.json()) == ["user", "tool", "assistant"]
    assert history.json()[1]["metadata"]["error"] == "knowledge_unavailable"
    assert "super-secret" not in history.json()[1]["content"]


def test_empty_knowledge_results_produce_an_ungrounded_reply(
    client: TestClient,
    accounts,
    login_headers,
    fake_llm_provider,
    fake_knowledge_retriever,
) -> None:
    headers = login_headers(accounts["customer_a"]["email"])
    conversation = _create_conversation(client, headers)
    fake_knowledge_retriever.results = []
    fake_llm_provider.reply = (
        "I do not have that information right now. Please contact support."
    )

    body = _send(
        client,
        headers,
        conversation["id"],
        "What is your return policy?",
    )

    metadata = body["assistant_message"]["metadata"]
    assert metadata["grounded"] is False
    assert metadata["sources"] == []
    assert metadata["tool_calls"] == [
        {
            "name": KNOWLEDGE_SEARCH_TOOL_NAME,
            "arguments": {"query": "What is your return policy?"},
            "status": "ok",
        }
    ]

    request = fake_llm_provider.calls[0]
    assert [message.role for message in request] == ["system", "system", "user"]
    assert "returned no matching reference material" in request[1].content

    history = client.get(
        f"/conversations/{conversation['id']}/messages",
        headers=headers,
    )
    assert history.status_code == 200
    assert _roles(history.json()) == ["user", "tool", "assistant"]
    assert history.json()[1]["metadata"]["result_count"] == 0


def test_failed_order_lookup_blocks_an_unsupported_success_claim(
    client: TestClient,
    accounts,
    login_headers,
    fake_llm_provider,
    monkeypatch,
) -> None:
    headers = login_headers(accounts["customer_a"]["email"])
    conversation = _create_conversation(client, headers)
    order_number = accounts["order_a_number"]

    def fail(*args, **kwargs):
        raise SQLAlchemyError("connection string password=super-secret")

    monkeypatch.setattr(
        order_tools.orders,
        "get_for_user_by_number",
        fail,
    )
    fake_llm_provider.reply = (
        "Your order is shipped and will arrive tomorrow."
    )

    body = _send(
        client,
        headers,
        conversation["id"],
        f"Where is my order {order_number}?",
    )

    assert body["assistant_message"]["content"] == ORDER_LOOKUP_UNAVAILABLE_REPLY
    metadata = body["assistant_message"]["metadata"]
    assert metadata["source"] == "guarded"
    assert metadata["guard_applied"] is True
    assert metadata["intent"] == "order_status"
    assert metadata["tool_calls"] == [
        {
            "name": ORDER_DETAILS_TOOL_NAME,
            "arguments": {"order_number": order_number},
            "status": "error",
            "error": "database_error",
        }
    ]
    assert "super-secret" not in body["assistant_message"]["content"]

    request = fake_llm_provider.calls[0]
    assert [message.role for message in request] == ["system", "system", "user"]
    assert "did not succeed" in request[1].content
    assert "database_error" in request[1].content
    assert "super-secret" not in request[1].content


def test_duplicate_model_tool_request_is_not_executed_twice(
    client: TestClient,
    accounts,
    login_headers,
    fake_llm_provider,
) -> None:
    headers = login_headers(accounts["customer_a"]["email"])
    conversation = _create_conversation(client, headers)
    order_number = accounts["order_a_number"]
    fake_llm_provider.reply = "Your order is still on track."
    _send(
        client,
        headers,
        conversation["id"],
        f"Where is my order {order_number}?",
    )

    duplicate_call = ToolCall(
        id="call_duplicate",
        name=ORDER_DETAILS_TOOL_NAME,
        arguments={"order_number": order_number},
    )
    fake_llm_provider.pending_tool_calls = [(duplicate_call,)]

    second = _send(
        client,
        headers,
        conversation["id"],
        "Where is my order?",
    )

    metadata = second["assistant_message"]["metadata"]
    assert metadata["intent"] == "order_status"
    assert metadata["tool_calls"] == [
        {
            "name": ORDER_DETAILS_TOOL_NAME,
            "arguments": {"order_number": order_number},
            "status": "ok",
        },
        {
            "name": ORDER_DETAILS_TOOL_NAME,
            "arguments": {"order_number": order_number},
            "status": "error",
            "error": "duplicate_tool_call",
        },
    ]
    assert metadata["tool_rounds"] == 1
    assert len(fake_llm_provider.calls) == 3
    tool_result = fake_llm_provider.calls[2][-1]
    assert tool_result.role == "tool"
    assert '"code":"duplicate_tool_call"' in tool_result.content

    history = client.get(
        f"/conversations/{conversation['id']}/messages",
        headers=headers,
    )
    assert history.status_code == 200
    # The duplicate is audited on the assistant message but is not persisted as
    # another tool row.
    assert _roles(history.json()) == [
        "user",
        "tool",
        "assistant",
        "user",
        "tool",
        "assistant",
    ]


def test_per_round_tool_call_limit_stops_the_loop(
    client: TestClient,
    accounts,
    login_headers,
    fake_llm_provider,
) -> None:
    headers = login_headers(accounts["customer_a"]["email"])
    conversation = _create_conversation(client, headers)
    order_number = accounts["order_a_number"]
    fake_llm_provider.pending_tool_calls = [
        (
            *[
                ToolCall(
                    id=f"call_many_{index}",
                    name=ORDER_DETAILS_TOOL_NAME,
                    arguments={"order_number": f"RX-1999-{9000 + index}"},
                )
                for index in range(5)
            ],
        )
    ]

    body = _send(
        client,
        headers,
        conversation["id"],
        f"Check order {order_number}",
    )

    assert body["assistant_message"]["content"] == TOOL_LIMIT_ASSISTANT_MESSAGE
    metadata = body["assistant_message"]["metadata"]
    assert metadata["source"] == "tool_limit"
    assert metadata["error"] == "tool_call_limit"
    # One preflight plus four allowed per-round calls and one blocked attempt.
    assert len(metadata["tool_calls"]) == 6
    assert metadata["tool_calls"][-1]["error"] == "tool_call_limit"
    assert len(fake_llm_provider.calls) == 1


def test_provider_failure_during_an_existing_conversation_keeps_history(
    client: TestClient,
    accounts,
    login_headers,
    fake_llm_provider,
) -> None:
    headers = login_headers(accounts["customer_a"]["email"])
    conversation = _create_conversation(client, headers)
    fake_llm_provider.reply = "Hi, how can I help with your order today?"

    first = _send(client, headers, conversation["id"], "Hello")
    assert first["assistant_message"]["content"] == fake_llm_provider.reply

    fake_llm_provider.error = ProviderRateLimitError(
        "quota exhausted",
        provider="stub",
    )
    second = _send(
        client,
        headers,
        conversation["id"],
        "What can Resolvix help with?",
    )

    metadata = second["assistant_message"]["metadata"]
    assert second["assistant_message"]["content"] == FALLBACK_ASSISTANT_MESSAGE
    assert metadata["source"] == "fallback"
    assert metadata["fallback"] is True
    assert metadata["error"] == "rate_limit"
    assert metadata["context_messages"] == 2
    assert len(fake_llm_provider.calls) == 2
    assert [message.role for message in fake_llm_provider.calls[1]] == [
        "system",
        "user",
        "assistant",
        "user",
    ]

    history = client.get(
        f"/conversations/{conversation['id']}/messages",
        headers=headers,
    )
    assert history.status_code == 200
    assert _roles(history.json()) == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert [message["content"] for message in history.json()] == [
        "Hello",
        first["assistant_message"]["content"],
        "What can Resolvix help with?",
        FALLBACK_ASSISTANT_MESSAGE,
    ]


def test_multiple_consecutive_turns_build_growing_bounded_context(
    client: TestClient,
    accounts,
    login_headers,
    fake_llm_provider,
) -> None:
    headers = login_headers(accounts["customer_a"]["email"])
    conversation = _create_conversation(client, headers)
    messages = [
        "Hello",
        "How are you today?",
        "What can Resolvix help with?",
        "Thanks",
    ]

    for index, content in enumerate(messages):
        body = _send(client, headers, conversation["id"], content)
        assert body["assistant_message"]["metadata"]["context_messages"] == (
            index * 2
        )

    assert len(fake_llm_provider.calls) == len(messages)
    assert [message.role for message in fake_llm_provider.calls[-1]] == [
        "system",
        *[
            role
            for _ in range(len(messages) - 1)
            for role in ("user", "assistant")
        ],
        "user",
    ]
    assert [
        message.content for message in fake_llm_provider.calls[-1][-7:]
    ] == [
        "Hello",
        fake_llm_provider.reply,
        "How are you today?",
        fake_llm_provider.reply,
        "What can Resolvix help with?",
        fake_llm_provider.reply,
        "Thanks",
    ]

    history = client.get(
        f"/conversations/{conversation['id']}/messages",
        headers=headers,
    )
    assert history.status_code == 200
    assert _roles(history.json()) == ["user", "assistant"] * len(messages)
