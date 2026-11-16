from __future__ import annotations

import json
import uuid
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.ai.prompts import SYSTEM_PROMPT
from app.ai.providers.base import ProviderRateLimitError, ToolCall
from app.db.session import SessionLocal
from app.knowledge.grounding import build_context_prompt
from app.knowledge.retrieval import RetrievedChunk
from app.models import Conversation, Message
from app.services.conversations import (
    FALLBACK_ASSISTANT_MESSAGE,
    MAX_TOOL_ROUNDS,
    TOOL_LIMIT_ASSISTANT_MESSAGE,
)
from app.tools import order_tools
from app.tools.order_tools import ORDER_DETAILS_TOOL_NAME


def _create_conversation(
    client: TestClient,
    headers: dict[str, str],
    *,
    title: str | None = None,
) -> dict:
    payload = {} if title is None else {"title": title}
    response = client.post("/conversations", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_create_conversation_persists_an_empty_thread(
    client: TestClient,
    accounts,
    login_headers,
) -> None:
    headers = login_headers(accounts["customer_a"]["email"])

    created = _create_conversation(client, headers)
    conversation_id = created["id"]

    assert created["title"] is None
    assert _parse_timestamp(created["updated_at"]) >= _parse_timestamp(
        created["created_at"]
    )

    detail = client.get(f"/conversations/{conversation_id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["messages"] == []

    listing = client.get("/conversations", headers=headers)
    assert listing.status_code == 200
    assert conversation_id in {
        conversation["id"] for conversation in listing.json()
    }

    session = SessionLocal()
    try:
        stored = session.get(Conversation, uuid.UUID(conversation_id))
        assert stored is not None
        assert stored.user_id == accounts["customer_a"]["id"]
        assert stored.messages == []
    finally:
        session.close()


def test_create_conversation_validates_and_normalizes_title(
    client: TestClient,
    accounts,
    login_headers,
) -> None:
    headers = login_headers(accounts["customer_a"]["email"])

    normalized = _create_conversation(
        client,
        headers,
        title="  Billing   question ",
    )
    assert normalized["title"] == "Billing question"

    blank = client.post(
        "/conversations",
        json={"title": "   "},
        headers=headers,
    )
    too_long = client.post(
        "/conversations",
        json={"title": "x" * 201},
        headers=headers,
    )
    unexpected_identity = client.post(
        "/conversations",
        json={"user_id": str(accounts["customer_b"]["id"])},
        headers=headers,
    )

    assert blank.status_code == 422
    assert too_long.status_code == 422
    assert unexpected_identity.status_code == 422


def test_send_message_persists_generated_reply(
    client: TestClient,
    accounts,
    login_headers,
    fake_llm_provider,
) -> None:
    headers = login_headers(accounts["customer_a"]["email"])
    conversation = _create_conversation(client, headers)
    fake_llm_provider.reply = (
        "I can help with that. Please share your order number."
    )

    response = client.post(
        f"/conversations/{conversation['id']}/messages",
        json={"content": "  Where is my order?  "},
        headers=headers,
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["user_message"]["role"] == "user"
    assert body["user_message"]["content"] == "Where is my order?"
    assert body["assistant_message"]["role"] == "assistant"
    assert body["assistant_message"]["content"] == fake_llm_provider.reply
    assert body["assistant_message"]["metadata"] == {
        "source": "llm",
        "provider": "stub",
        "model": "stub-model",
        "reply_to": body["user_message"]["id"],
        "grounded": False,
        "sources": [],
        "finish_reason": "stop",
        "usage": {"input_tokens": 12, "output_tokens": 8},
    }
    assert body["conversation"]["title"] == "Where is my order?"
    assert _parse_timestamp(body["conversation"]["updated_at"]) > (
        _parse_timestamp(conversation["updated_at"])
    )

    assert len(fake_llm_provider.calls) == 1
    provider_messages = fake_llm_provider.calls[0]
    assert provider_messages[0].role == "system"
    assert provider_messages[0].content == SYSTEM_PROMPT
    assert [
        (message.role, message.content) for message in provider_messages[1:]
    ] == [("user", "Where is my order?")]

    history = client.get(
        f"/conversations/{conversation['id']}/messages",
        headers=headers,
    )
    assert history.status_code == 200
    assert [message["id"] for message in history.json()] == [
        body["user_message"]["id"],
        body["assistant_message"]["id"],
    ]

    detail = client.get(
        f"/conversations/{conversation['id']}",
        headers=headers,
    )
    assert detail.status_code == 200
    assert [message["role"] for message in detail.json()["messages"]] == [
        "user",
        "assistant",
    ]

    session = SessionLocal()
    try:
        stored = list(
            session.scalars(
                select(Message)
                .where(Message.conversation_id == uuid.UUID(conversation["id"]))
                .order_by(Message.created_at)
            ).all()
        )
        assert [(message.role, message.content) for message in stored] == [
            ("user", "Where is my order?"),
            ("assistant", fake_llm_provider.reply),
        ]
    finally:
        session.close()


def test_retrieved_knowledge_is_added_to_the_provider_prompt(
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
        "According to the Returns and Refunds Policy, unused products can be "
        "returned within 30 days of delivery."
    )

    response = client.post(
        f"/conversations/{conversation['id']}/messages",
        json={"content": "Can I send back an item after 30 days?"},
        headers=headers,
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert fake_knowledge_retriever.queries == [
        "Can I send back an item after 30 days?"
    ]
    assert len(fake_llm_provider.calls) == 1
    provider_messages = fake_llm_provider.calls[0]
    assert [message.role for message in provider_messages] == [
        "system",
        "system",
        "user",
    ]
    assert provider_messages[0].content == SYSTEM_PROMPT
    assert provider_messages[1].content == build_context_prompt([chunk])
    assert "30 days" in provider_messages[1].content
    assert "What is your return window?" in provider_messages[1].content
    assert "(Returns)" in provider_messages[1].content
    assert provider_messages[2].content == (
        "Can I send back an item after 30 days?"
    )

    metadata = body["assistant_message"]["metadata"]
    assert metadata["grounded"] is True
    assert metadata["sources"] == [chunk.as_metadata()]
    assert metadata["sources"][0]["title"] == "What is your return window?"
    assert metadata["sources"][0]["category"] == "Returns"


def test_retrieval_failure_still_generates_an_ungrounded_reply(
    client: TestClient,
    accounts,
    login_headers,
    fake_llm_provider,
    fake_knowledge_retriever,
) -> None:
    headers = login_headers(accounts["customer_a"]["email"])
    conversation = _create_conversation(client, headers)
    fake_knowledge_retriever.error = RuntimeError("embedding model unavailable")

    response = client.post(
        f"/conversations/{conversation['id']}/messages",
        json={"content": "What is your return policy?"},
        headers=headers,
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert [message.role for message in fake_llm_provider.calls[0]] == [
        "system",
        "user",
    ]
    assert body["assistant_message"]["metadata"]["grounded"] is False
    assert body["assistant_message"]["metadata"]["sources"] == []
    assert "embedding model unavailable" not in response.text


def test_send_message_includes_prior_turns_in_provider_history(
    client: TestClient,
    accounts,
    login_headers,
    fake_llm_provider,
) -> None:
    headers = login_headers(accounts["customer_a"]["email"])
    conversation = _create_conversation(client, headers)

    first = client.post(
        f"/conversations/{conversation['id']}/messages",
        json={"content": "My delivery is late"},
        headers=headers,
    )
    assert first.status_code == 201, first.text
    first_reply = first.json()["assistant_message"]["content"]

    fake_llm_provider.reply = "I can check the tracking status with you."
    second = client.post(
        f"/conversations/{conversation['id']}/messages",
        json={"content": "Can you check the tracking?"},
        headers=headers,
    )

    assert second.status_code == 201, second.text
    assert len(fake_llm_provider.calls) == 2
    assert [
        (message.role, message.content)
        for message in fake_llm_provider.calls[1]
    ] == [
        ("system", SYSTEM_PROMPT),
        ("user", "My delivery is late"),
        ("assistant", first_reply),
        ("user", "Can you check the tracking?"),
    ]


def test_provider_failure_persists_a_controlled_fallback(
    client: TestClient,
    accounts,
    login_headers,
    fake_llm_provider,
) -> None:
    headers = login_headers(accounts["customer_a"]["email"])
    conversation = _create_conversation(client, headers)
    fake_llm_provider.error = ProviderRateLimitError(
        "quota exhausted",
        provider="stub",
    )

    response = client.post(
        f"/conversations/{conversation['id']}/messages",
        json={"content": "Is my order still arriving?"},
        headers=headers,
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["assistant_message"]["content"] == FALLBACK_ASSISTANT_MESSAGE
    assert body["assistant_message"]["metadata"] == {
        "source": "fallback",
        "provider": "stub",
        "model": "stub-model",
        "fallback": True,
        "error": "rate_limit",
        "reply_to": body["user_message"]["id"],
        "grounded": False,
        "sources": [],
    }

    history = client.get(
        f"/conversations/{conversation['id']}/messages",
        headers=headers,
    )
    assert history.status_code == 200
    assert [message["content"] for message in history.json()] == [
        "Is my order still arriving?",
        FALLBACK_ASSISTANT_MESSAGE,
    ]


def test_unexpected_provider_failure_does_not_leak_details(
    client: TestClient,
    accounts,
    login_headers,
    fake_llm_provider,
) -> None:
    headers = login_headers(accounts["customer_a"]["email"])
    conversation = _create_conversation(client, headers)
    fake_llm_provider.error = RuntimeError("secret vendor stack trace")

    response = client.post(
        f"/conversations/{conversation['id']}/messages",
        json={"content": "Please help"},
        headers=headers,
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["assistant_message"]["content"] == FALLBACK_ASSISTANT_MESSAGE
    assert body["assistant_message"]["metadata"]["fallback"] is True
    assert body["assistant_message"]["metadata"]["error"] == "unexpected_error"
    assert "secret vendor stack trace" not in response.text


def test_first_message_sets_title_and_reload_keeps_history(
    client: TestClient,
    accounts,
    login_headers,
) -> None:
    headers = login_headers(accounts["customer_a"]["email"])
    conversation = _create_conversation(client, headers)

    first = client.post(
        f"/conversations/{conversation['id']}/messages",
        json={"content": "My delivery is late"},
        headers=headers,
    )
    second = client.post(
        f"/conversations/{conversation['id']}/messages",
        json={"content": "Can you check the tracking?"},
        headers=headers,
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()["conversation"]["title"] == "My delivery is late"

    reloaded = client.get(
        f"/conversations/{conversation['id']}/messages",
        headers=headers,
    )
    assert reloaded.status_code == 200
    assert [message["role"] for message in reloaded.json()] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert reloaded.json()[0]["content"] == "My delivery is late"
    assert reloaded.json()[2]["content"] == "Can you check the tracking?"


def test_new_message_moves_conversation_to_the_top(
    client: TestClient,
    accounts,
    login_headers,
) -> None:
    headers = login_headers(accounts["customer_a"]["email"])
    older = _create_conversation(client, headers, title="Older thread")
    newer = _create_conversation(client, headers, title="Newer thread")

    before = client.get("/conversations", headers=headers)
    assert before.status_code == 200
    assert before.json()[0]["id"] == newer["id"]

    sent = client.post(
        f"/conversations/{older['id']}/messages",
        json={"content": "This thread is active again"},
        headers=headers,
    )
    assert sent.status_code == 201

    after = client.get("/conversations", headers=headers)
    assert after.status_code == 200
    assert after.json()[0]["id"] == older["id"]


def test_customer_cannot_post_to_another_customers_conversation(
    client: TestClient,
    accounts,
    login_headers,
    fake_llm_provider,
    fake_knowledge_retriever,
) -> None:
    other_conversation_id = accounts["conversation_b_id"]
    response = client.post(
        f"/conversations/{other_conversation_id}/messages",
        json={"content": "Private message attempt"},
        headers=login_headers(accounts["customer_a"]["email"]),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Conversation not found"
    assert "Private message attempt" not in response.text
    assert fake_llm_provider.calls == []
    assert fake_knowledge_retriever.queries == []

    owner_view = client.get(
        f"/conversations/{other_conversation_id}/messages",
        headers=login_headers(accounts["customer_b"]["email"]),
    )
    assert owner_view.status_code == 200
    assert [message["content"] for message in owner_view.json()] == [
        "Customer B private message"
    ]


def test_send_message_requires_authentication(
    client: TestClient,
    accounts,
) -> None:
    response = client.post(
        f"/conversations/{accounts['conversation_a_id']}/messages",
        json={"content": "No token"},
    )

    assert response.status_code == 401


def test_send_message_validates_content_and_unknown_conversation(
    client: TestClient,
    accounts,
    login_headers,
) -> None:
    headers = login_headers(accounts["customer_a"]["email"])
    path = f"/conversations/{accounts['conversation_a_id']}/messages"

    for payload in (
        {"content": ""},
        {"content": "   "},
        {"content": "x" * 8001},
        {"content": "Valid text", "role": "assistant"},
        {"content": "Valid text", "user_id": str(accounts["customer_b"]["id"])},
    ):
        response = client.post(path, json=payload, headers=headers)
        assert response.status_code == 422, payload

    missing = client.post(
        f"/conversations/{uuid.uuid4()}/messages",
        json={"content": "Valid text"},
        headers=headers,
    )
    assert missing.status_code == 404


def test_model_can_request_order_tool_and_receive_database_result(
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
            ToolCall(
                id="call_order_1",
                name=ORDER_DETAILS_TOOL_NAME,
                arguments={"order_number": order_number},
            ),
        )
    ]
    fake_llm_provider.reply = (
        "Your order is processing and in transit. It contains two "
        "USB-C cables and is estimated to arrive today."
    )

    response = client.post(
        f"/conversations/{conversation['id']}/messages",
        json={"content": f"Where is my order {order_number}?"},
        headers=headers,
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["assistant_message"]["content"] == fake_llm_provider.reply
    metadata = body["assistant_message"]["metadata"]
    assert metadata["source"] == "llm"
    assert metadata["tool_rounds"] == 1
    assert metadata["tool_calls"] == [
        {
            "name": ORDER_DETAILS_TOOL_NAME,
            "arguments": {"order_number": order_number},
            "status": "ok",
        }
    ]

    assert len(fake_llm_provider.calls) == 2
    first_request = fake_llm_provider.calls[0]
    assert [message.role for message in first_request] == ["system", "user"]
    assert [
        definition.name
        for definition in fake_llm_provider.tool_definitions[0]
    ] == [ORDER_DETAILS_TOOL_NAME]

    second_request = fake_llm_provider.calls[1]
    assert [message.role for message in second_request] == [
        "system",
        "user",
        "assistant",
        "tool",
    ]
    assistant_request = second_request[2]
    assert assistant_request.content == ""
    assert assistant_request.tool_calls[0].name == ORDER_DETAILS_TOOL_NAME
    tool_message = second_request[3]
    assert tool_message.tool_call_id == "call_order_1"
    assert tool_message.tool_name == ORDER_DETAILS_TOOL_NAME
    tool_payload = json.loads(tool_message.content)
    assert tool_payload["ok"] is True
    assert tool_payload["data"]["status"] == "processing"
    assert tool_payload["data"]["shipping_status"] == "in_transit"
    assert tool_payload["data"]["estimated_delivery"]
    assert tool_payload["data"]["items"] == [
        {
            "product_name": "Test USB-C Cable",
            "quantity": 2,
            "unit_price": "9.99",
        }
    ]


def test_tool_cannot_return_another_customers_order(
    client: TestClient,
    accounts,
    login_headers,
    fake_llm_provider,
) -> None:
    headers = login_headers(accounts["customer_a"]["email"])
    conversation = _create_conversation(client, headers)
    other_order_number = accounts["order_b_number"]
    fake_llm_provider.pending_tool_calls = [
        (
            ToolCall(
                id="call_order_denied",
                name=ORDER_DETAILS_TOOL_NAME,
                arguments={"order_number": other_order_number},
            ),
        )
    ]
    fake_llm_provider.reply = (
        "I couldn't find that order for your account. Please check the "
        "order number."
    )

    response = client.post(
        f"/conversations/{conversation['id']}/messages",
        json={"content": f"Check order {other_order_number}"},
        headers=headers,
    )

    assert response.status_code == 201, response.text
    body = response.json()
    metadata = body["assistant_message"]["metadata"]
    assert metadata["tool_calls"] == [
        {
            "name": ORDER_DETAILS_TOOL_NAME,
            "arguments": {"order_number": other_order_number},
            "status": "error",
            "error": "order_not_found",
        }
    ]

    tool_payload = json.loads(fake_llm_provider.calls[1][-1].content)
    assert tool_payload["ok"] is False
    assert tool_payload["error"]["code"] == "order_not_found"
    assert "data" not in tool_payload
    assert "Test Bluetooth Speaker" not in response.text
    assert "49.99" not in response.text


@pytest.mark.parametrize(
    ("tool_name", "arguments", "expected_error"),
    [
        (
            ORDER_DETAILS_TOOL_NAME,
            {},
            "invalid_arguments",
        ),
        (
            ORDER_DETAILS_TOOL_NAME,
            {"order_number": "RX 2026 1001"},
            "invalid_arguments",
        ),
        (
            ORDER_DETAILS_TOOL_NAME,
            {
                "order_number": "RX-2026-1001",
                "authenticated_user_id": (
                    "00000000-0000-0000-0000-000000000000"
                ),
            },
            "invalid_arguments",
        ),
        (
            "execute_sql",
            {"sql": "SELECT * FROM users"},
            "unknown_tool",
        ),
    ],
)
def test_invalid_tool_requests_produce_controlled_results(
    client: TestClient,
    accounts,
    login_headers,
    fake_llm_provider,
    tool_name: str,
    arguments: dict,
    expected_error: str,
) -> None:
    headers = login_headers(accounts["customer_a"]["email"])
    conversation = _create_conversation(client, headers)
    fake_llm_provider.pending_tool_calls = [
        (
            ToolCall(
                id="call_invalid",
                name=tool_name,
                arguments=arguments,
            ),
        )
    ]
    fake_llm_provider.reply = (
        "I couldn't complete that lookup. Please check the information and "
        "try again."
    )

    response = client.post(
        f"/conversations/{conversation['id']}/messages",
        json={"content": "Please run the lookup"},
        headers=headers,
    )

    assert response.status_code == 201, response.text
    metadata = response.json()["assistant_message"]["metadata"]
    assert metadata["tool_calls"][0]["status"] == "error"
    assert metadata["tool_calls"][0]["error"] == expected_error

    tool_payload = json.loads(fake_llm_provider.calls[1][-1].content)
    assert tool_payload["ok"] is False
    assert tool_payload["error"]["code"] == expected_error
    assert "data" not in tool_payload


def test_database_failure_produces_a_controlled_tool_result(
    client: TestClient,
    accounts,
    login_headers,
    fake_llm_provider,
    monkeypatch,
) -> None:
    headers = login_headers(accounts["customer_a"]["email"])
    conversation = _create_conversation(client, headers)
    order_number = accounts["order_a_number"]
    fake_llm_provider.pending_tool_calls = [
        (
            ToolCall(
                id="call_db_failure",
                name=ORDER_DETAILS_TOOL_NAME,
                arguments={"order_number": order_number},
            ),
        )
    ]
    fake_llm_provider.reply = (
        "I couldn't check your order right now. Please try again in a moment."
    )

    def fail(*args, **kwargs):
        raise SQLAlchemyError("database password=super-secret")

    monkeypatch.setattr(
        order_tools.orders,
        "get_for_user_by_number",
        fail,
    )

    response = client.post(
        f"/conversations/{conversation['id']}/messages",
        json={"content": f"Check order {order_number}"},
        headers=headers,
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["assistant_message"]["content"] == fake_llm_provider.reply
    metadata = body["assistant_message"]["metadata"]
    assert metadata["tool_calls"][0]["error"] == "database_error"
    assert "super-secret" not in response.text

    tool_payload = json.loads(fake_llm_provider.calls[1][-1].content)
    assert tool_payload["ok"] is False
    assert tool_payload["error"]["code"] == "database_error"
    assert "super-secret" not in tool_payload["error"]["message"]


def test_repeated_tool_requests_are_bounded(
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
            ToolCall(
                id=f"call_loop_{index}",
                name=ORDER_DETAILS_TOOL_NAME,
                arguments={"order_number": order_number},
            ),
        )
        for index in range(MAX_TOOL_ROUNDS + 1)
    ]

    response = client.post(
        f"/conversations/{conversation['id']}/messages",
        json={"content": "Keep checking my order"},
        headers=headers,
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["assistant_message"]["content"] == TOOL_LIMIT_ASSISTANT_MESSAGE
    metadata = body["assistant_message"]["metadata"]
    assert metadata["source"] == "tool_limit"
    assert metadata["error"] == "tool_round_limit"
    assert metadata["tool_rounds"] == MAX_TOOL_ROUNDS
    assert len(metadata["tool_calls"]) == MAX_TOOL_ROUNDS
    assert len(fake_llm_provider.calls) == MAX_TOOL_ROUNDS + 1
