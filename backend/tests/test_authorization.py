from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.models import FAQ, KnowledgeDocument, User


ADMIN_ENDPOINTS = (
    "/admin/users",
    "/admin/orders",
    "/admin/knowledge/faqs",
    "/admin/knowledge/documents",
)


def test_customer_sees_only_their_own_orders(
    client: TestClient,
    accounts,
    login_headers,
) -> None:
    response = client.get(
        "/orders",
        headers=login_headers(accounts["customer_a"]["email"]),
    )

    assert response.status_code == 200
    body = response.json()
    assert [order["order_number"] for order in body] == [
        accounts["order_a_number"]
    ]
    assert body[0]["items"][0]["product_name"] == "Test USB-C Cable"


def test_customer_cannot_read_another_customers_order(
    client: TestClient,
    accounts,
    login_headers,
) -> None:
    response = client.get(
        f"/orders/{accounts['order_b_number']}",
        headers=login_headers(accounts["customer_a"]["email"]),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Order not found"
    assert accounts["order_b_number"] not in response.text


def test_user_id_query_parameter_cannot_override_token_identity(
    client: TestClient,
    accounts,
    login_headers,
) -> None:
    response = client.get(
        "/orders",
        headers=login_headers(accounts["customer_a"]["email"]),
        params={"user_id": str(accounts["customer_b"]["id"])},
    )

    assert response.status_code == 200
    assert [order["order_number"] for order in response.json()] == [
        accounts["order_a_number"]
    ]


def test_conversations_are_scoped_to_the_authenticated_customer(
    client: TestClient,
    accounts,
    login_headers,
) -> None:
    headers = login_headers(accounts["customer_a"]["email"])

    listing = client.get("/conversations", headers=headers)
    own_detail = client.get(
        f"/conversations/{accounts['conversation_a_id']}",
        headers=headers,
    )
    other_detail = client.get(
        f"/conversations/{accounts['conversation_b_id']}",
        headers=headers,
    )
    other_messages = client.get(
        f"/conversations/{accounts['conversation_b_id']}/messages",
        headers=headers,
    )

    assert listing.status_code == 200
    assert [item["id"] for item in listing.json()] == [
        str(accounts["conversation_a_id"])
    ]
    assert own_detail.status_code == 200
    assert len(own_detail.json()["messages"]) == 2
    assert own_detail.json()["messages"][0]["metadata"] == {
        "source": "phase2-test",
        "attempt": 1,
    }
    assert other_detail.status_code == 404
    assert other_messages.status_code == 404
    assert "Customer B private message" not in other_detail.text


def test_customer_cannot_access_admin_endpoints(
    client: TestClient,
    accounts,
    login_headers,
) -> None:
    headers = login_headers(accounts["customer_a"]["email"])

    for path in ADMIN_ENDPOINTS:
        response = client.get(path, headers=headers)
        assert response.status_code == 403, path
        assert response.json()["detail"] == "Administrator access required"


def test_protected_endpoints_require_authentication(
    client: TestClient,
) -> None:
    for path in ("/auth/me", "/conversations", "/orders", *ADMIN_ENDPOINTS):
        response = client.get(path)
        assert response.status_code == 401, path


def test_role_claim_in_token_does_not_grant_admin_access(
    client: TestClient,
    accounts,
) -> None:
    forged_role_token, _ = create_access_token(
        subject=str(accounts["customer_a"]["id"]),
        role="admin",
    )

    response = client.get(
        "/admin/users",
        headers={"Authorization": f"Bearer {forged_role_token}"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Administrator access required"


def test_authorization_uses_current_database_role(
    client: TestClient,
    accounts,
) -> None:
    stale_role_token, _ = create_access_token(
        subject=str(accounts["admin"]["id"]),
        role="customer",
    )

    response = client.get(
        "/admin/users",
        headers={"Authorization": f"Bearer {stale_role_token}"},
    )

    assert response.status_code == 200


def test_admin_demotion_takes_effect_immediately(
    client: TestClient,
    accounts,
    login_headers,
) -> None:
    headers = login_headers(accounts["admin"]["email"])
    assert client.get("/admin/users", headers=headers).status_code == 200

    session = SessionLocal()
    admin = session.get(User, accounts["admin"]["id"])
    assert admin is not None
    admin.role = "customer"
    session.commit()
    session.close()

    response = client.get("/admin/users", headers=headers)
    assert response.status_code == 403
    assert response.json()["detail"] == "Administrator access required"


def test_admin_can_list_users_without_password_hashes(
    client: TestClient,
    accounts,
    login_headers,
) -> None:
    response = client.get(
        "/admin/users",
        headers=login_headers(accounts["admin"]["email"]),
    )

    assert response.status_code == 200
    emails = {user["email"] for user in response.json()}
    assert accounts["admin"]["email"] in emails
    assert accounts["customer_a"]["email"] in emails
    assert "password_hash" not in response.text
    assert "$argon2" not in response.text


def test_admin_can_list_all_orders(
    client: TestClient,
    accounts,
    login_headers,
) -> None:
    response = client.get(
        "/admin/orders",
        headers=login_headers(accounts["admin"]["email"]),
    )

    assert response.status_code == 200
    order_numbers = {order["order_number"] for order in response.json()}
    assert accounts["order_a_number"] in order_numbers
    assert accounts["order_b_number"] in order_numbers


def test_admin_can_list_knowledge_sources(
    client: TestClient,
    accounts,
    login_headers,
) -> None:
    session = SessionLocal()
    suffix = uuid.uuid4().hex[:10]
    faq = FAQ(
        question=f"Phase 2 test FAQ {suffix}",
        answer="Temporary answer for authorization testing.",
        category="Testing",
        is_active=False,
    )
    document = KnowledgeDocument(
        title=f"Phase 2 test document {suffix}",
        content="Temporary content for authorization testing.",
        category="Testing",
        is_active=False,
    )
    session.add_all([faq, document])
    session.commit()
    faq_id = faq.id
    document_id = document.id

    try:
        headers = login_headers(accounts["admin"]["email"])
        faqs = client.get("/admin/knowledge/faqs", headers=headers)
        documents = client.get("/admin/knowledge/documents", headers=headers)

        assert faqs.status_code == 200
        assert documents.status_code == 200
        assert any(item["id"] == str(faq_id) for item in faqs.json())
        assert any(
            item["id"] == str(document_id) for item in documents.json()
        )
        assert {"question", "answer", "category", "is_active"} <= set(
            faqs.json()[0]
        )
        assert {"title", "content", "category", "is_active"} <= set(
            documents.json()[0]
        )
    finally:
        session.execute(delete(FAQ).where(FAQ.id == faq_id))
        session.execute(
            delete(KnowledgeDocument).where(
                KnowledgeDocument.id == document_id
            )
        )
        session.commit()
        session.close()
