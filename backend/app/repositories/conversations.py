from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Conversation


def list_for_user(session: Session, user_id: UUID) -> list[Conversation]:
    """Return only the conversations owned by ``user_id``."""
    return list(
        session.scalars(
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.updated_at.desc(), Conversation.created_at.desc())
        ).all()
    )


def get_for_user(
    session: Session,
    conversation_id: UUID,
    user_id: UUID,
    *,
    with_messages: bool = True,
) -> Conversation | None:
    """Return a conversation only when it belongs to ``user_id``.

    Message-sending flows pass ``with_messages=False`` and then load a bounded
    recent window separately, so a long conversation is never fetched in full
    just to verify ownership.
    """
    statement = select(Conversation).where(
        Conversation.id == conversation_id,
        Conversation.user_id == user_id,
    )
    if with_messages:
        statement = statement.options(selectinload(Conversation.messages))
    return session.scalar(statement)


def get_by_id(session: Session, conversation_id: UUID) -> Conversation | None:
    """Return any conversation by id. Used by explicitly authorized services."""
    return session.get(Conversation, conversation_id)


def create_for_user(
    session: Session,
    user_id: UUID,
    *,
    title: str | None = None,
) -> Conversation:
    """Persist a new conversation for the authenticated user."""
    conversation = Conversation(user_id=user_id, title=title)
    session.add(conversation)
    session.flush()
    return conversation
