"""Central support-agent orchestrator.

The orchestrator is the only place that:

* builds the bounded conversation context;
* resolves customer intent to approved capabilities;
* executes preflight capabilities such as an order lookup or RAG search;
* runs the bounded model -> validate -> execute -> tool-result loop;
* converts provider failures into controlled results.

HTTP routes and persistence stay in the service layer. Models never execute
backend code: every tool request is checked against the route's allow-list and
the registry's allow-list before the backend function runs.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.ai.context import ConversationContext, build_conversation_context
from app.ai.prompts import SYSTEM_PROMPT
from app.ai.providers.base import (
    ChatMessage,
    LLMProvider,
    LLMResponse,
    ProviderError,
    ToolCall,
)
from app.ai.routing import (
    Capability,
    CapabilityRoute,
    Intent,
    resolve_route,
)
from app.core.logging import operation_context
from app.knowledge.grounding import build_context_prompt
from app.knowledge.retrieval import KnowledgeRetriever, RetrievedChunk
from app.models import Message
from app.tools.base import ToolContext, ToolOutcome
from app.tools.knowledge_tools import KNOWLEDGE_SEARCH_TOOL_NAME
from app.tools.order_tools import ORDER_DETAILS_TOOL_NAME
from app.tools.registry import (
    ToolRegistry,
    audit_tool_call,
    build_default_registry,
)

logger = logging.getLogger(__name__)

MAX_HISTORY_MESSAGES = 40
MAX_HISTORY_CHARS = 12000
MAX_TOOL_ROUNDS = 3
MAX_TOOL_CALLS_PER_TURN = 6
MAX_TOOL_CALLS_PER_ROUND = 4

FALLBACK_ASSISTANT_MESSAGE = (
    "I'm sorry, I can't generate a reply right now. "
    "Please try again in a moment."
)
TOOL_LIMIT_ASSISTANT_MESSAGE = (
    "I couldn't finish checking that information right now. "
    "Please try again in a moment."
)
ORDER_LOOKUP_NOT_FOUND_REPLY = (
    "I couldn't retrieve that order's details, so I can't confirm its status "
    "or delivery estimate. Please check the order number and try again."
)
ORDER_LOOKUP_UNAVAILABLE_REPLY = (
    "I couldn't check that order right now, so I can't confirm its status or "
    "delivery estimate. Please try again in a moment."
)

DUPLICATE_TOOL_MESSAGE = (
    "That tool call already ran in this turn. Use the earlier result instead "
    "of repeating the lookup."
)
TOOL_CALL_LIMIT_MESSAGE = (
    "The tool-call limit for this turn was reached. Answer with the information "
    "already available and do not request more tools."
)

ORDER_RESULT_HEADER = (
    "A trusted backend order lookup already ran for the signed-in customer. "
    "Use only the facts in this result when discussing the order. Do not claim "
    "any status, shipping state, delivery estimate, total, or item that is not "
    "present here."
)
ORDER_FAILURE_HEADER = (
    "The trusted backend order lookup did not succeed. The application does not "
    "have order details for this request. Do not claim that the order was found, "
    "describe its status, or promise a delivery date. Tell the customer the "
    "lookup failed and ask them to check the order number or try again."
)
KNOWLEDGE_EMPTY_PROMPT = (
    "The controlled knowledge-base search returned no matching reference "
    "material. Do not invent or infer a Resolvix policy, fee, timeline, or "
    "procedure. Say that you do not have that information and offer the next "
    "useful step."
)
KNOWLEDGE_FAILURE_PROMPT = (
    "The controlled knowledge-base search could not complete. Do not invent or "
    "infer a Resolvix policy, fee, timeline, or procedure. Apologize, say you "
    "cannot confirm it right now, and offer the next useful step."
)

_SUPPORTED_SOURCES = {"faq", "document"}
_ORDER_SUCCESS_CLAIM = re.compile(
    r"\b(?:your|the)\s+order\b.{0,160}\b(?:is|was|has\s+been|will\s+be|"
    r"should\s+be|arriv(?:e|es|ing)|ships?|shipped|deliver(?:s|ed)?)\b"
    r".{0,160}\b(?:processing|confirmed|packed|shipped|in\s+transit|"
    r"out\s+for\s+delivery|delivered|arriving|on\s+its\s+way|cancelled|"
    r"canceled|delayed)\b",
    re.IGNORECASE,
)
_ORDER_ARRIVAL_CLAIM = re.compile(
    r"\b(?:your|the)\s+order\b.{0,160}\b(?:arrives?|will\s+arrive|"
    r"be\s+delivered|get\s+here)\b",
    re.IGNORECASE,
)
_NEGATION = re.compile(
    r"\b(?:can'?t|cannot|couldn'?t|unable|not\s+able|don'?t|do\s+not|"
    r"didn'?t|wasn'?t|isn'?t)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class ToolExecution:
    """One preflight or model-requested tool attempt."""

    call: ToolCall
    outcome: ToolOutcome
    preflight: bool = False
    duplicate: bool = False
    executed: bool = True


@dataclass(frozen=True, slots=True)
class AgentResult:
    """A provider-ready reply plus persistence/audit metadata."""

    content: str
    source: Literal["llm", "fallback", "tool_limit", "clarification", "guarded"]
    intent: Intent
    capabilities: tuple[Capability, ...]
    provider: str
    model: str
    tool_executions: tuple[ToolExecution, ...] = ()
    tool_rounds: int = 0
    retrieved: tuple[RetrievedChunk, ...] = ()
    finish_reason: str | None = None
    usage: dict[str, int] | None = None
    error: str | None = None
    clarification_reason: str | None = None
    history_message_count: int = 0
    history_truncated: bool = False
    fallback: bool = False
    guard_applied: bool = False

    @property
    def grounded(self) -> bool:
        return bool(self.retrieved)

    @property
    def tool_audit(self) -> list[dict[str, Any]]:
        return [
            audit_tool_call(execution.call, execution.outcome)
            for execution in self.tool_executions
        ]


@dataclass
class _ToolLoopState:
    executions: list[ToolExecution] = field(default_factory=list)
    rounds: int = 0
    limit_reason: str | None = None


class _ToolBudget:
    """Hard cap on tool attempts and duplicate executions per turn."""

    def __init__(self, max_calls: int) -> None:
        self.max_calls = max_calls
        self.attempts = 0
        self.signatures: set[str] = set()

    @staticmethod
    def signature(call: ToolCall) -> str:
        encoded = json.dumps(
            call.arguments,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return f"{call.name}:{encoded}"


def _safe_order_payload(data: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "order_number",
        "status",
        "shipping_status",
        "estimated_delivery",
        "order_date",
        "total_amount",
    )
    payload = {key: data[key] for key in fields if key in data}
    items = data.get("items")
    if isinstance(items, list):
        payload["items"] = items[:50]
    return payload


def _order_result_prompt(order_number: str, data: dict[str, Any] | None) -> str:
    serialized = json.dumps(
        _safe_order_payload(data or {}),
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )
    return (
        f"{ORDER_RESULT_HEADER}\n"
        f"<order_result>{serialized}</order_result>"
    )


def _order_failure_prompt(order_number: str, code: str | None) -> str:
    return (
        f"{ORDER_FAILURE_HEADER}\n"
        f"<order_lookup_failed order_number=\"{order_number}\" "
        f"error=\"{code or 'unknown_error'}\" />"
    )


def _retrieved_from_knowledge(
    outcome: ToolOutcome,
) -> list[RetrievedChunk]:
    if not outcome.ok or not isinstance(outcome.data, dict):
        return []
    results = outcome.data.get("results")
    if not isinstance(results, list):
        return []

    chunks: list[RetrievedChunk] = []
    for result in results:
        if not isinstance(result, dict):
            continue
        source_type = result.get("source_type")
        if source_type not in _SUPPORTED_SOURCES:
            continue
        try:
            source_id = UUID(str(result["source_id"]))
            chunk_index = int(result["chunk_index"])
            distance = float(result["distance"])
        except (KeyError, TypeError, ValueError):
            continue
        title = result.get("title")
        category = result.get("category")
        content = result.get("content")
        if not all(
            isinstance(value, str) and value.strip()
            for value in (title, category, content)
        ):
            continue
        chunks.append(
            RetrievedChunk(
                source_type=source_type,
                source_id=source_id,
                title=title,
                category=category,
                chunk_index=chunk_index,
                content=content,
                distance=max(0.0, min(2.0, distance)),
            )
        )
    return chunks


def _claims_unsupported_order_success(content: str) -> bool:
    """Detect a positive order claim after a failed backend lookup."""
    if _NEGATION.search(content):
        return False
    return bool(
        _ORDER_SUCCESS_CLAIM.search(content)
        or _ORDER_ARRIVAL_CLAIM.search(content)
    )


class SupportAgentOrchestrator:
    """Coordinate one context-aware customer-support turn."""

    def __init__(
        self,
        provider: LLMProvider,
        retriever: KnowledgeRetriever,
        *,
        registry: ToolRegistry | None = None,
        max_history_messages: int = MAX_HISTORY_MESSAGES,
        max_history_chars: int = MAX_HISTORY_CHARS,
        max_tool_rounds: int = MAX_TOOL_ROUNDS,
        max_tool_calls: int = MAX_TOOL_CALLS_PER_TURN,
        max_tool_calls_per_round: int = MAX_TOOL_CALLS_PER_ROUND,
    ) -> None:
        if max_tool_rounds < 1:
            raise ValueError("max_tool_rounds must be positive")
        if max_tool_calls < 1:
            raise ValueError("max_tool_calls must be positive")
        if max_tool_calls_per_round < 1:
            raise ValueError("max_tool_calls_per_round must be positive")
        self.provider = provider
        self.retriever = retriever
        self.registry = registry or build_default_registry(retriever)
        self.max_history_messages = max_history_messages
        self.max_history_chars = max_history_chars
        self.max_tool_rounds = max_tool_rounds
        self.max_tool_calls = max_tool_calls
        self.max_tool_calls_per_round = max_tool_calls_per_round

    async def respond(
        self,
        *,
        session: Session,
        user_id: UUID,
        conversation_id: UUID,
        content: str,
        previous_messages: Sequence[Message],
    ) -> AgentResult:
        """Run one turn under a dedicated operation id.

        Every provider, tool, retrieval, and persistence log emitted inside
        this call carries the same ``operation_id``, which is separate from the
        HTTP request id.
        """
        started = time.perf_counter()
        with operation_context() as operation_id:
            try:
                result = await self._respond(
                    session=session,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    content=content,
                    previous_messages=previous_messages,
                )
            except Exception as error:
                logger.exception(
                    "Agent turn failed",
                    extra={
                        "event": "agent_error",
                        "operation": "agent_turn",
                        "conversation_id": str(conversation_id),
                        "error_type": type(error).__name__,
                        "duration_ms": round(
                            (time.perf_counter() - started) * 1000,
                            2,
                        ),
                    },
                )
                raise

            logger.info(
                "Agent turn completed",
                extra={
                    "event": "agent_turn",
                    "operation": "agent_turn",
                    "operation_ref": operation_id,
                    "conversation_id": str(conversation_id),
                    "intent": result.intent.value,
                    "capabilities": [
                        capability.value
                        for capability in result.capabilities
                    ],
                    "source": result.source,
                    "provider": result.provider,
                    "model": result.model,
                    "fallback": result.fallback,
                    "error_code": result.error,
                    "tool_attempts": len(result.tool_executions),
                    "retrieved_count": len(result.retrieved),
                    "history_messages": result.history_message_count,
                    "history_truncated": result.history_truncated,
                    "duration_ms": round(
                        (time.perf_counter() - started) * 1000,
                        2,
                    ),
                },
            )
            return result

    async def _respond(
        self,
        *,
        session: Session,
        user_id: UUID,
        conversation_id: UUID,
        content: str,
        previous_messages: Sequence[Message],
    ) -> AgentResult:
        """Run one context-aware support turn and return safe audit metadata."""
        context = build_conversation_context(
            previous_messages,
            max_history_messages=self.max_history_messages,
            max_history_chars=self.max_history_chars,
        )
        route = resolve_route(
            content,
            previous_order_number=context.last_order_number,
            previous_intent=context.last_intent,
            previous_user_message=context.last_user_message,
        )

        if route.requires_clarification:
            return AgentResult(
                content=route.clarification_message or "",
                source="clarification",
                intent=route.intent,
                capabilities=route.capabilities,
                provider=self.provider.name,
                model=self.provider.model,
                clarification_reason=route.clarification_reason,
                history_message_count=context.history_message_count,
                history_truncated=context.history_truncated,
            )

        route_registry = self.registry.subset(route.allowed_tool_names)
        tool_context = ToolContext(
            session=session,
            user_id=user_id,
            conversation_id=conversation_id,
        )
        budget = _ToolBudget(self.max_tool_calls)
        state = _ToolLoopState()

        system_notes: list[str] = []
        retrieved: list[RetrievedChunk] = []

        if (
            Capability.ORDER_LOOKUP in route.capabilities
            and route.order_number is not None
        ):
            call = ToolCall(
                id=f"preflight_order_{uuid4().hex[:16]}",
                name=ORDER_DETAILS_TOOL_NAME,
                arguments={"order_number": route.order_number},
            )
            execution = await self._execute_tool(
                call,
                registry=route_registry,
                context=tool_context,
                budget=budget,
                preflight=True,
            )
            state.executions.append(execution)
            if execution.outcome.ok:
                system_notes.append(
                    _order_result_prompt(
                        route.order_number,
                        execution.outcome.data,
                    )
                )
            else:
                system_notes.append(
                    _order_failure_prompt(
                        route.order_number,
                        execution.outcome.error_code,
                    )
                )

        if Capability.KNOWLEDGE_SEARCH in route.capabilities:
            call = ToolCall(
                id=f"preflight_knowledge_{uuid4().hex[:16]}",
                name=KNOWLEDGE_SEARCH_TOOL_NAME,
                arguments={"query": route.knowledge_query or content},
            )
            execution = await self._execute_tool(
                call,
                registry=route_registry,
                context=tool_context,
                budget=budget,
                preflight=True,
            )
            state.executions.append(execution)
            retrieved = _retrieved_from_knowledge(execution.outcome)
            if not execution.outcome.ok:
                system_notes.append(KNOWLEDGE_FAILURE_PROMPT)
            elif not retrieved:
                system_notes.append(KNOWLEDGE_EMPTY_PROMPT)

        llm_messages: list[ChatMessage] = [
            ChatMessage(role="system", content=SYSTEM_PROMPT)
        ]
        if system_notes:
            llm_messages.append(
                ChatMessage(role="system", content="\n\n".join(system_notes))
            )
        if retrieved:
            llm_messages.append(
                ChatMessage(
                    role="system",
                    content=build_context_prompt(retrieved),
                )
            )
        llm_messages.extend(context.history)
        llm_messages.append(ChatMessage(role="user", content=content))

        response: LLMResponse | None = None
        provider_name = self.provider.name
        model_name = self.provider.model
        try:
            response = await self._generate_with_tools(
                llm_messages,
                registry=route_registry,
                context=tool_context,
                budget=budget,
                state=state,
            )
        except ProviderError as error:
            logger.warning(
                "LLM provider failed; returning a controlled fallback",
                extra={
                    "event": "agent_fallback",
                    "operation": "agent_turn",
                    "provider": provider_name,
                    "model": model_name,
                    "conversation_id": str(conversation_id),
                    "error_code": error.code,
                },
            )
            return self._failure_result(
                route=route,
                content=FALLBACK_ASSISTANT_MESSAGE,
                source="fallback",
                error=error.code,
                state=state,
                retrieved=retrieved,
                context=context,
                provider=provider_name,
                model=model_name,
            )
        except Exception as error:
            logger.exception(
                "Unexpected LLM provider failure; returning a controlled fallback",
                extra={
                    "event": "agent_fallback",
                    "operation": "agent_turn",
                    "provider": provider_name,
                    "model": model_name,
                    "conversation_id": str(conversation_id),
                    "error_type": type(error).__name__,
                    "error_code": "unexpected_error",
                },
            )
            return self._failure_result(
                route=route,
                content=FALLBACK_ASSISTANT_MESSAGE,
                source="fallback",
                error="unexpected_error",
                state=state,
                retrieved=retrieved,
                context=context,
                provider=provider_name,
                model=model_name,
            )

        if response is None:
            return self._failure_result(
                route=route,
                content=TOOL_LIMIT_ASSISTANT_MESSAGE,
                source="tool_limit",
                error=state.limit_reason or "tool_limit",
                state=state,
                retrieved=retrieved,
                context=context,
                provider=provider_name,
                model=model_name,
            )

        provider_name = response.provider or provider_name
        model_name = response.model or model_name
        content_out = response.content
        source: Literal["llm", "guarded"] = "llm"
        guard_applied = False

        if route.intent in {Intent.ORDER_STATUS, Intent.ORDER_ITEMS}:
            order_executions = [
                execution
                for execution in state.executions
                if execution.call.name == ORDER_DETAILS_TOOL_NAME
            ]
            order_succeeded = any(
                execution.outcome.ok for execution in order_executions
            )
            if (
                order_executions
                and not order_succeeded
                and _claims_unsupported_order_success(content_out)
            ):
                unavailable = any(
                    execution.outcome.error_code
                    in {"database_error", "tool_failed"}
                    for execution in order_executions
                )
                content_out = (
                    ORDER_LOOKUP_UNAVAILABLE_REPLY
                    if unavailable
                    else ORDER_LOOKUP_NOT_FOUND_REPLY
                )
                source = "guarded"
                guard_applied = True

        return AgentResult(
            content=content_out,
            source=source,
            intent=route.intent,
            capabilities=route.capabilities,
            provider=provider_name,
            model=model_name,
            tool_executions=tuple(state.executions),
            tool_rounds=state.rounds,
            retrieved=tuple(retrieved),
            finish_reason=response.finish_reason,
            usage=response.usage,
            history_message_count=context.history_message_count,
            history_truncated=context.history_truncated,
            guard_applied=guard_applied,
        )

    async def _execute_tool(
        self,
        call: ToolCall,
        *,
        registry: ToolRegistry,
        context: ToolContext,
        budget: _ToolBudget,
        preflight: bool = False,
    ) -> ToolExecution:
        signature = budget.signature(call)
        if signature in budget.signatures:
            logger.info(
                "Prevented duplicate tool execution",
                extra={
                    "event": "tool_attempt",
                    "operation": "tool_execution",
                    "tool": call.name,
                    "preflight": preflight,
                    "executed": False,
                    "duplicate": True,
                    "error_code": "duplicate_tool_call",
                },
            )
            return ToolExecution(
                call=call,
                outcome=ToolOutcome(
                    tool_name=call.name,
                    ok=False,
                    error_code="duplicate_tool_call",
                    error_message=DUPLICATE_TOOL_MESSAGE,
                ),
                preflight=preflight,
                duplicate=True,
                executed=False,
            )

        if budget.attempts >= budget.max_calls:
            logger.warning(
                "Tool-call limit reached while requesting a tool",
                extra={
                    "event": "tool_attempt",
                    "operation": "tool_execution",
                    "tool": call.name,
                    "preflight": preflight,
                    "executed": False,
                    "error_code": "tool_call_limit",
                },
            )
            return ToolExecution(
                call=call,
                outcome=ToolOutcome(
                    tool_name=call.name,
                    ok=False,
                    error_code="tool_call_limit",
                    error_message=TOOL_CALL_LIMIT_MESSAGE,
                ),
                preflight=preflight,
                executed=False,
            )

        budget.attempts += 1
        budget.signatures.add(signature)
        started = time.perf_counter()
        outcome = await registry.execute(call, context)
        logger.info(
            "Agent tool attempt finished",
            extra={
                "event": "tool_attempt",
                "operation": "tool_execution",
                "tool": call.name,
                "preflight": preflight,
                "executed": True,
                "duplicate": False,
                "ok": outcome.ok,
                "error_code": outcome.error_code,
                "duration_ms": round(
                    (time.perf_counter() - started) * 1000,
                    2,
                ),
            },
        )
        return ToolExecution(
            call=call,
            outcome=outcome,
            preflight=preflight,
            executed=True,
        )

    async def _generate_with_tools(
        self,
        messages: list[ChatMessage],
        *,
        registry: ToolRegistry,
        context: ToolContext,
        budget: _ToolBudget,
        state: _ToolLoopState,
    ) -> LLMResponse | None:
        """Run the bounded model/tool loop and mutate *state* for auditing."""
        definitions = registry.definitions

        for round_index in range(self.max_tool_rounds + 1):
            started = time.perf_counter()
            try:
                response = await self.provider.generate(
                    messages,
                    tools=definitions or None,
                )
            except ProviderError as error:
                logger.warning(
                    "LLM provider returned a controlled error",
                    extra={
                        "event": "provider_error",
                        "operation": "llm_invocation",
                        "provider": self.provider.name,
                        "model": self.provider.model,
                        "provider_round": round_index,
                        "error_code": error.code,
                        "duration_ms": round(
                            (time.perf_counter() - started) * 1000,
                            2,
                        ),
                    },
                )
                raise
            except Exception as error:
                logger.exception(
                    "LLM provider failed unexpectedly",
                    extra={
                        "event": "provider_error",
                        "operation": "llm_invocation",
                        "provider": self.provider.name,
                        "model": self.provider.model,
                        "provider_round": round_index,
                        "error_type": type(error).__name__,
                        "duration_ms": round(
                            (time.perf_counter() - started) * 1000,
                            2,
                        ),
                    },
                )
                raise

            logger.info(
                "LLM provider call completed",
                extra={
                    "event": "provider_call",
                    "operation": "llm_invocation",
                    "provider": response.provider or self.provider.name,
                    "model": response.model or self.provider.model,
                    "provider_round": round_index,
                    "tool_call_count": len(response.tool_calls),
                    "finish_reason": response.finish_reason,
                    "duration_ms": round(
                        (time.perf_counter() - started) * 1000,
                        2,
                    ),
                },
            )
            if not response.tool_calls:
                return response

            if round_index >= self.max_tool_rounds:
                state.limit_reason = "tool_round_limit"
                return None

            messages.append(
                ChatMessage(
                    role="assistant",
                    content=response.content,
                    tool_calls=response.tool_calls,
                )
            )

            for index, call in enumerate(response.tool_calls):
                if index >= self.max_tool_calls_per_round:
                    execution = ToolExecution(
                        call=call,
                        outcome=ToolOutcome(
                            tool_name=call.name,
                            ok=False,
                            error_code="tool_call_limit",
                            error_message=TOOL_CALL_LIMIT_MESSAGE,
                        ),
                        executed=False,
                    )
                    state.limit_reason = "tool_call_limit"
                else:
                    execution = await self._execute_tool(
                        call,
                        registry=registry,
                        context=context,
                        budget=budget,
                    )
                    if (
                        not execution.executed
                        and execution.outcome.error_code == "tool_call_limit"
                    ):
                        state.limit_reason = "tool_call_limit"

                state.executions.append(execution)
                messages.append(
                    ChatMessage(
                        role="tool",
                        content=execution.outcome.to_json(),
                        tool_call_id=call.id,
                        tool_name=call.name,
                    )
                )

            state.rounds += 1
            if state.limit_reason:
                return None

        state.limit_reason = "tool_round_limit"
        return None

    @staticmethod
    def _failure_result(
        *,
        route: CapabilityRoute,
        content: str,
        source: Literal["fallback", "tool_limit"],
        error: str,
        state: _ToolLoopState,
        retrieved: Sequence[RetrievedChunk],
        context: ConversationContext,
        provider: str,
        model: str,
    ) -> AgentResult:
        return AgentResult(
            content=content,
            source=source,
            intent=route.intent,
            capabilities=route.capabilities,
            provider=provider,
            model=model,
            tool_executions=tuple(state.executions),
            tool_rounds=state.rounds,
            retrieved=tuple(retrieved),
            error=error,
            history_message_count=context.history_message_count,
            history_truncated=context.history_truncated,
            fallback=True,
        )


__all__ = [
    "AgentResult",
    "FALLBACK_ASSISTANT_MESSAGE",
    "MAX_HISTORY_CHARS",
    "MAX_HISTORY_MESSAGES",
    "MAX_TOOL_CALLS_PER_ROUND",
    "MAX_TOOL_CALLS_PER_TURN",
    "MAX_TOOL_ROUNDS",
    "ORDER_LOOKUP_NOT_FOUND_REPLY",
    "ORDER_LOOKUP_UNAVAILABLE_REPLY",
    "SupportAgentOrchestrator",
    "TOOL_LIMIT_ASSISTANT_MESSAGE",
    "ToolExecution",
]
