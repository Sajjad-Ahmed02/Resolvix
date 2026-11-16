from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.ai.prompts import SYSTEM_PROMPT
from app.ai.providers.base import (
    ChatMessage,
    LLMProvider,
    LLMResponse,
    ProviderError,
)
from app.knowledge.grounding import build_context_prompt
from app.knowledge.retrieval import KnowledgeRetriever, RetrievedChunk
from app.models import Conversation, Message
from app.repositories import conversations, messages
from app.tools.base import ToolContext
from app.tools.registry import (
    DEFAULT_TOOL_REGISTRY,
    ToolRegistry,
    audit_tool_call,
)

logger = logging.getLogger(__name__)

AUTO_TITLE_MAX_LENGTH = 80
MAX_HISTORY_MESSAGES = 40
MAX_TOOL_ROUNDS = 3

FALLBACK_ASSISTANT_MESSAGE = (
    "I'm sorry, I can't generate a reply right now. "
    "Please try again in a moment."
)
TOOL_LIMIT_ASSISTANT_MESSAGE = (
    "I couldn't finish checking that information right now. "
    "Please try again in a moment."
)


def _title_for_message(content: str) -> str:
    """Build a readable sidebar title from the first customer message."""
    title = " ".join(content.split())
    if len(title) > AUTO_TITLE_MAX_LENGTH:
        title = title[: AUTO_TITLE_MAX_LENGTH - 1].rstrip() + "…"
    return title or "New conversation"


def _history_for(conversation: Conversation) -> list[ChatMessage]:
    """Return recent customer/assistant turns in chronological order."""
    history = [
        ChatMessage(role=message.role, content=message.content)
        for message in conversation.messages
        if message.role in {"user", "assistant"}
    ]
    history = history[-MAX_HISTORY_MESSAGES:]
    # Gemini and most chat APIs expect a conversation to start with a user
    # turn, so drop an assistant message cut by the history limit.
    while history and history[0].role == "assistant":
        history.pop(0)
    return history


async def _generate_with_tools(
    provider: LLMProvider,
    llm_messages: list[ChatMessage],
    *,
    registry: ToolRegistry,
    context: ToolContext,
    audit: list[dict[str, Any]],
) -> tuple[LLMResponse | None, int]:
    """Run the bounded model -> validate -> execute -> tool result loop.

    Returns ``None`` when the model keeps requesting tools after
    ``MAX_TOOL_ROUNDS`` executed rounds. The caller persists a controlled reply
    instead of allowing an unbounded agent loop.
    """
    definitions = registry.definitions
    executed_rounds = 0

    for round_index in range(MAX_TOOL_ROUNDS + 1):
        response = await provider.generate(
            llm_messages,
            tools=definitions or None,
        )
        if not response.tool_calls:
            return response, executed_rounds
        if round_index >= MAX_TOOL_ROUNDS:
            return None, executed_rounds

        llm_messages.append(
            ChatMessage(
                role="assistant",
                content=response.content,
                tool_calls=response.tool_calls,
            )
        )
        for call in response.tool_calls:
            # Arguments are untrusted model output. The registry checks the
            # allow-list and the tool validates them against its schema.
            outcome = registry.execute(call, context)
            audit.append(audit_tool_call(call, outcome))
            llm_messages.append(
                ChatMessage(
                    role="tool",
                    content=outcome.to_json(),
                    tool_call_id=call.id,
                    tool_name=call.name,
                )
            )
        executed_rounds += 1

    return None, executed_rounds


def create_for_user(
    session: Session,
    user_id: UUID,
    *,
    title: str | None = None,
) -> Conversation:
    """Create and persist a conversation owned by the authenticated user."""
    conversation = conversations.create_for_user(
        session,
        user_id,
        title=title,
    )
    session.commit()
    session.refresh(conversation)
    return conversation


def list_for_user(session: Session, user_id: UUID) -> list[Conversation]:
    """Return the authenticated user's conversations."""
    return conversations.list_for_user(session, user_id)


def get_for_user(
    session: Session,
    conversation_id: UUID,
    user_id: UUID,
) -> Conversation | None:
    """Return a conversation only when the authenticated user owns it."""
    return conversations.get_for_user(session, conversation_id, user_id)


def list_messages_for_user(
    session: Session,
    conversation_id: UUID,
    user_id: UUID,
) -> list[Message] | None:
    """Return messages for an owned conversation, or None when not owned."""
    conversation = conversations.get_for_user(session, conversation_id, user_id)
    if conversation is None:
        return None
    return conversation.messages


