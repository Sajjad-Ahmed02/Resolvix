from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.ai.orchestrator import (
    FALLBACK_ASSISTANT_MESSAGE,
    MAX_TOOL_ROUNDS,
    TOOL_LIMIT_ASSISTANT_MESSAGE,
    AgentResult,
    SupportAgentOrchestrator,
    ToolExecution,
)
from app.ai.providers.base import LLMProvider
from app.ai.routing import Capability, Intent
from app.core.config import settings
from app.knowledge.retrieval import KnowledgeRetriever
from app.models import Conversation, Message
from app.repositories import conversations, messages
from app.tools.knowledge_tools import KNOWLEDGE_SEARCH_TOOL_NAME
from app.tools.order_tools import ORDER_DETAILS_TOOL_NAME
from app.tools.registry import ToolRegistry, audit_tool_call

logger = logging.getLogger(__name__)

AUTO_TITLE_MAX_LENGTH = 80

__all__ = [
    "FALLBACK_ASSISTANT_MESSAGE",
    "MAX_TOOL_ROUNDS",
    "TOOL_LIMIT_ASSISTANT_MESSAGE",
    "add_customer_message",
    "create_for_user",
    "get_for_user",
    "list_for_user",
    "list_messages_for_user",
]


def _title_for_message(content: str) -> str:
    """Build a readable sidebar title from the first customer message."""
    title = " ".join(content.split())
    if len(title) > AUTO_TITLE_MAX_LENGTH:
        title = title[: AUTO_TITLE_MAX_LENGTH - 1].rstrip() + "…"
    return title or "New conversation"


def _unexpected_orchestration_result(provider: LLMProvider) -> AgentResult:
    """Controlled reply if orchestration itself fails unexpectedly."""
    return AgentResult(
        content=FALLBACK_ASSISTANT_MESSAGE,
        source="fallback",
        intent=Intent.GENERAL,
        capabilities=(Capability.LLM_RESPONSE,),
        provider=provider.name,
        model=provider.model,
        error="orchestration_error",
        fallback=True,
    )


def _assistant_metadata(
    result: AgentResult,
    *,
    user_message_id: UUID,
) -> dict[str, Any]:
    """Build compact, customer-safe metadata for a persisted reply."""
    metadata: dict[str, Any] = {
        "source": result.source,
        "provider": result.provider,
        "model": result.model,
        "reply_to": str(user_message_id),
        "intent": result.intent.value,
        "capabilities": [
            capability.value for capability in result.capabilities
        ],
        "grounded": result.grounded,
        "sources": [chunk.as_metadata() for chunk in result.retrieved],
        "context_messages": result.history_message_count,
    }
    if result.history_truncated:
        metadata["history_truncated"] = True
    if result.fallback:
        metadata["fallback"] = True
    if result.error:
        metadata["error"] = result.error
    if result.clarification_reason:
        metadata["clarification_reason"] = result.clarification_reason
    if result.guard_applied:
        metadata["guard_applied"] = True
    if result.finish_reason:
        metadata["finish_reason"] = result.finish_reason
    if result.usage:
        metadata["usage"] = result.usage

    audit = result.tool_audit
    if audit:
        metadata["tool_calls"] = audit
        metadata["tool_rounds"] = result.tool_rounds
    return metadata


def _tool_message_content(execution: ToolExecution) -> str:
    """Human-readable summary shown in persisted tool rows."""
    outcome = execution.outcome
    call = execution.call

    if call.name == ORDER_DETAILS_TOOL_NAME:
        order_number = call.arguments.get("order_number")
        if outcome.ok:
            return f"Order lookup completed for {order_number}."
        if outcome.error_code == "order_not_found":
            return "Order lookup did not find an order for this account."
        if outcome.error_code == "database_error":
            return "Order lookup failed because order information was unavailable."
        if outcome.error_code == "duplicate_tool_call":
            return "Order lookup was not repeated; the earlier result applies."
        if outcome.error_code == "tool_call_limit":
            return "Order lookup was not run because the tool-call limit was reached."
        return "Order lookup could not be completed."

    if call.name == KNOWLEDGE_SEARCH_TOOL_NAME:
        if outcome.ok and isinstance(outcome.data, dict):
            count = outcome.data.get("result_count", 0)
            if count:
                return f"Knowledge search found {count} relevant passage(s)."
            return "Knowledge search found no relevant passages."
        if outcome.error_code == "duplicate_tool_call":
            return "Knowledge search was not repeated; the earlier result applies."
        if outcome.error_code == "tool_call_limit":
            return (
                "Knowledge search was not run because the tool-call limit was "
                "reached."
            )
        return "Knowledge search could not be completed."

    return f"{call.name} finished." if outcome.ok else f"{call.name} failed."


