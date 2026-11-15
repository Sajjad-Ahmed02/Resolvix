from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.models import Conversation, Message
from app.repositories import conversations


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
