from __future__ import annotations

from fastapi.testclient import TestClient


EXPECTED_PATHS = {
    "/",
    "/health",
    "/auth/login",
    "/auth/refresh",
    "/auth/me",
    "/auth/logout",
    "/conversations",
    "/conversations/{conversation_id}",
    "/conversations/{conversation_id}/messages",
    "/orders",
    "/orders/{order_number}",
    "/admin/users",
    "/admin/stats",
    "/admin/orders",
    "/admin/orders/{order_id}",
    "/admin/orders/{order_id}/items",
    "/admin/orders/{order_id}/items/{item_id}",
    "/admin/knowledge/faqs",
    "/admin/knowledge/faqs/{faq_id}",
    "/admin/knowledge/faqs/{faq_id}/reindex",
    "/admin/knowledge/documents",
    "/admin/knowledge/documents/{document_id}",
    "/admin/knowledge/documents/{document_id}/reindex",
    "/admin/knowledge/reindex",
    "/admin/conversations",
    "/admin/conversations/{conversation_id}",
    "/admin/ai/test",
}


def test_swagger_ui_is_available(client: TestClient) -> None:
    response = client.get("/docs")

    assert response.status_code == 200
    assert "swagger-ui" in response.text.lower()


def test_openapi_documents_all_endpoints_and_auth_schemes(
    client: TestClient,
) -> None:
    spec = client.get("/openapi.json").json()

    assert EXPECTED_PATHS <= set(spec["paths"])
    assert spec["info"]["title"] == "Resolvix"
    assert spec["info"]["version"] == "0.2.0"

    security_schemes = spec["components"]["securitySchemes"]
    assert security_schemes["Bearer JWT"]["type"] == "http"
    assert security_schemes["Bearer JWT"]["scheme"] == "bearer"
    assert security_schemes["Access Cookie"]["type"] == "apiKey"
    assert security_schemes["Access Cookie"]["in"] == "cookie"

    admin_security = spec["paths"]["/admin/users"]["get"]["security"]
    assert {"Bearer JWT": []} in admin_security
    assert {"Access Cookie": []} in admin_security
    assert spec["paths"]["/orders"]["get"]["security"] == admin_security
    assert spec["paths"]["/auth/login"]["post"].get("security") is None
