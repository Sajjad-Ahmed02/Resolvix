"""Bounded conversation context for the support agent.

Only user and assistant turns are sent back to the model. Tool rows remain in
the conversation for auditing and UI history, and are inspected here to recover
safe routing hints such as the last successfully looked-up order number.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.ai.providers.base import ChatMessage
from app.ai.routing import Intent
from app.models import Message
from app.tools.order_tools import ORDER_DETAILS_TOOL_NAME

logger = logging.getLogger(__name__)

DEFAULT_MAX_HISTORY_MESSAGES = 40
DEFAULT_MAX_HISTORY_CHARS = 12000

TRUNCATION_MARKER = "[Earlier part of this message was truncated]\n"


@dataclass(frozen=True, slots=True)
class ConversationContext:
    """Provider-ready history plus routing hints from persisted rows."""

    history: tuple[ChatMessage, ...]
    last_user_message: str | None
    last_intent: Intent | None
    last_order_number: str | None
    last_order_summary: dict[str, Any] | None
    source_message_count: int
    history_message_count: int
    history_truncated: bool

    @property
    def has_order_context(self) -> bool:
        return self.last_order_number is not None


def _coerce_intent(value: object) -> Intent | None:
    if not isinstance(value, str):
        return None
    try:
        return Intent(value)
    except ValueError:
        return None


def _order_number_from_tool_metadata(
    metadata: dict[str, Any] | None,
) -> str | None:
    if not isinstance(metadata, dict):
        return None
    if metadata.get("tool") != ORDER_DETAILS_TOOL_NAME:
        return None
    if metadata.get("status") != "ok":
        return None
    order_number = metadata.get("order_number")
    return order_number if isinstance(order_number, str) and order_number else None


def _order_number_from_assistant_metadata(
    metadata: dict[str, Any] | None,
) -> str | None:
    if not isinstance(metadata, dict):
        return None
    tool_calls = metadata.get("tool_calls")
    if not isinstance(tool_calls, list):
        return None
    for entry in reversed(tool_calls):
        if not isinstance(entry, dict):
            continue
        if entry.get("name") != ORDER_DETAILS_TOOL_NAME:
            continue
        if entry.get("status") != "ok":
            continue
        arguments = entry.get("arguments")
        if not isinstance(arguments, dict):
            continue
        order_number = arguments.get("order_number")
        if isinstance(order_number, str) and order_number.strip():
            return order_number.strip().upper()
    return None


def _last_order_summary(
    messages: Sequence[Message],
) -> tuple[str | None, dict[str, Any] | None]:
    """Return the newest successful order lookup and its safe summary.

    Tool rows carry the compact summary. Assistant metadata is a fallback for
    conversations persisted before tool rows were introduced.
    """
    for message in reversed(messages):
        if message.role != "tool":
            continue
        metadata = getattr(message, "message_metadata", None)
        order_number = _order_number_from_tool_metadata(metadata)
        if not order_number:
            continue
        summary = (
            metadata.get("order_summary") if isinstance(metadata, dict) else None
        )
        return (
            order_number.strip().upper(),
            summary if isinstance(summary, dict) else None,
        )

    for message in reversed(messages):
        if message.role != "assistant":
            continue
        metadata = getattr(message, "message_metadata", None)
        order_number = _order_number_from_assistant_metadata(metadata)
        if order_number:
            return order_number, None
    return None, None


def _last_intent(messages: Sequence[Message]) -> Intent | None:
    for message in reversed(messages):
        if message.role != "assistant":
            continue
        metadata = getattr(message, "message_metadata", None)
        if not isinstance(metadata, dict):
            continue
        intent = _coerce_intent(metadata.get("intent"))
        if intent is not None:
            return intent
    return None


def _last_user_message(messages: Sequence[Message]) -> str | None:
    for message in reversed(messages):
        if message.role == "user" and message.content.strip():
            return message.content.strip()
    return None


def _truncate_content(content: str, budget: int) -> str:
    """Keep the newest part of a single oversized message."""
    if budget <= 0:
        return ""
    if len(content) <= budget:
        return content
    if budget <= len(TRUNCATION_MARKER):
        return content[-budget:]
    return TRUNCATION_MARKER + content[-(budget - len(TRUNCATION_MARKER)) :]


def build_conversation_context(
    messages: Sequence[Message],
    *,
    max_history_messages: int = DEFAULT_MAX_HISTORY_MESSAGES,
    max_history_chars: int = DEFAULT_MAX_HISTORY_CHARS,
) -> ConversationContext:
    """Build a bounded, provider-safe history from persisted messages.

    Selection is newest-first so the most recent turns survive the window. A
    leading assistant turn is removed because chat APIs expect the dialogue to
    start with a user message. Tool rows never enter the provider dialogue; the
    model already saw their results in the turn that executed them.
    """
    if max_history_messages < 1:
        raise ValueError("max_history_messages must be positive")
    if max_history_chars < 1:
        raise ValueError("max_history_chars must be positive")

    source_messages = list(messages)
    eligible = [
        message
        for message in source_messages
        if message.role in {"user", "assistant"} and message.content.strip()
    ]
    considered = eligible[-max_history_messages:]
    truncated = len(eligible) > len(considered)

    selected: list[ChatMessage] = []
    remaining = max_history_chars
    for message in reversed(considered):
        content = message.content
        if len(content) > remaining:
            if selected or not considered:
                truncated = True
                break
            content = _truncate_content(content, remaining)
            truncated = True
        if not content.strip():
            truncated = True
            break
        selected.append(
            ChatMessage(
                role="user" if message.role == "user" else "assistant",
                content=content,
            )
        )
        remaining -= len(content)
        if remaining <= 0:
            truncated = True
            break

    selected.reverse()
    while selected and selected[0].role == "assistant":
        selected.pop(0)
        truncated = True

    last_order_number, last_order_summary = _last_order_summary(source_messages)

    return ConversationContext(
        history=tuple(selected),
        last_user_message=_last_user_message(source_messages),
        last_intent=_last_intent(source_messages),
        last_order_number=last_order_number,
        last_order_summary=last_order_summary,
        source_message_count=len(source_messages),
        history_message_count=len(selected),
        history_truncated=truncated,
    )


__all__ = [
    "ConversationContext",
    "DEFAULT_MAX_HISTORY_CHARS",
    "DEFAULT_MAX_HISTORY_MESSAGES",
    "build_conversation_context",
]
