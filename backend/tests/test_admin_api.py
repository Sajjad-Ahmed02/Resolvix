from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.db.session import SessionLocal
from app.knowledge.dependencies import get_knowledge_ingestor
from app.knowledge.ingestion import KnowledgeIngestor
from app.main import app
from app.models import Conversation, FAQ, KnowledgeChunk, KnowledgeDocument, Order
from app.repositories import knowledge

from tests.conftest import DeterministicEmbedder


class FailingEmbedder(DeterministicEmbedder):
    async def embed_documents(self, texts):
        raise RuntimeError("simulated embedding outage")


def _admin_headers(login_headers, accounts):
    return login_headers(accounts["admin"]["email"])


def _create_faq(client, headers, *, active=True, category=None):
    response = client.post(
        "/admin/knowledge/faqs",
        headers=headers,
        json={
            "question": "Phase 8 test return window?",
            "answer": "Phase 8 test returns are accepted within 30 days.",
            "category": category or "phase8-test",
            "is_active": active,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_admin_routes_are_protected_in_the_backend(
    client: TestClient,
    accounts,
    login_headers,
) -> None:
    customer_headers = login_headers(accounts["customer_a"]["email"])
    # Login also writes cookies into the shared test client jar. Clear them so
    # the "anonymous" half of this test is genuinely unauthenticated.
    client.cookies.clear()
    protected = (
        ("get", "/admin/stats"),
        ("get", "/admin/orders"),
        ("post", "/admin/orders"),
        ("get", "/admin/conversations"),
        ("get", f"/admin/conversations/{accounts['conversation_a_id']}"),
        ("post", "/admin/ai/test"),
        ("get", "/admin/knowledge/faqs"),
        ("post", "/admin/knowledge/faqs"),
        ("get", "/admin/knowledge/documents"),
        ("post", "/admin/knowledge/documents"),
        ("post", "/admin/knowledge/reindex"),
    )

    for method, path in protected:
        request_kwargs = {"headers": customer_headers}
        if method in {"post", "put", "patch"}:
            request_kwargs["json"] = {}

        response = getattr(client, method)(path, **request_kwargs)
        assert response.status_code == 403, (method, path, response.text)
        assert response.json()["detail"] == "Administrator access required"

        request_kwargs.pop("headers")
        anonymous = getattr(client, method)(path, **request_kwargs)
        assert anonymous.status_code == 401, (method, path)


def test_admin_stats_returns_dashboard_counts(
    client: TestClient,
    accounts,
    login_headers,
) -> None:
    response = client.get(
        "/admin/stats",
        headers=_admin_headers(login_headers, accounts),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["users"] >= 3
    assert body["orders"] >= 2
    assert body["conversations"] >= 2
    assert body["faqs"] >= 0
    assert body["documents"] >= 0


def test_faq_crud_synchronizes_chunks_and_embeddings(
    client: TestClient,
    accounts,
    login_headers,
) -> None:
    headers = _admin_headers(login_headers, accounts)
    created = _create_faq(client, headers)
    faq_id = created["faq"]["id"]
    assert created["indexing"]["status"] == "indexed"
    assert created["indexing"]["chunks"] >= 1

    session = SessionLocal()
    try:
        chunks = knowledge.list_chunks_for_faq(session, uuid.UUID(faq_id))
        assert chunks
        assert chunks[0].embedding_model == "test-embedder"
        assert chunks[0].source_updated_at is not None

        updated = client.put(
            f"/admin/knowledge/faqs/{faq_id}",
            headers=headers,
            json={
                "question": "Phase 8 updated return window?",
                "answer": "Phase 8 updated answers are accepted within 60 days.",
                "category": "phase8-test",
                "is_active": True,
            },
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["indexing"]["status"] == "indexed"
        assert updated.json()["faq"]["question"].startswith("Phase 8 updated")

        session.expire_all()
        chunks = knowledge.list_chunks_for_faq(session, uuid.UUID(faq_id))
        assert any("60 days" in chunk.content for chunk in chunks)
        assert not any("30 days" in chunk.content for chunk in chunks)

        deactivated = client.put(
            f"/admin/knowledge/faqs/{faq_id}",
            headers=headers,
            json={
                "question": updated.json()["faq"]["question"],
                "answer": updated.json()["faq"]["answer"],
                "category": "phase8-test",
                "is_active": False,
            },
        )
        assert deactivated.status_code == 200, deactivated.text
        assert deactivated.json()["indexing"]["status"] == "deleted"
        session.expire_all()
        assert knowledge.list_chunks_for_faq(session, uuid.UUID(faq_id)) == []

        deleted = client.delete(
            f"/admin/knowledge/faqs/{faq_id}",
            headers=headers,
        )
        assert deleted.status_code == 204
        session.expire_all()
        assert session.get(FAQ, uuid.UUID(faq_id)) is None
        assert knowledge.list_chunks_for_faq(session, uuid.UUID(faq_id)) == []
    finally:
        session.execute(delete(FAQ).where(FAQ.id == uuid.UUID(faq_id)))
        session.commit()
        session.close()


def test_faq_indexing_failure_is_reported_not_swallowed(
    client: TestClient,
    accounts,
    login_headers,
) -> None:
    headers = _admin_headers(login_headers, accounts)
    failing = KnowledgeIngestor(
        FailingEmbedder(),
        max_tokens=200,
        overlap_tokens=40,
    )
    app.dependency_overrides[get_knowledge_ingestor] = lambda: failing
    faq_id = None

    try:
        response = client.post(
            "/admin/knowledge/faqs",
            headers=headers,
            json={
                "question": "Phase 8 failing FAQ?",
                "answer": "This answer cannot be embedded in this test.",
                "category": "phase8-test",
                "is_active": True,
            },
        )
        assert response.status_code == 201, response.text
        body = response.json()
        faq_id = body["faq"]["id"]
        assert body["indexing"]["status"] == "failed"
        assert "simulated embedding outage" in body["indexing"]["error"]

        reindex = client.post(
            f"/admin/knowledge/faqs/{faq_id}/reindex",
            headers=headers,
        )
        assert reindex.status_code == 502
        assert reindex.json()["detail"]["status"] == "failed"
        assert "simulated embedding outage" in reindex.json()["detail"]["error"]

        session = SessionLocal()
        try:
            assert knowledge.list_chunks_for_faq(
                session,
                uuid.UUID(faq_id),
            ) == []
        finally:
            session.close()
    finally:
        app.dependency_overrides.pop(get_knowledge_ingestor, None)
        if faq_id:
            session = SessionLocal()
            session.execute(delete(FAQ).where(FAQ.id == uuid.UUID(faq_id)))
            session.commit()
            session.close()


def test_document_crud_reindexes_and_retrieval_hides_inactive_sources(
    client: TestClient,
    accounts,
    login_headers,
) -> None:
    headers = _admin_headers(login_headers, accounts)
    created = client.post(
        "/admin/knowledge/documents",
        headers=headers,
        json={
            "title": "Phase 8 test policy",
            "content": (
                "Phase 8 returns policy. Unused products can be returned "
                "within 30 days of delivery for a full refund."
            ),
            "category": "phase8-test",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    document_id = created.json()["document"]["id"]
    assert created.json()["indexing"]["status"] == "indexed"

    session = SessionLocal()
    try:
        chunks = knowledge.list_chunks_for_document(
            session,
            uuid.UUID(document_id),
        )
        assert chunks

        matches = knowledge.search_chunks(
            session,
            [0.5] * 384,
            limit=10,
            embedding_model="test-embedder",
        )
        assert any(
            chunk.document_id == uuid.UUID(document_id)
            for chunk, _, _, _ in matches
        )

        deactivated = client.put(
            f"/admin/knowledge/documents/{document_id}",
            headers=headers,
            json={
                "title": "Phase 8 test policy",
                "content": created.json()["document"]["content"],
                "category": "phase8-test",
                "is_active": False,
            },
        )
        assert deactivated.status_code == 200, deactivated.text
        assert deactivated.json()["indexing"]["status"] == "deleted"

        session.expire_all()
        matches = knowledge.search_chunks(
            session,
            [0.5] * 384,
            limit=10,
            embedding_model="test-embedder",
        )
        assert not any(
            chunk.document_id == uuid.UUID(document_id)
            for chunk, _, _, _ in matches
        )

        reindex = client.post(
            f"/admin/knowledge/documents/{document_id}/reindex",
            headers=headers,
        )
        assert reindex.status_code == 200
        # Inactive sources have no vectors to refresh, so a re-index reports
        # "skipped" once the chunks are already gone.
        assert reindex.json()["status"] in {"deleted", "skipped"}
        assert reindex.json()["chunks"] == 0

        deleted = client.delete(
            f"/admin/knowledge/documents/{document_id}",
            headers=headers,
        )
        assert deleted.status_code == 204
        session.expire_all()
        assert session.get(KnowledgeDocument, uuid.UUID(document_id)) is None
        assert (
            session.scalar(
                select(KnowledgeChunk).where(
                    KnowledgeChunk.document_id == uuid.UUID(document_id)
                )
            )
            is None
        )
    finally:
        session.execute(
            delete(KnowledgeDocument).where(
                KnowledgeDocument.id == uuid.UUID(document_id)
            )
        )
        session.commit()
        session.close()


def test_admin_can_manage_synthetic_orders_and_items(
    client: TestClient,
    accounts,
    login_headers,
) -> None:
    headers = _admin_headers(login_headers, accounts)
    order_number = f"RX-2026-{uuid.uuid4().int % 100_000_000:08d}"

    created = client.post(
        "/admin/orders",
        headers=headers,
        json={
            "user_id": str(accounts["customer_a"]["id"]),
            "order_number": order_number,
            "status": "pending",
            "shipping_status": "not_shipped",
            "items": [
                {
                    "product_name": "Phase 8 Cable",
                    "quantity": 2,
                    "unit_price": "9.99",
                },
                {
                    "product_name": "Phase 8 Stand",
                    "quantity": 1,
                    "unit_price": "59.95",
                },
            ],
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    order_id = body["id"]
    assert body["order_number"] == order_number
    assert body["customer_email"] if "customer_email" in body else True
    assert body["user"]["email"] == accounts["customer_a"]["email"]
    assert Decimal(body["total_amount"]) == Decimal("79.93")
    assert len(body["items"]) == 2

    duplicate = client.post(
        "/admin/orders",
        headers=headers,
        json={
            "user_id": str(accounts["customer_a"]["id"]),
            "order_number": order_number,
            "items": [
                {
                    "product_name": "Duplicate",
                    "quantity": 1,
                    "unit_price": "1.00",
                }
            ],
        },
    )
    assert duplicate.status_code == 409

    unknown_customer = client.post(
        "/admin/orders",
        headers=headers,
        json={
            "user_id": str(uuid.uuid4()),
            "order_number": f"RX-2026-{uuid.uuid4().int % 100_000_000:08d}",
            "items": [
                {
                    "product_name": "No owner",
                    "quantity": 1,
                    "unit_price": "1.00",
                }
            ],
        },
    )
    assert unknown_customer.status_code == 404

    updated = client.patch(
        f"/admin/orders/{order_id}",
        headers=headers,
        json={
            "status": "processing",
            "shipping_status": "in_transit",
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["status"] == "processing"
    assert updated.json()["shipping_status"] == "in_transit"

    added = client.post(
        f"/admin/orders/{order_id}/items",
        headers=headers,
        json={
            "product_name": "Phase 8 Lamp",
            "quantity": 1,
            "unit_price": "39.99",
        },
    )
    assert added.status_code == 201
    assert Decimal(added.json()["total_amount"]) == Decimal("119.92")
    item_id = added.json()["items"][-1]["id"]

    patched_item = client.patch(
        f"/admin/orders/{order_id}/items/{item_id}",
        headers=headers,
        json={"quantity": 2, "unit_price": "10.00"},
    )
    assert patched_item.status_code == 200
    assert Decimal(patched_item.json()["total_amount"]) == Decimal("99.93")

    removed = client.delete(
        f"/admin/orders/{order_id}/items/{item_id}",
        headers=headers,
    )
    assert removed.status_code == 200
    assert Decimal(removed.json()["total_amount"]) == Decimal("79.93")

    listed = client.get("/admin/orders", headers=headers)
    assert listed.status_code == 200
    assert any(order["id"] == order_id for order in listed.json())

    missing_order = client.get(
        f"/admin/orders/{uuid.uuid4()}",
        headers=headers,
    )
    assert missing_order.status_code == 404

    session = SessionLocal()
    try:
        session.execute(delete(Order).where(Order.id == uuid.UUID(order_id)))
        session.commit()
    finally:
        session.close()


def test_admin_can_inspect_conversations(
    client: TestClient,
    accounts,
    login_headers,
) -> None:
    headers = _admin_headers(login_headers, accounts)

    listing = client.get("/admin/conversations", headers=headers)
    assert listing.status_code == 200
    conversation = next(
        item
        for item in listing.json()
        if item["id"] == str(accounts["conversation_a_id"])
    )
    assert conversation["customer_email"] == accounts["customer_a"]["email"]
    assert conversation["message_count"] == 2

    detail = client.get(
        f"/admin/conversations/{accounts['conversation_a_id']}",
        headers=headers,
    )
    assert detail.status_code == 200
    body = detail.json()
    # Both fixture messages may share a server timestamp, so only membership
    # (not row order) is deterministic.
    assert {message["content"] for message in body["messages"]} == {
        "Where is my order?",
        "Please share your order number.",
    }
    user_message = next(
        message
        for message in body["messages"]
        if message["content"] == "Where is my order?"
    )
    assert user_message["role"] == "user"
    assert user_message["metadata"] == {
        "source": "phase2-test",
        "attempt": 1,
    }

    missing = client.get(
        f"/admin/conversations/{uuid.uuid4()}",
        headers=headers,
    )
    assert missing.status_code == 404


def test_admin_ai_test_uses_the_real_orchestrator_and_supports_follow_ups(
    client: TestClient,
    accounts,
    login_headers,
    fake_llm_provider,
) -> None:
    headers = _admin_headers(login_headers, accounts)
    fake_llm_provider.reply = "A test answer from the real orchestrator."
    conversation_id = None

    try:
        first = client.post(
            "/admin/ai/test",
            headers=headers,
            json={"message": "What is the return window?"},
        )
        assert first.status_code == 200, first.text
        body = first.json()
        conversation_id = body["conversation"]["id"]
        assert body["conversation_created"] is True
        assert body["assistant_message"]["content"] == (
            "A test answer from the real orchestrator."
        )
        assert body["assistant_message"]["metadata"]["intent"] == (
            "return_refund_policy"
        )
        assert body["assistant_message"]["metadata"]["capabilities"] == [
            "knowledge_search",
            "llm_response",
        ]
        assert body["latency_ms"] >= 0

        follow_up = client.post(
            "/admin/ai/test",
            headers=headers,
            json={
                "message": "What about opened items?",
                "conversation_id": conversation_id,
            },
        )
        assert follow_up.status_code == 200, follow_up.text
        assert follow_up.json()["conversation"]["id"] == conversation_id
        assert follow_up.json()["conversation_created"] is False

        missing = client.post(
            "/admin/ai/test",
            headers=headers,
            json={
                "message": "Follow-up",
                "conversation_id": str(uuid.uuid4()),
            },
        )
        assert missing.status_code == 404
    finally:
        if conversation_id:
            session = SessionLocal()
            session.execute(
                delete(Conversation).where(
                    Conversation.id == uuid.UUID(conversation_id)
                )
            )
            session.commit()
            session.close()
