from __future__ import annotations

import uuid
from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.ai.prompts import SYSTEM_PROMPT
from app.ai.providers.base import ProviderRateLimitError
from app.db.session import SessionLocal
from app.models import Conversation, Message
from app.services.conversations import FALLBACK_ASSISTANT_MESSAGE


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
