from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models import Conversation, Message, User


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


def get_with_user(
    session: Session,
    conversation_id: UUID,
) -> Conversation | None:
    """Return any conversation with its owner for administrator inspection."""
    return session.scalar(
        select(Conversation)
        .where(Conversation.id == conversation_id)
        .options(joinedload(Conversation.user))
    )


def list_all_with_counts(
    session: Session,
) -> list[tuple[Conversation, User, int]]:
    """Return every conversation with its owner and message count."""
    statement = (
        select(
            Conversation,
            User,
            func.count(Message.id).label("message_count"),
        )
        .join(User, Conversation.user_id == User.id)
        .outerjoin(Message, Message.conversation_id == Conversation.id)
        .group_by(Conversation.id, User.id)
        .order_by(Conversation.updated_at.desc(), Conversation.id)
    )
    return [
        (row[0], row[1], int(row[2]))
        for row in session.execute(statement).all()
    ]


def count(session: Session) -> int:
    return int(
        session.scalar(select(func.count()).select_from(Conversation)) or 0
    )


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
