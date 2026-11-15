from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.db.session import get_db
from app.models import User
from app.schemas.common import ErrorResponse
from app.schemas.conversation import (
    ConversationDetail,
    ConversationRead,
    MessageRead,
)
from app.services import conversations as conversation_service


router = APIRouter(prefix="/conversations", tags=["Conversations"])


@router.get(
    "",
    response_model=list[ConversationRead],
    summary="List the authenticated user's conversations",
)
def list_conversations(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> list[ConversationRead]:
    return conversation_service.list_for_user(session, current_user.id)


@router.get(
    "/{conversation_id}",
    response_model=ConversationDetail,
    summary="Read one conversation owned by the authenticated user",
    responses={
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "Conversation does not exist or belongs to another user.",
        }
    },
)
def get_conversation(
    conversation_id: UUID,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> ConversationDetail:
    conversation = conversation_service.get_for_user(
        session,
        conversation_id,
        current_user.id,
    )
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )
    return conversation


@router.get(
    "/{conversation_id}/messages",
    response_model=list[MessageRead],
    summary="List messages in one owned conversation",
    responses={
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "Conversation does not exist or belongs to another user.",
        }
    },
)
def list_messages(
    conversation_id: UUID,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> list[MessageRead]:
    messages = conversation_service.list_messages_for_user(
        session,
        conversation_id,
        current_user.id,
    )
    if messages is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )
    return messages
