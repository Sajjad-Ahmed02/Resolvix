from __future__ import annotations

import asyncio
import json
import logging
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app.ai.orchestrator import SupportAgentOrchestrator
from app.ai.providers.base import ChatMessage, LLMProvider, LLMResponse, ToolCall
from app.core.logging import (
    JsonFormatter,
    RequestContextFilter,
    get_operation_id,
    get_request_id,
    operation_context,
    set_request_id,
)
from app.knowledge.ingestion import KnowledgeIngestor
from app.knowledge.retrieval import KnowledgeRetriever
from app.main import app
from app.models import FAQ
from app.tools.base import ToolContext
from app.tools.registry import ToolRegistry


class _Embedder:
    model_name = "observability-test-embedder"
    dimension = 384
    max_seq_length = 256

    def reusable_token_limit(self) -> int:
        return 254

    async def embed_documents(self, texts):
        return [[0.5] * 384 for _ in texts]

    async def embed_query(self, text: str):
        return [0.5] * 384

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def encode_tokens(self, text: str):
        return text.split()

    def decode_tokens(self, tokens):
        return " ".join(tokens)


class _Retriever:
    async def retrieve(self, session, query, *, top_k=None):
        return []


class _Provider(LLMProvider):
    name = "observability-test-provider"
    model = "observability-test-model"

    async def generate(self, messages, *, tools=None):
        return LLMResponse(
            content="Here is the policy guidance you asked for.",
            provider=self.name,
            model=self.model,
            finish_reason="stop",
            usage={"input_tokens": 4, "output_tokens": 6},
        )

    async def aclose(self) -> None:
        pass


class _DummySession:
    def rollback(self) -> None:
        pass


def _record_with_context(
    message: str,
    *,
    event: str,
    **fields,
) -> logging.LogRecord:
    record = logging.LogRecord(
        name="resolvix.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )
    record.event = event
    for key, value in fields.items():
        setattr(record, key, value)
    RequestContextFilter().filter(record)
    return record


def test_request_ids_are_generated_unique_and_returned(client: TestClient) -> None:
    first = client.get("/")
    second = client.get("/")

    assert first.status_code == 200
    assert len(first.headers["X-Request-ID"]) == 32
    assert len(second.headers["X-Request-ID"]) == 32
    assert first.headers["X-Request-ID"] != second.headers["X-Request-ID"]
    assert get_request_id() == "-"


def test_a_safe_caller_request_id_is_preserved(client: TestClient) -> None:
    response = client.get(
        "/health",
        headers={"X-Request-ID": "gateway:request-42.abc"},
    )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "gateway:request-42.abc"


def test_an_unsafe_request_id_is_replaced(client: TestClient) -> None:
    unsafe = "x" * 200
    response = client.get("/", headers={"X-Request-ID": unsafe})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] != unsafe
    assert len(response.headers["X-Request-ID"]) == 32


def test_unhandled_errors_return_a_safe_request_correlated_body(
    monkeypatch,
) -> None:
    def explode() -> bool:
        raise RuntimeError("internal password=super-secret")

    monkeypatch.setattr(
        "app.api.routes.health.check_database_connection",
        explode,
    )

    with TestClient(app, raise_server_exceptions=False) as test_client:
        response = test_client.get("/health")

    body = response.json()
    assert response.status_code == 500
    assert body["detail"] == "An unexpected error occurred."
    assert body["request_id"] == response.headers["X-Request-ID"]
    assert "RuntimeError" not in response.text
    assert "super-secret" not in response.text
    assert "Traceback" not in response.text


def test_database_errors_return_a_retryable_sanitized_response(
    monkeypatch,
) -> None:
    def explode() -> bool:
        raise SQLAlchemyError(
            "postgresql+psycopg://resolvix:super-secret@db:5432/resolvix"
        )

    monkeypatch.setattr(
        "app.api.routes.health.check_database_connection",
        explode,
    )

    with TestClient(app, raise_server_exceptions=False) as test_client:
        response = test_client.get("/health")

    body = response.json()
    assert response.status_code == 503
    assert body["detail"] == (
        "A data service is temporarily unavailable. Please try again."
    )
    assert body["request_id"] == response.headers["X-Request-ID"]
    assert "postgresql" not in response.text
    assert "super-secret" not in response.text


