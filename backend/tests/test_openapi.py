from __future__ import annotations

from fastapi.testclient import TestClient


EXPECTED_PATHS = {
    "/",
    "/health",
    "/auth/login",
    "/auth/me",
    "/auth/logout",
    "/conversations",
    "/conversations/{conversation_id}",
    "/conversations/{conversation_id}/messages",
    "/orders",
    "/orders/{order_number}",
    "/admin/users",
    "/admin/orders",
    "/admin/knowledge/faqs",
    "/admin/knowledge/documents",
}


def test_swagger_ui_is_available(client: TestClient) -> None:
    response = client.get("/docs")

    assert response.status_code == 200
    assert "swagger-ui" in response.text.lower()


def test_openapi_documents_all_endpoints_and_bearer_auth(
    client: TestClient,
) -> None:
    spec = client.get("/openapi.json").json()

    assert EXPECTED_PATHS <= set(spec["paths"])
    assert spec["info"]["title"] == "Resolvix"
    assert spec["info"]["version"] == "0.2.0"

    security_schemes = spec["components"]["securitySchemes"]
    assert security_schemes["Bearer JWT"]["type"] == "http"
    assert security_schemes["Bearer JWT"]["scheme"] == "bearer"

    assert spec["paths"]["/admin/users"]["get"]["security"] == [
        {"Bearer JWT": []}
    ]
    assert spec["paths"]["/orders"]["get"]["security"] == [{"Bearer JWT": []}]
    assert spec["paths"]["/auth/login"]["post"].get("security") is None
