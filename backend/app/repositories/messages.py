from __future__ import annotations

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


def create(
    session: Session,
    conversation_id: UUID,
    *,
    role: str,
    content: str,
    metadata: dict[str, Any] | None = None,
) -> Message:
    """Persist a message. Callers must have verified conversation ownership."""
    message = Message(
        conversation_id=conversation_id,
        role=role,
        content=content,
        message_metadata=metadata,
    )
    session.add(message)
    session.flush()
    return message