async def add_customer_message(
    session: Session,
    conversation_id: UUID,
    user_id: UUID,
    *,
    content: str,
    provider: LLMProvider,
    retriever: KnowledgeRetriever,
    tool_registry: ToolRegistry | None = None,
) -> tuple[Conversation, Message, Message] | None:
    """Persist a customer message and a generated assistant reply.

    The customer message is committed before retrieval and the provider call so
    it is never lost when a model times out or is unavailable. Relevant policy
    and FAQ chunks are retrieved before generation and passed as reference
    material. The model may request allow-listed tools; the registry validates
    every name and argument and executes the backend function with a trusted
    user context. Provider failures are converted into a persisted fallback
    reply, keeping the endpoint useful and avoiding leaked vendor details.

    Returns ``None`` when the conversation does not exist or belongs to another
    user, so the API can answer with a non-disclosing 404. The first customer
    message becomes the conversation title, and the conversation timestamp is
    refreshed so it moves to the top of the sidebar.
    """
    conversation = conversations.get_for_user(
        session,
        conversation_id,
        user_id,
    )
    if conversation is None:
        return None

    history = _history_for(conversation)
    user_created_at = datetime.now(timezone.utc)

    user_message = messages.create(
        session,
        conversation.id,
        role="user",
        content=content,
        created_at=user_created_at,
    )
    if not conversation.title or not conversation.title.strip():
        conversation.title = _title_for_message(content)
    conversation.updated_at = user_created_at
    session.commit()
    session.refresh(user_message)

    history.append(ChatMessage(role="user", content=content))

    retrieved: list[RetrievedChunk] = []
    try:
        retrieved = await retriever.retrieve(session, content)
    except Exception:
        logger.exception(
            "Knowledge retrieval failed for conversation %s; answering "
            "without reference material.",
            conversation.id,
        )

    llm_messages = [ChatMessage(role="system", content=SYSTEM_PROMPT)]
    if retrieved:
        llm_messages.append(
            ChatMessage(role="system", content=build_context_prompt(retrieved))
        )
    llm_messages.extend(history)

    retrieval_metadata: dict[str, Any] = {
        "grounded": bool(retrieved),
        "sources": [chunk.as_metadata() for chunk in retrieved],
    }
    registry = (
        tool_registry if tool_registry is not None else DEFAULT_TOOL_REGISTRY
    )
    tool_context = ToolContext(
        session=session,
        user_id=user_id,
        conversation_id=conversation.id,
    )
    tool_audit: list[dict[str, Any]] = []
    tool_rounds = 0

    assistant_content: str
    assistant_metadata: dict[str, Any]
    try:
        response, tool_rounds = await _generate_with_tools(
            provider,
            llm_messages,
            registry=registry,
            context=tool_context,
            audit=tool_audit,
        )
    except ProviderError as error:
        logger.warning(
            "LLM provider %s failed for conversation %s: %s",
            provider.name,
            conversation.id,
            error,
        )
        assistant_content = FALLBACK_ASSISTANT_MESSAGE
        assistant_metadata = {
            "source": "fallback",
            "provider": provider.name,
            "model": provider.model,
            "fallback": True,
            "error": error.code,
            "reply_to": str(user_message.id),
            **retrieval_metadata,
        }
    except Exception:
        logger.exception(
            "Unexpected LLM provider failure for conversation %s",
            conversation.id,
        )
        assistant_content = FALLBACK_ASSISTANT_MESSAGE
        assistant_metadata = {
            "source": "fallback",
            "provider": provider.name,
            "model": provider.model,
            "fallback": True,
            "error": "unexpected_error",
            "reply_to": str(user_message.id),
            **retrieval_metadata,
        }
    else:
        if response is None:
            assistant_content = TOOL_LIMIT_ASSISTANT_MESSAGE
            assistant_metadata = {
                "source": "tool_limit",
                "provider": provider.name,
                "model": provider.model,
                "fallback": True,
                "error": "tool_round_limit",
                "reply_to": str(user_message.id),
                **retrieval_metadata,
            }
        else:
            assistant_content = response.content
            assistant_metadata = {
                "source": "llm",
                "provider": response.provider,
                "model": response.model,
                "reply_to": str(user_message.id),
                **retrieval_metadata,
            }
            if response.finish_reason:
                assistant_metadata["finish_reason"] = response.finish_reason
            if response.usage:
                assistant_metadata["usage"] = response.usage

    if tool_audit:
        assistant_metadata["tool_calls"] = tool_audit
        assistant_metadata["tool_rounds"] = tool_rounds

    assistant_created_at = max(
        datetime.now(timezone.utc),
        user_created_at + timedelta(milliseconds=1),
    )
    assistant_message = messages.create(
        session,
        conversation.id,
        role="assistant",
        content=assistant_content,
        metadata=assistant_metadata,
        created_at=assistant_created_at,
    )
    conversation.updated_at = assistant_created_at

    session.commit()
    session.refresh(conversation)
    session.refresh(user_message)
    session.refresh(assistant_message)
    return conversation, user_message, assistant_message
