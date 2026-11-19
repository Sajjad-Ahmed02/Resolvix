from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_root_reports_running_api(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.json()["status"] == "running"


def test_health_checks_database(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "healthy",
        "application": "Resolvix",
        "version": "0.3.0",
        "database": "ok",
    }


def test_health_reports_database_outage_without_details(
    client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.api.routes.health.check_database_connection",
        lambda: False,
    )

    response = client.get("/health")

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert response.json()["database"] == "unavailable"
    assert "postgres" not in response.text.lower()
    assert "DATABASE_URL" not in response.text


def test_unhandled_errors_are_sanitized(monkeypatch) -> None:
    def explode() -> bool:
        raise RuntimeError("internal password=super-secret")

    monkeypatch.setattr(
        "app.api.routes.health.check_database_connection",
        explode,
    )

    with TestClient(app, raise_server_exceptions=False) as test_client:
        response = test_client.get("/health")

    assert response.status_code == 500
    body = response.json()
    assert body["detail"] == "An unexpected error occurred."
    assert body["request_id"] == response.headers["X-Request-ID"]
    assert "RuntimeError" not in response.text
    assert "super-secret" not in response.text
    assert "Traceback" not in response.text
