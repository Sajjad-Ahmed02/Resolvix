from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import Conversation, Message
from app.repositories import conversations, messages


AUTO_TITLE_MAX_LENGTH = 80

PLACEHOLDER_ASSISTANT_MESSAGE = (
    "Thanks for your message. It has been saved. AI-generated answers are "
    "not enabled yet, so this temporary reply confirms the chat workflow is "
    "working."
)


def _title_for_message(content: str) -> str:
    """Build a readable sidebar title from the first customer message."""
    title = " ".join(content.split())
    if len(title) > AUTO_TITLE_MAX_LENGTH:
        title = title[: AUTO_TITLE_MAX_LENGTH - 1].rstrip() + "…"
    return title or "New conversation"


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


def add_customer_message(
    session: Session,
    conversation_id: UUID,
    user_id: UUID,
    *,
    content: str,
) -> tuple[Conversation, Message, Message] | None:
    """Persist a customer message and a temporary assistant reply.

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

    user_created_at = datetime.now(timezone.utc)
    assistant_created_at = user_created_at + timedelta(milliseconds=1)

    user_message = messages.create(
        session,
        conversation.id,
        role="user",
        content=content,
        created_at=user_created_at,
    )
    assistant_message = messages.create(
        session,
        conversation.id,
        role="assistant",
        content=PLACEHOLDER_ASSISTANT_MESSAGE,
        metadata={
            "temporary": True,
            "source": "placeholder",
            "reply_to": str(user_message.id),
        },
        created_at=assistant_created_at,
    )

    if not conversation.title or not conversation.title.strip():
        conversation.title = _title_for_message(content)
    conversation.updated_at = assistant_created_at

    session.commit()
    session.refresh(conversation)
    session.refresh(user_message)
    session.refresh(assistant_message)
    return conversation, user_message, assistant_message
