from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.ai.prompts import SYSTEM_PROMPT
from app.ai.providers.base import ChatMessage, LLMProvider, ProviderError
from app.models import Conversation, Message
from app.repositories import conversations, messages

logger = logging.getLogger(__name__)

AUTO_TITLE_MAX_LENGTH = 80
MAX_HISTORY_MESSAGES = 40

FALLBACK_ASSISTANT_MESSAGE = (
    "I'm sorry, I can't generate a reply right now. "
    "Please try again in a moment."
)


def _title_for_message(content: str) -> str:
    """Build a readable sidebar title from the first customer message."""
    title = " ".join(content.split())
    if len(title) > AUTO_TITLE_MAX_LENGTH:
        title = title[: AUTO_TITLE_MAX_LENGTH - 1].rstrip() + "…"
    return title or "New conversation"


def _history_for(conversation: Conversation) -> list[ChatMessage]:
    """Return recent customer/assistant turns in chronological order."""
    history = [
        ChatMessage(role=message.role, content=message.content)
        for message in conversation.messages
        if message.role in {"user", "assistant"}
    ]
    history = history[-MAX_HISTORY_MESSAGES:]
    # Gemini and most chat APIs expect a conversation to start with a user
    # turn, so drop an assistant message cut by the history limit.
    while history and history[0].role == "assistant":
        history.pop(0)
    return history


def create_for_user(
    session: Session,
    user_id: UUID,
    *,
    title: str | None = None,
) -> Conversation:
    """Create and persist a conversation owned by the authenticated user."""
    conversation = conversations.create_for_user(
        session,
        user_id,
        title=title,
    )
    session.commit()
    session.refresh(conversation)
    return conversation


def list_for_user(session: Session, user_id: UUID) -> list[Conversation]:
    """Return the authenticated user's conversations."""
    return conversations.list_for_user(session, user_id)


def get_for_user(
    session: Session,
    conversation_id: UUID,
    user_id: UUID,
) -> Conversation | None:
    """Return a conversation only when the authenticated user owns it."""
    return conversations.get_for_user(session, conversation_id, user_id)


def list_messages_for_user(
    session: Session,
    conversation_id: UUID,
    user_id: UUID,
) -> list[Message] | None:
    """Return messages for an owned conversation, or None when not owned."""
    conversation = conversations.get_for_user(session, conversation_id, user_id)
    if conversation is None:
        return None
    return conversation.messages


async def add_customer_message(
    session: Session,
    conversation_id: UUID,
    user_id: UUID,
    *,
    content: str,
    provider: LLMProvider,
) -> tuple[Conversation, Message, Message] | None:
    """Persist a customer message and a generated assistant reply.

    The customer message is committed before the provider call so it is never
    lost when a model times out or is unavailable. Provider failures are
    converted into a persisted fallback reply, keeping the endpoint useful and
    avoiding leaked vendor details.

    Returns ``None`` when the conversation does not exist or belongs to another
    user, so the API can answer with a non-disclosing 404. The first customer
    message becomes the conversation title, and the conversation timestamp is
    refreshed so it moves to the top of the sidebar.
    """
    conversation = conversations.get_for_user(
        session,
        conversation_id,
        user_id,
    )
    if conversation is None:
        return None

    history = _history_for(conversation)
    user_created_at = datetime.now(timezone.utc)

    user_message = messages.create(
        session,
        conversation.id,
        role="user",
        content=content,
        created_at=user_created_at,
    )
    if not conversation.title or not conversation.title.strip():
        conversation.title = _title_for_message(content)
    conversation.updated_at = user_created_at
    session.commit()
    session.refresh(user_message)

    history.append(ChatMessage(role="user", content=content))
    llm_messages = [
        ChatMessage(role="system", content=SYSTEM_PROMPT),
        *history,
    ]

    assistant_content: str
    assistant_metadata: dict[str, Any]
    try:
        response = await provider.generate(llm_messages)
    except ProviderError as error:
        logger.warning(
            "LLM provider %s failed for conversation %s: %s",
            provider.name,
            conversation.id,
            error,
        )
        assistant_content = FALLBACK_ASSISTANT_MESSAGE
        assistant_metadata = {
            "source": "fallback",
            "provider": provider.name,
            "model": provider.model,
            "fallback": True,
            "error": error.code,
            "reply_to": str(user_message.id),
        }
    except Exception:
        logger.exception(
            "Unexpected LLM provider failure for conversation %s",
            conversation.id,
        )
        assistant_content = FALLBACK_ASSISTANT_MESSAGE
        assistant_metadata = {
            "source": "fallback",
            "provider": provider.name,
            "model": provider.model,
            "fallback": True,
            "error": "unexpected_error",
            "reply_to": str(user_message.id),
        }
    else:
        assistant_content = response.content
        assistant_metadata = {
            "source": "llm",
            "provider": response.provider,
            "model": response.model,
            "reply_to": str(user_message.id),
        }
        if response.finish_reason:
            assistant_metadata["finish_reason"] = response.finish_reason
        if response.usage:
            assistant_metadata["usage"] = response.usage

    assistant_created_at = max(
        datetime.now(timezone.utc),
        user_created_at + timedelta(milliseconds=1),
    )
    assistant_message = messages.create(
        session,
        conversation.id,
        role="assistant",
        content=assistant_content,
        metadata=assistant_metadata,
        created_at=assistant_created_at,
    )
    conversation.updated_at = assistant_created_at

    session.commit()
    session.refresh(conversation)
    session.refresh(user_message)
    session.refresh(assistant_message)
    return conversation, user_message, assistant_message
