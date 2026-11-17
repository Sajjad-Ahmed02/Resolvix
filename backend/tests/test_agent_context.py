from __future__ import annotations

from typing import Any

import pytest

from app.ai.context import TRUNCATION_MARKER, build_conversation_context
from app.ai.routing import Intent
from app.models import Message


def _message(
    role: str,
    content: str,
    metadata: dict[str, Any] | None = None,
) -> Message:
    return Message(
        role=role,
        content=content,
        message_metadata=metadata,
    )


def test_context_keeps_the_bounded_newest_dialogue() -> None:
    messages = [
        _message("user", "first"),
        _message("assistant", "second"),
        _message("user", "third"),
        _message("assistant", "fourth"),
        _message("user", "fifth"),
    ]

    context = build_conversation_context(
        messages,
        max_history_messages=4,
        max_history_chars=1000,
    )

    assert [
        (message.role, message.content) for message in context.history
    ] == [
        ("user", "third"),
        ("assistant", "fourth"),
        ("user", "fifth"),
    ]
    assert context.source_message_count == 5
    assert context.history_message_count == 3
    assert context.history_truncated is True


def test_context_drops_a_leading_assistant_turn() -> None:
    messages = [
        _message("user", "first"),
        _message("assistant", "second"),
        _message("user", "third"),
    ]

    context = build_conversation_context(
        messages,
        max_history_messages=2,
        max_history_chars=1000,
    )

    assert [
        (message.role, message.content) for message in context.history
    ] == [("user", "third")]
    assert context.history_truncated is True


def test_context_enforces_the_character_budget() -> None:
    messages = [
        _message("user", "first message"),
        _message("assistant", "second message"),
        _message("user", "x" * 50),
    ]

    context = build_conversation_context(
        messages,
        max_history_messages=10,
        max_history_chars=60,
    )

    assert [(message.role, message.content) for message in context.history] == [
        ("user", "x" * 50)
    ]
    assert context.history_truncated is True


def test_context_truncates_one_oversized_newest_message() -> None:
    content = "beginning " + ("z" * 200)

    context = build_conversation_context(
        [_message("user", content)],
        max_history_messages=10,
        max_history_chars=100,
    )

    assert len(context.history) == 1
    assert context.history[0].role == "user"
    assert context.history[0].content.startswith(TRUNCATION_MARKER)
    assert context.history[0].content.endswith("z" * 20)
    assert context.history_truncated is True


def test_context_excludes_tool_rows_from_provider_history() -> None:
    messages = [
        _message("user", "Where is my order RX-2026-1001?"),
        _message(
            "tool",
            "Order lookup completed for RX-2026-1001.",
            {
                "tool": "get_order_details",
                "status": "ok",
                "order_number": "rx-2026-1001",
                "order_summary": {
                    "status": "processing",
                    "shipping_status": "in_transit",
                },
            },
        ),
        _message(
            "assistant",
            "Your order is being processed.",
            {"intent": "order_status"},
        ),
        _message("user", "When will it arrive?"),
    ]

    context = build_conversation_context(
        messages,
        max_history_messages=10,
        max_history_chars=1000,
    )

    assert [
        (message.role, message.content) for message in context.history
    ] == [
        ("user", "Where is my order RX-2026-1001?"),
        ("assistant", "Your order is being processed."),
        ("user", "When will it arrive?"),
    ]
    assert context.last_order_number == "RX-2026-1001"
    assert context.last_order_summary == {
        "status": "processing",
        "shipping_status": "in_transit",
    }
    assert context.last_intent is Intent.ORDER_STATUS
    assert context.last_user_message == "When will it arrive?"
    assert context.has_order_context is True


def test_context_recovers_order_from_assistant_metadata_fallback() -> None:
    messages = [
        _message("user", "Check my order"),
        _message(
            "assistant",
            "I found it.",
            {
                "intent": "order_items",
                "tool_calls": [
                    {
                        "name": "get_order_details",
                        "arguments": {"order_number": "rx-2026-1001"},
                        "status": "ok",
                    }
                ],
            },
        ),
    ]

    context = build_conversation_context(messages)

    assert context.last_order_number == "RX-2026-1001"
    assert context.last_order_summary is None
    assert context.last_intent is Intent.ORDER_ITEMS


def test_context_ignores_failed_tool_rows_for_order_hints() -> None:
    messages = [
        _message("user", "Check my order RX-2026-9999"),
        _message(
            "tool",
            "Order lookup did not find an order for this account.",
            {
                "tool": "get_order_details",
                "status": "error",
                "order_number": "RX-2026-9999",
                "error": "order_not_found",
            },
        ),
        _message("assistant", "I could not find that order."),
    ]

    context = build_conversation_context(messages)

    assert context.last_order_number is None
    assert context.has_order_context is False


def test_context_handles_an_empty_conversation() -> None:
    context = build_conversation_context([])

    assert context.history == ()
    assert context.last_user_message is None
    assert context.last_intent is None
    assert context.last_order_number is None
    assert context.source_message_count == 0
    assert context.history_message_count == 0
    assert context.history_truncated is False


@pytest.mark.parametrize(
    ("max_messages", "max_chars"),
    [(0, 1000), (10, 0)],
)
def test_context_rejects_invalid_limits(
    max_messages: int,
    max_chars: int,
) -> None:
    with pytest.raises(ValueError):
        build_conversation_context(
            [],
            max_history_messages=max_messages,
            max_history_chars=max_chars,
        )
