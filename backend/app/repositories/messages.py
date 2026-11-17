from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Message


def list_for_conversation(
    session: Session,
    conversation_id: UUID,
) -> list[Message]:
    """Return messages in chronological order."""
    return list(
        session.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at, Message.id)
        ).all()
    )


def list_recent_for_conversation(
    session: Session,
    conversation_id: UUID,
    *,
    limit: int,
) -> list[Message]:
    """Return the newest *limit* rows in chronological order.

    Callers must verify conversation ownership first. This bounded query keeps
    context assembly from loading an unbounded conversation history.
    """
    if limit < 1:
        raise ValueError("limit must be positive")
    rows = list(
        session.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(limit)
        ).all()
    )
    rows.reverse()
    return rows


def create(
    session: Session,
    conversation_id: UUID,
    *,
    role: str,
    content: str,
    metadata: dict[str, Any] | None = None,
    created_at: datetime | None = None,
) -> Message:
    """Persist a message. Callers must have verified conversation ownership."""
    message = Message(
        conversation_id=conversation_id,
        role=role,
        content=content,
        message_metadata=metadata,
    )
    if created_at is not None:
        message.created_at = created_at
    session.add(message)
    session.flush()
    return message
