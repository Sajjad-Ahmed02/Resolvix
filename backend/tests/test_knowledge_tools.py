from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any
from uuid import UUID

import pytest

from app.ai.providers.base import ToolCall
from app.knowledge.retrieval import RetrievedChunk
from app.tools.base import ToolContext
from app.tools.knowledge_tools import (
    KNOWLEDGE_SEARCH_TOOL_NAME,
    KnowledgeSearchTool,
)
from app.tools.order_tools import ORDER_DETAILS_TOOL_NAME
from app.tools.registry import ToolRegistry, build_default_registry


class StubRetriever:
    def __init__(self, chunks: list[RetrievedChunk] | None = None) -> None:
        self.chunks = chunks or []
        self.error: Exception | None = None
        self.queries: list[str] = []

    async def retrieve(
        self,
        session: Any,
        query: str,
        *,
        top_k: int | None = None,
    ) -> list[RetrievedChunk]:
        self.queries.append(query)
        if self.error is not None:
            raise self.error
        return list(self.chunks)


def _chunk(
    *,
    title: str = "What is your return window?",
    category: str = "Returns",
    content: str = "Unused products can be returned within 30 days.",
    source_id: UUID | None = None,
    distance: float = 0.125,
) -> RetrievedChunk:
    return RetrievedChunk(
        source_type="faq",
        source_id=source_id or uuid.uuid4(),
        title=title,
        category=category,
        chunk_index=0,
        content=content,
        distance=distance,
    )


def _context() -> ToolContext:
    return ToolContext(session=object(), user_id=uuid.uuid4())


def _call(arguments: dict, *, name: str = KNOWLEDGE_SEARCH_TOOL_NAME) -> ToolCall:
    return ToolCall(id="call_knowledge", name=name, arguments=arguments)


def _execute(registry: ToolRegistry, call: ToolCall):
    return asyncio.run(registry.execute(call, _context()))


def test_default_registry_adds_knowledge_only_with_a_retriever() -> None:
    retriever = StubRetriever()

    order_only = build_default_registry()
    full = build_default_registry(retriever)

    assert [definition.name for definition in order_only.definitions] == [
        ORDER_DETAILS_TOOL_NAME
    ]
    assert [definition.name for definition in full.definitions] == [
        ORDER_DETAILS_TOOL_NAME,
        KNOWLEDGE_SEARCH_TOOL_NAME,
    ]
    assert [
        definition.name
        for definition in full.subset([KNOWLEDGE_SEARCH_TOOL_NAME]).definitions
    ] == [KNOWLEDGE_SEARCH_TOOL_NAME]
    assert full.subset(["execute_sql"]).definitions == []


def test_knowledge_tool_returns_traceable_citations() -> None:
    retriever = StubRetriever(
        [
            _chunk(
                title="What is your return window?",
                category="Returns",
                content="Unused products can be returned within 30 days.",
                distance=0.125,
            )
        ]
    )
    registry = build_default_registry(retriever)

    outcome = _execute(
        registry,
        _call({"query": "  return    window  "}),
    )

    assert retriever.queries == ["return window"]
    assert outcome.ok is True
    assert outcome.data is not None
    assert outcome.data["query"] == "return window"
    assert outcome.data["result_count"] == 1
    result = outcome.data["results"][0]
    assert result["source_type"] == "faq"
    assert result["title"] == "What is your return window?"
    assert result["category"] == "Returns"
    assert result["content"] == "Unused products can be returned within 30 days."
    assert result["distance"] == 0.125
    assert result["similarity"] == pytest.approx(0.875)
    assert str(retriever.chunks[0].source_id) == result["source_id"]


def test_knowledge_tool_definition_is_a_scoped_query_schema() -> None:
    definition = KnowledgeSearchTool.definition

    assert definition.name == KNOWLEDGE_SEARCH_TOOL_NAME
    assert definition.parameters["type"] == "object"
    assert definition.parameters["required"] == ["query"]
    assert definition.parameters["additionalProperties"] is False
    assert set(definition.parameters["properties"]) == {"query"}


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"query": ""},
        {"query": "  "},
        {"query": "a"},
        {"query": "return policy", "source_type": "document"},
    ],
)
def test_knowledge_tool_rejects_invalid_arguments(arguments: dict) -> None:
    outcome = _execute(
        build_default_registry(StubRetriever()),
        _call(arguments),
    )

    assert outcome.ok is False
    assert outcome.error_code == "invalid_arguments"
    assert outcome.data is None


def test_knowledge_tool_failure_is_controlled_and_sanitized() -> None:
    retriever = StubRetriever()
    retriever.error = RuntimeError("vector database password=super-secret")
    registry = build_default_registry(retriever)

    outcome = _execute(
        registry,
        _call({"query": "return policy"}),
    )

    assert outcome.ok is False
    assert outcome.error_code == "knowledge_unavailable"
    assert outcome.data is None
    assert outcome.error_message is not None
    assert "super-secret" not in outcome.error_message
    payload = json.loads(outcome.to_json())
    assert payload["ok"] is False
    assert payload["error"]["code"] == "knowledge_unavailable"
    assert "super-secret" not in outcome.to_json()


def test_knowledge_tool_is_not_available_without_a_retriever() -> None:
    outcome = _execute(
        build_default_registry(),
        _call({"query": "return policy"}),
    )

    assert outcome.ok is False
    assert outcome.error_code == "unknown_tool"