def test_json_formatter_emits_correlation_and_structured_fields() -> None:
    token = set_request_id("request-123")
    try:
        with operation_context("op-abc"):
            record = _record_with_context(
                "Tool execution completed",
                event="tool_execution",
                tool="get_order_details",
                duration_ms=12.5,
                ok=True,
            )
            payload = json.loads(JsonFormatter().format(record))
    finally:
        from app.core.logging import reset_request_id

        reset_request_id(token)

    assert payload["event"] == "tool_execution"
    assert payload["request_id"] == "request-123"
    assert payload["operation_id"] == "op-abc"
    assert payload["tool"] == "get_order_details"
    assert payload["duration_ms"] == 12.5
    assert payload["ok"] is True
    assert payload["level"] == "INFO"
    assert payload["timestamp"].endswith("Z")


def test_operation_context_is_task_local_and_resets() -> None:
    assert get_operation_id() == "-"
    with operation_context() as operation_id:
        assert operation_id.startswith("op_")
        assert get_operation_id() == operation_id
    assert get_operation_id() == "-"


def test_retrieval_logs_counts_without_query_text(monkeypatch, caplog) -> None:
    monkeypatch.setattr(
        "app.repositories.knowledge.search_chunks",
        lambda *args, **kwargs: [],
    )
    retriever = KnowledgeRetriever(_Embedder(), top_k=4, max_distance=0.7)

    with caplog.at_level(
        logging.INFO,
        logger="app.knowledge.retrieval",
    ):
        results = asyncio.run(
            retriever.retrieve(None, "where is my private order?")
        )

    assert results == []
    record = next(
        item
        for item in caplog.records
        if getattr(item, "event", None) == "retrieval_completed"
    )
    assert record.result_count == 0
    assert record.top_k == 4
    assert record.query_chars == len("where is my private order?")
    assert "where is my private order" not in record.getMessage()
    assert not hasattr(record, "query")


def test_registry_logs_unknown_tool_rejection_without_execution(caplog) -> None:
    registry = ToolRegistry([])
    context = ToolContext(session=None, user_id=uuid.uuid4())

    with caplog.at_level(logging.INFO, logger="app.tools.registry"):
        outcome = asyncio.run(
            registry.execute(
                ToolCall(
                    id="call_1",
                    name="drop_all_tables",
                    arguments={"confirm": True},
                ),
                context,
            )
        )

    assert outcome.ok is False
    assert outcome.error_code == "unknown_tool"
    record = next(
        item
        for item in caplog.records
        if getattr(item, "event", None) == "tool_rejected"
    )
    assert record.tool == "drop_all_tables"
    assert record.error_code == "unknown_tool"


def test_ingestion_logs_embedding_failure_and_returns_a_controlled_result(
    monkeypatch,
    caplog,
) -> None:
    def explode(*args, **kwargs):
        raise RuntimeError("embedding backend unavailable")

    monkeypatch.setattr("app.knowledge.ingestion.chunk_faq", explode)
    ingestor = KnowledgeIngestor(
        _Embedder(),
        max_tokens=200,
        overlap_tokens=40,
    )
    faq = FAQ(
        id=uuid.uuid4(),
        question="Where is my order?",
        answer="Use the tracking page.",
        category="Observability test",
        is_active=True,
    )

    with caplog.at_level(logging.INFO, logger="app.knowledge.ingestion"):
        result = asyncio.run(ingestor.sync_faq(_DummySession(), faq))

    assert result.action == "failed"
    assert result.error is not None
    assert result.error.startswith("RuntimeError:")
    error_record = next(
        item
        for item in caplog.records
        if getattr(item, "event", None) == "knowledge_sync_error"
    )
    assert error_record.source_type == "faq"
    assert error_record.source_id == str(faq.id)
    assert error_record.error_type == "RuntimeError"
    result_record = next(
        item
        for item in caplog.records
        if getattr(item, "event", None) == "knowledge_sync"
        and getattr(item, "action", None) == "failed"
    )
    assert result_record.chunks == 0


def test_agent_turn_logs_request_provider_and_retrieval_boundaries(caplog) -> None:
    orchestrator = SupportAgentOrchestrator(_Provider(), _Retriever())

    with caplog.at_level(logging.INFO, logger="app.ai.orchestrator"):
        result = asyncio.run(
            orchestrator.respond(
                session=None,
                user_id=uuid.uuid4(),
                conversation_id=uuid.uuid4(),
                content="What is your return policy?",
                previous_messages=[],
            )
        )

    assert result.source == "llm"
    assert result.retrieved == ()
    turn = next(
        item
        for item in caplog.records
        if getattr(item, "event", None) == "agent_turn"
    )
    assert turn.operation == "agent_turn"
    assert turn.operation_ref
    assert turn.provider == "observability-test-provider"
    assert turn.intent == "return_refund_policy"
    assert turn.retrieved_count == 0
    assert turn.fallback is False
    assert any(
        getattr(item, "event", None) == "provider_call"
        for item in caplog.records
    )
