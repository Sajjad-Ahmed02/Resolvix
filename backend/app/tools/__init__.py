"""Allow-listed backend tools available to the support agent."""

from app.tools.base import (
    Tool,
    ToolArgumentError,
    ToolContext,
    ToolOutcome,
)
from app.tools.knowledge_tools import (
    KNOWLEDGE_SEARCH_TOOL_NAME,
    KnowledgeSearchArguments,
    KnowledgeSearchTool,
)
from app.tools.order_tools import (
    ORDER_DETAILS_TOOL_NAME,
    OrderDetailsTool,
    OrderLookupUnavailableError,
    OrderNotFoundError,
    get_order_details,
)
from app.tools.registry import (
    DEFAULT_TOOL_REGISTRY,
    ToolRegistry,
    build_default_registry,
)

__all__ = [
    "DEFAULT_TOOL_REGISTRY",
    "KNOWLEDGE_SEARCH_TOOL_NAME",
    "KnowledgeSearchArguments",
    "KnowledgeSearchTool",
    "ORDER_DETAILS_TOOL_NAME",
    "OrderDetailsTool",
    "OrderLookupUnavailableError",
    "OrderNotFoundError",
    "Tool",
    "ToolArgumentError",
    "ToolContext",
    "ToolOutcome",
    "ToolRegistry",
    "build_default_registry",
    "get_order_details",
]
