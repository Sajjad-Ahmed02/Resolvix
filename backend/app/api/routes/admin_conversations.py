from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import require_admin
from app.db.session import get_db
from app.repositories import messages
from app.schemas.admin import (
    AdminConversationDetail,
    AdminConversationRead,
)
from app.schemas.common import ErrorResponse
from app.schemas.conversation import MessageRead
from app.services import admin as admin_service


router = APIRouter(
    prefix="/conversations",
    tags=["Administration"],
    dependencies=[Depends(require_admin)],
)


@router.get(
    "",
    response_model=list[AdminConversationRead],
    summary="List every conversation with its owner and message count",
)
def list_conversations(
    session: Session = Depends(get_db),
) -> list[AdminConversationRead]:
    return [
        AdminConversationRead(
            id=conversation.id,
            user_id=user.id,
            customer_name=user.name,
            customer_email=user.email,
            title=conversation.title,
            message_count=message_count,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
        )
        for conversation, user, message_count in admin_service.list_conversations(
            session
        )
    ]


@router.get(
    "/{conversation_id}",
    response_model=AdminConversationDetail,
    summary="Inspect one conversation and all persisted messages",
    responses={
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "Conversation not found.",
        }
    },
)
def get_conversation(
    conversation_id: UUID,
    session: Session = Depends(get_db),
) -> AdminConversationDetail:
    try:
        conversation = admin_service.get_conversation(
            session,
            conversation_id,
        )
    except admin_service.AdminNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from None

    stored_messages = messages.list_for_conversation(
        session,
        conversation.id,
    )
    return AdminConversationDetail(
        id=conversation.id,
        user_id=conversation.user.id,
        customer_name=conversation.user.name,
        customer_email=conversation.user.email,
        title=conversation.title,
        message_count=len(stored_messages),
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        messages=[
            MessageRead.model_validate(message)
            for message in stored_messages
        ],
    )
