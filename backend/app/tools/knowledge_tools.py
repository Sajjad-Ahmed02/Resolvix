"""Controlled knowledge-base retrieval capability for the support agent."""

from __future__ import annotations

import logging
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
)
from sqlalchemy.orm import Session

from app.ai.providers.base import ToolDefinition
from app.knowledge.retrieval import KnowledgeRetriever
from app.tools.base import (
    Tool,
    ToolArgumentError,
    ToolContext,
    ToolOutcome,
)

logger = logging.getLogger(__name__)

KNOWLEDGE_SEARCH_TOOL_NAME = "search_knowledge_base"

INVALID_ARGUMENTS_MESSAGE = (
    "The knowledge search query is missing or invalid. Ask a focused policy "
    "or FAQ question and try again."
)
KNOWLEDGE_UNAVAILABLE_MESSAGE = (
    "Knowledge search is temporarily unavailable. Do not invent or infer a "
    "Resolvix policy; tell the customer you cannot confirm it right now and "
    "offer the next useful step."
)


class KnowledgeSearchArguments(BaseModel):
    """Arguments accepted from the model for knowledge retrieval."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    query: str = Field(
        min_length=2,
        max_length=1000,
        description=(
            "A focused customer-support question or search phrase, for "
            "example 'return window for opened items' or 'payment methods'."
        ),
    )

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("Knowledge search query must not be blank")
        return normalized


class KnowledgeSearchTool(Tool):
    """Search active FAQ/policy chunks and return traceable citations."""

    definition = ToolDefinition(
        name=KNOWLEDGE_SEARCH_TOOL_NAME,
        description=(
            "Search the Resolvix knowledge base for return, refund, shipping, "
            "payment, warranty, and other store policies or FAQs. Use this "
            "when a policy or FAQ answer is needed and the reference material "
            "is not already present in the conversation. Answer from the "
            "returned passages only."
        ),
        parameters=KnowledgeSearchArguments.model_json_schema(),
    )

    def __init__(self, retriever: KnowledgeRetriever) -> None:
        self.retriever = retriever

    async def execute(
        self,
        context: ToolContext,
        arguments: dict[str, Any],
    ) -> ToolOutcome:
        try:
            parsed = KnowledgeSearchArguments.model_validate(arguments)
        except ValidationError as error:
            logger.info(
                "Rejected knowledge search arguments: %s",
                error.error_count(),
            )
            raise ToolArgumentError(INVALID_ARGUMENTS_MESSAGE) from error

        try:
            chunks = await self.retriever.retrieve(
                context.session,
                parsed.query,
            )
        except Exception:
            logger.exception("Knowledge search failed")
            self._rollback_safely(context.session)
            return ToolOutcome(
                tool_name=KNOWLEDGE_SEARCH_TOOL_NAME,
                ok=False,
                error_code="knowledge_unavailable",
                error_message=KNOWLEDGE_UNAVAILABLE_MESSAGE,
            )

        results = [
            {
                "source_type": chunk.source_type,
                "source_id": str(chunk.source_id),
                "title": chunk.title,
                "category": chunk.category,
                "chunk_index": chunk.chunk_index,
                "content": chunk.content,
                "distance": round(chunk.distance, 6),
                "similarity": round(chunk.similarity, 6),
            }
            for chunk in chunks
        ]
        return ToolOutcome(
            tool_name=KNOWLEDGE_SEARCH_TOOL_NAME,
            ok=True,
            data={
                "query": parsed.query,
                "result_count": len(results),
                "results": results,
            },
        )

    @staticmethod
    def _rollback_safely(session: Session) -> None:
        try:
            session.rollback()
        except Exception:  # pragma: no cover - defensive cleanup
            logger.exception("Failed to roll back after knowledge search")


__all__ = [
    "KNOWLEDGE_SEARCH_TOOL_NAME",
    "KnowledgeSearchArguments",
    "KnowledgeSearchTool",
]
