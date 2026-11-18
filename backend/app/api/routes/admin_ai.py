from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.ai.dependencies import get_llm_provider
from app.ai.providers.base import LLMProvider
from app.api.dependencies import require_admin
from app.db.session import get_db
from app.knowledge.dependencies import get_knowledge_retriever
from app.knowledge.retrieval import KnowledgeRetriever
from app.models import User
from app.repositories import conversations
from app.schemas.admin import AdminAITestRequest, AdminAITestResponse
from app.schemas.common import ErrorResponse
from app.schemas.conversation import ConversationRead, MessageRead
from app.services import conversations as conversation_service


router = APIRouter(prefix="/ai", tags=["Administration"])

ADMIN_TEST_TITLE = "Admin AI test"


@router.post(
    "/test",
    response_model=AdminAITestResponse,
    summary="Run a real agent turn and inspect routing, tools, and citations",
    responses={
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "The requested test conversation was not found.",
        }
    },
)
async def test_agent(
    payload: AdminAITestRequest,
    current_admin: User = Depends(require_admin),
    session: Session = Depends(get_db),
    provider: LLMProvider = Depends(get_llm_provider),
    retriever: KnowledgeRetriever = Depends(get_knowledge_retriever),
) -> AdminAITestResponse:
    """Exercise the production orchestrator from the administrator console.

    Tests use a real conversation owned by the signing-in administrator so
    multi-turn follow-ups behave exactly like customer chat. Assistant metadata
    exposes the selected intent, approved capabilities, tool calls, citations,
    and fallback details for inspection.
    """
    conversation_created = False
    if payload.conversation_id is not None:
        conversation = conversations.get_for_user(
            session,
            payload.conversation_id,
            current_admin.id,
            with_messages=False,
        )
        if conversation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Test conversation not found",
            )
    else:
        conversation = conversation_service.create_for_user(
            session,
            current_admin.id,
            title=ADMIN_TEST_TITLE,
        )
        conversation_created = True

    started = time.perf_counter()
    exchange = await conversation_service.add_customer_message(
        session,
        conversation.id,
        current_admin.id,
        content=payload.message,
        provider=provider,
        retriever=retriever,
    )
    latency_ms = round((time.perf_counter() - started) * 1000, 1)

    if exchange is None:  # pragma: no cover - ownership was checked above
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Test conversation not found",
        )

    conversation, user_message, assistant_message = exchange
    return AdminAITestResponse(
        conversation=ConversationRead.model_validate(conversation),
        user_message=MessageRead.model_validate(user_message),
        assistant_message=MessageRead.model_validate(assistant_message),
        conversation_created=conversation_created,
        latency_ms=latency_ms,
    )
