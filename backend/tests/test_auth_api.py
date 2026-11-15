from __future__ import annotations

import base64
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.core.config import settings
from app.core.security import create_access_token, hash_password, is_argon2_hash
from app.db.session import SessionLocal
from app.models import User


def _legacy_pbkdf2_hash(password: str) -> str:
    salt = secrets.token_hex(16)
    iterations = 1_000
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("ascii"),
        iterations,
    )
    return (
        f"pbkdf2_sha256${iterations}${salt}$"
        f"{base64.b64encode(digest).decode('ascii')}"
    )


def test_customer_login_returns_token_and_public_user(
    client: TestClient,
    accounts,
) -> None:
    response = client.post(
        "/auth/login",
        json={
            "email": accounts["customer_a"]["email"],
            "password": accounts["password"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["access_token"]
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    assert body["user"]["email"] == accounts["customer_a"]["email"]
    assert body["user"]["role"] == "customer"
    assert "password_hash" not in response.text
    assert "$argon2" not in response.text


def test_admin_login_returns_admin_role(client: TestClient, accounts) -> None:
    response = client.post(
        "/auth/login",
        json={
            "email": accounts["admin"]["email"],
            "password": accounts["password"],
        },
    )

    assert response.status_code == 200
    assert response.json()["user"]["role"] == "admin"


def test_login_normalizes_email_case(client: TestClient, accounts) -> None:
    response = client.post(
        "/auth/login",
        json={
            "email": accounts["customer_a"]["email"].upper(),
            "password": accounts["password"],
        },
    )

    assert response.status_code == 200
    assert (
        response.json()["user"]["email"]
        == accounts["customer_a"]["email"].lower()
    )


def test_login_accepts_the_synthetic_local_demo_domain(
    client: TestClient,
) -> None:
    email = f"phase2-local-{uuid.uuid4().hex[:10]}@resolvix.local"
    password = "LocalPass123!"
    session = SessionLocal()
    user = User(
        name="Local Domain User",
        email=email,
        password_hash=hash_password(password),
        role="admin",
    )
    session.add(user)
    session.commit()
    user_id = user.id

    try:
        response = client.post(
            "/auth/login",
            json={"email": email.upper(), "password": password},
        )
        assert response.status_code == 200, response.text
        assert response.json()["user"]["email"] == email
        assert response.json()["user"]["role"] == "admin"
    finally:
        session.execute(delete(User).where(User.id == user_id))
        session.commit()
        session.close()


def test_wrong_password_and_unknown_email_are_indistinguishable(
    client: TestClient,
    accounts,
) -> None:
    wrong_password = client.post(
        "/auth/login",
        json={
            "email": accounts["customer_a"]["email"],
            "password": "WrongPassword123!",
        },
    )
    unknown_email = client.post(
        "/auth/login",
        json={
            "email": f"missing-{uuid.uuid4().hex[:8]}@example.com",
            "password": accounts["password"],
        },
    )

    assert wrong_password.status_code == 401
    assert unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()
    assert wrong_password.json()["detail"] == "Invalid email or password"
    assert wrong_password.headers["www-authenticate"] == "Bearer"
    assert "Traceback" not in wrong_password.text
    assert "argon2" not in wrong_password.text.lower()


def test_login_validation_rejects_missing_fields(client: TestClient) -> None:
    response = client.post("/auth/login", json={"email": "not-an-email"})

    assert response.status_code == 422
    assert "password" in response.text
    assert "Traceback" not in response.text


def test_login_upgrades_a_legacy_pbkdf2_hash(
    client: TestClient,
) -> None:
    email = f"phase2-legacy-{uuid.uuid4().hex[:10]}@example.com"
    password = "LegacyPass123!"
    session = SessionLocal()
    user = User(
        name="Legacy Hash User",
        email=email,
        password_hash=_legacy_pbkdf2_hash(password),
        role="customer",
    )
    session.add(user)
    session.commit()
    user_id = user.id
    assert not is_argon2_hash(user.password_hash)

    try:
        response = client.post(
            "/auth/login",
            json={"email": email, "password": password},
        )
        assert response.status_code == 200

        session.expire_all()
        refreshed = session.get(User, user_id)
        assert refreshed is not None
        assert is_argon2_hash(refreshed.password_hash)
    finally:
        session.execute(delete(User).where(User.id == user_id))
        session.commit()
        session.close()


def test_me_requires_a_bearer_token(client: TestClient) -> None:
    response = client.get("/auth/me")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["detail"] == "Could not validate credentials"


def test_me_returns_the_authenticated_user(
    client: TestClient,
    accounts,
    login_headers,
) -> None:
    response = client.get(
        "/auth/me",
        headers=login_headers(accounts["customer_a"]["email"]),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(accounts["customer_a"]["id"])
    assert body["email"] == accounts["customer_a"]["email"]
    assert body["role"] == "customer"
    assert "password_hash" not in body


def test_invalid_and_expired_tokens_are_rejected(
    client: TestClient,
    accounts,
) -> None:
    invalid = client.get(
        "/auth/me",
        headers={"Authorization": "Bearer not-a-jwt"},
    )
    expired_token, _ = create_access_token(
        subject=str(accounts["customer_a"]["id"]),
        role="customer",
        expires_delta=timedelta(seconds=-60),
    )
    expired = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {expired_token}"},
    )

    assert invalid.status_code == 401
    assert expired.status_code == 401
    assert invalid.json()["detail"] == "Could not validate credentials"
    assert expired.json()["detail"] == "Could not validate credentials"


def test_non_access_token_type_is_rejected(
    client: TestClient,
    accounts,
) -> None:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(accounts["customer_a"]["id"]),
        "role": "customer",
        "type": "refresh",
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
    }
    token = jwt.encode(
        payload,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )

    response = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401


def test_token_for_deleted_user_is_rejected(client: TestClient) -> None:
    session = SessionLocal()
    user = User(
        name="Deleted User",
        email=f"phase2-deleted-{uuid.uuid4().hex[:10]}@example.com",
        password_hash="unused",
        role="customer",
    )
    session.add(user)
    session.commit()
    user_id = user.id
    session.execute(delete(User).where(User.id == user_id))
    session.commit()
    session.close()

    token, _ = create_access_token(
        subject=str(user_id),
        role="customer",
    )
    response = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401


def test_logout_requires_authentication_and_returns_no_content(
    client: TestClient,
    accounts,
    login_headers,
) -> None:
    headers = login_headers(accounts["customer_a"]["email"])

    unauthorized = client.post("/auth/logout")
    response = client.post("/auth/logout", headers=headers)

    assert unauthorized.status_code == 401
    assert response.status_code == 204
    assert response.content == b""
