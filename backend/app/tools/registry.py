"""The allow-list of tools the support agent may execute.

The registry is intentionally separate from provider adapters and from the
conversation service. A model can only name a registered tool; the registry
rejects everything else before any backend code runs.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from typing import Any

from app.ai.providers.base import ToolCall, ToolDefinition
from app.knowledge.retrieval import KnowledgeRetriever
from app.tools.base import Tool, ToolArgumentError, ToolContext, ToolOutcome
from app.tools.knowledge_tools import KnowledgeSearchTool
from app.tools.order_tools import OrderDetailsTool

logger = logging.getLogger(__name__)

MAX_TOOL_ARGUMENT_BYTES = 4096

UNKNOWN_TOOL_MESSAGE = (
    "That tool is not available. Only registered support tools may be used."
)
INVALID_ARGUMENTS_MESSAGE = (
    "The tool arguments are invalid. Ask the customer for the required "
    "information and try again."
)
TOOL_FAILED_MESSAGE = (
    "The tool could not complete the request. Apologize and ask the customer "
    "to try again in a moment."
)


class ToolRegistry:
    """Resolve and execute only explicitly registered tools."""

    def __init__(self, tools: Iterable[Tool]) -> None:
        registered: dict[str, Tool] = {}
        for tool in tools:
            name = tool.definition.name
            if name in registered:
                raise ValueError(f"Duplicate tool registration: {name}")
            registered[name] = tool
        self._tools = registered

    @property
    def definitions(self) -> list[ToolDefinition]:
        """Return immutable-by-convention schemas for the model providers."""
        return [tool.definition for tool in self._tools.values()]

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def subset(self, names: Iterable[str]) -> "ToolRegistry":
        """Return a registry restricted to the route's approved tools.

        Missing names are ignored rather than creating placeholder tools. A
        model that requests a name outside the subset receives the normal
        unknown-tool result, so route-level allow-listing is enforced before
        execution.
        """
        return ToolRegistry(
            self._tools[name] for name in names if name in self._tools
        )

    async def execute(
        self,
        call: ToolCall,
        context: ToolContext,
    ) -> ToolOutcome:
        """Validate and execute one model-requested tool call."""
        tool = self._tools.get(call.name)
        if tool is None:
            logger.warning("Rejected unknown tool request: %r", call.name)
            return ToolOutcome(
                tool_name=call.name,
                ok=False,
                error_code="unknown_tool",
                error_message=UNKNOWN_TOOL_MESSAGE,
            )

        arguments = call.arguments
        if not isinstance(arguments, dict):
            return ToolOutcome(
                tool_name=call.name,
                ok=False,
                error_code="invalid_arguments",
                error_message=INVALID_ARGUMENTS_MESSAGE,
            )

        try:
            encoded = json.dumps(
                arguments,
                ensure_ascii=False,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        except (TypeError, ValueError):
            return ToolOutcome(
                tool_name=call.name,
                ok=False,
                error_code="invalid_arguments",
                error_message=INVALID_ARGUMENTS_MESSAGE,
            )
        if len(encoded) > MAX_TOOL_ARGUMENT_BYTES:
            logger.warning(
                "Rejected oversized arguments for tool %r (%s bytes)",
                call.name,
                len(encoded),
            )
            return ToolOutcome(
                tool_name=call.name,
                ok=False,
                error_code="invalid_arguments",
                error_message=INVALID_ARGUMENTS_MESSAGE,
            )

        try:
            outcome = await tool.execute(context, arguments)
        except ToolArgumentError as error:
            return ToolOutcome(
                tool_name=call.name,
                ok=False,
                error_code="invalid_arguments",
                error_message=error.safe_message,
            )
        except Exception:
            logger.exception("Unexpected failure in tool %r", call.name)
            try:
                context.session.rollback()
            except Exception:  # pragma: no cover - defensive cleanup
                logger.exception("Failed to roll back after tool failure")
            return ToolOutcome(
                tool_name=call.name,
                ok=False,
                error_code="tool_failed",
                error_message=TOOL_FAILED_MESSAGE,
            )

        if not isinstance(outcome, ToolOutcome) or (
            outcome.tool_name != call.name
        ):
            logger.error("Tool %r returned an invalid outcome", call.name)
            return ToolOutcome(
                tool_name=call.name,
                ok=False,
                error_code="tool_failed",
                error_message=TOOL_FAILED_MESSAGE,
            )
        return outcome


def build_default_registry(
    retriever: KnowledgeRetriever | None = None,
) -> ToolRegistry:
    """Build the production allow-list. Add new tools only here.

    The order tool is always available. The knowledge tool is included only
    when a retriever is supplied, which keeps low-level tool tests independent
    from the embedding stack while production chat receives both capabilities.
    """
    tools: list[Tool] = [OrderDetailsTool()]
    if retriever is not None:
        tools.append(KnowledgeSearchTool(retriever))
    return ToolRegistry(tools)


DEFAULT_TOOL_REGISTRY = build_default_registry()


def audit_tool_call(
    call: ToolCall,
    outcome: ToolOutcome,
) -> dict[str, Any]:
    """Build a compact, JSON-safe audit record for message metadata."""
    try:
        serialized = json.dumps(
            call.arguments,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )
    except (TypeError, ValueError):
        serialized = "{}"

    safe_arguments: dict[str, Any]
    if len(serialized) > 2000:
        safe_arguments = {"truncated": True}
    else:
        try:
            parsed = json.loads(serialized)
        except ValueError:
            parsed = {}
        safe_arguments = parsed if isinstance(parsed, dict) else {}

    entry: dict[str, Any] = {
        "name": call.name,
        "arguments": safe_arguments,
        "status": "ok" if outcome.ok else "error",
    }
    if not outcome.ok:
        entry["error"] = outcome.error_code
    return entry
