from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ConversationCreate(BaseModel):
    """Optional title for a new conversation.

    Omitting the title is the normal flow: the first customer message becomes
    the conversation title so the sidebar stays readable.
    """

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=200)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("Conversation title must not be blank")
        return normalized


class MessageCreate(BaseModel):
    """A customer-authored message.

    The role is not accepted from the client. Customer messages always persist
    as ``user`` and the temporary reply always persists as ``assistant``.
    """

    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=8000)

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Message must not be empty")
        return normalized


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


class MessageExchange(BaseModel):
    """The persisted customer message and its temporary assistant reply."""

    conversation: ConversationRead
    user_message: MessageRead
    assistant_message: MessageRead