def _tool_message_metadata(execution: ToolExecution) -> dict[str, Any]:
    """Persist safe arguments, citations, and status for one tool attempt."""
    call = execution.call
    outcome = execution.outcome
    audit = audit_tool_call(call, outcome)
    metadata: dict[str, Any] = {
        "tool": call.name,
        "tool_call_id": call.id,
        "arguments": audit.get("arguments", {}),
        "status": "ok" if outcome.ok else "error",
        "preflight": execution.preflight,
    }
    if not execution.executed:
        metadata["executed"] = False
    if execution.duplicate:
        metadata["duplicate"] = True
    if outcome.error_code:
        metadata["error"] = outcome.error_code

    if call.name == ORDER_DETAILS_TOOL_NAME:
        order_number = call.arguments.get("order_number")
        if isinstance(order_number, str):
            metadata["order_number"] = order_number.strip().upper()
        if outcome.ok and isinstance(outcome.data, dict):
            metadata["order_summary"] = {
                key: outcome.data.get(key)
                for key in (
                    "status",
                    "shipping_status",
                    "estimated_delivery",
                    "total_amount",
                )
                if key in outcome.data
            }
    elif call.name == KNOWLEDGE_SEARCH_TOOL_NAME:
        query = call.arguments.get("query")
        if isinstance(query, str):
            metadata["query"] = query
        if outcome.ok and isinstance(outcome.data, dict):
            metadata["result_count"] = outcome.data.get("result_count", 0)
            results = outcome.data.get("results")
            if isinstance(results, list):
                metadata["sources"] = [
                    {
                        key: result.get(key)
                        for key in (
                            "source_type",
                            "source_id",
                            "title",
                            "category",
                            "chunk_index",
                            "distance",
                        )
                        if key in result
                    }
                    for result in results
                    if isinstance(result, dict)
                ]
    return metadata


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
    """Persist a customer message and a context-aware assistant reply.

    Ownership is checked before any row is read or written. The recent message
    window is loaded through a bounded repository query, then the central
    orchestrator resolves intent, executes approved backend capabilities, and
    calls the provider. The customer message is committed first so it survives
    a provider or tool failure. Assistant and useful tool rows are committed
    together afterwards.

    Returns ``None`` when the conversation does not exist or belongs to another
    user, so the API can answer with a non-disclosing 404.
    """
    conversation = conversations.get_for_user(
        session,
        conversation_id,
        user_id,
        with_messages=False,
    )
    if conversation is None:
        logger.warning(
            "Conversation access denied",
            extra={
                "event": "conversation_access_denied",
                "operation": "conversation_message",
                "conversation_id": str(conversation_id),
                "user_id": str(user_id),
            },
        )
        return None

    previous_messages = messages.list_recent_for_conversation(
        session,
        conversation.id,
        limit=settings.AGENT_CONTEXT_MESSAGE_LIMIT,
    )
    user_created_at = datetime.now(timezone.utc)
    if previous_messages:
        # Keep chronological ordering even when two turns arrive within the
        # same clock tick.
        user_created_at = max(
            user_created_at,
            previous_messages[-1].created_at + timedelta(milliseconds=1),
        )

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

    orchestrator = SupportAgentOrchestrator(
        provider,
        retriever,
        registry=tool_registry,
        max_history_messages=settings.AGENT_MAX_HISTORY_MESSAGES,
        max_history_chars=settings.AGENT_MAX_HISTORY_CHARS,
        max_tool_rounds=settings.AGENT_MAX_TOOL_ROUNDS,
        max_tool_calls=settings.AGENT_MAX_TOOL_CALLS,
    )
    try:
        result = await orchestrator.respond(
            session=session,
            user_id=user_id,
            conversation_id=conversation.id,
            content=content,
            previous_messages=previous_messages,
        )
    except Exception:
        logger.exception(
            "Unexpected agent orchestration failure for conversation %s",
            conversation.id,
        )
        result = _unexpected_orchestration_result(provider)

    last_created_at = user_created_at
    for execution in result.tool_executions:
        if not execution.executed:
            continue
        last_created_at = max(
            datetime.now(timezone.utc),
            last_created_at + timedelta(milliseconds=1),
        )
        messages.create(
            session,
            conversation.id,
            role="tool",
            content=_tool_message_content(execution),
            metadata=_tool_message_metadata(execution),
            created_at=last_created_at,
        )

    assistant_created_at = max(
        datetime.now(timezone.utc),
        last_created_at + timedelta(milliseconds=1),
    )
    assistant_message = messages.create(
        session,
        conversation.id,
        role="assistant",
        content=result.content,
        metadata=_assistant_metadata(
            result,
            user_message_id=user_message.id,
        ),
        created_at=assistant_created_at,
    )
    conversation.updated_at = assistant_created_at

    session.commit()
    session.refresh(conversation)
    session.refresh(user_message)
    session.refresh(assistant_message)
    logger.info(
        "Assistant reply persisted",
        extra={
            "event": "conversation_reply_persisted",
            "operation": "conversation_message",
            "conversation_id": str(conversation.id),
            "message_id": str(assistant_message.id),
            "source": result.source,
            "grounded": result.grounded,
            "fallback": result.fallback,
            "tool_calls": len(result.tool_executions),
            "error_code": result.error,
        },
    )
    return conversation, user_message, assistant_message
