from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class MessageRead(BaseModel):
    """A conversation message.

    PostgreSQL stores ``metadata`` while the ORM attribute is
    ``message_metadata``; both names are accepted when serialising.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    role: Literal["user", "assistant", "tool"]
    content: str
    # ``metadata`` on a SQLAlchemy model resolves to the declarative MetaData,
    # so the ORM attribute is ``message_metadata``. The JSON field stays
    # ``metadata`` to match the database column and API contract.
    metadata: dict[str, Any] | None = Field(
        default=None,
        validation_alias="message_metadata",
    )
    created_at: datetime


class ConversationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str | None
    created_at: datetime
    updated_at: datetime


class ConversationDetail(ConversationRead):
    messages: list[MessageRead]
