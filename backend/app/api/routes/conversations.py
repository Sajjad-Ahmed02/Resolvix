from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.ai.dependencies import get_llm_provider
from app.ai.providers.base import LLMProvider
from app.api.dependencies import get_current_user
from app.db.session import get_db
from app.knowledge.dependencies import get_knowledge_retriever
from app.knowledge.retrieval import KnowledgeRetriever
from app.models import User
from app.schemas.common import ErrorResponse
from app.schemas.conversation import (
    ConversationCreate,
    ConversationDetail,
    ConversationRead,
    MessageCreate,
    MessageExchange,
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


@router.post(
    "",
    response_model=ConversationRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a conversation for the authenticated user",
)
def create_conversation(
    payload: ConversationCreate,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> ConversationRead:
    """Create an empty conversation.

    The title is optional. When omitted, the first customer message becomes the
    sidebar title automatically. Ownership always comes from the bearer token.
    """
    return conversation_service.create_for_user(
        session,
        current_user.id,
        title=payload.title,
    )


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


@router.post(
    "/{conversation_id}/messages",
    response_model=MessageExchange,
    status_code=status.HTTP_201_CREATED,
    summary="Save a customer message and generate an assistant reply",
    responses={
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "Conversation does not exist or belongs to another user.",
        }
    },
)
async def send_message(
    conversation_id: UUID,
    payload: MessageCreate,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
    provider: LLMProvider = Depends(get_llm_provider),
    retriever: KnowledgeRetriever = Depends(get_knowledge_retriever),
) -> MessageExchange:
    """Persist the customer message and the provider-generated reply.

    The active provider is selected with ``LLM_PROVIDER``. Relevant FAQ and
    policy chunks are retrieved with local embeddings and added to the system
    context. Provider failures are stored as a controlled fallback reply
    instead of leaking vendor errors or returning an HTTP 500. A different
    customer's conversation returns 404 and never receives a message.
    """
    exchange = await conversation_service.add_customer_message(
        session,
        conversation_id,
        current_user.id,
        content=payload.content,
        provider=provider,
        retriever=retriever,
    )
    if exchange is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

    conversation, user_message, assistant_message = exchange
    return MessageExchange(
        conversation=ConversationRead.model_validate(conversation),
        user_message=MessageRead.model_validate(user_message),
        assistant_message=MessageRead.model_validate(assistant_message),
    )
