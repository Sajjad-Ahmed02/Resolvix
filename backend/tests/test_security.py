from __future__ import annotations

import base64
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.core.config import settings
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    is_argon2_hash,
    password_needs_rehash,
    verify_password,
)


def _legacy_pbkdf2_hash(password: str, iterations: int = 1_000) -> str:
    """Build a Phase 1-compatible hash for upgrade testing."""
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("ascii"),
        iterations,
    )
    encoded = base64.b64encode(digest).decode("ascii")
    return f"pbkdf2_sha256${iterations}${salt}${encoded}"


def test_passwords_use_salted_argon2id_hashes() -> None:
    first = hash_password("S3cure!password")
    second = hash_password("S3cure!password")

    assert first.startswith("$argon2id$")
    assert first != second
    assert is_argon2_hash(first)
    assert verify_password("S3cure!password", first)
    assert not verify_password("wrong-password", first)
    assert not password_needs_rehash(first)


def test_legacy_pbkdf2_hashes_still_verify_and_are_upgraded() -> None:
    legacy = _legacy_pbkdf2_hash("Legacy123!")

    assert not is_argon2_hash(legacy)
    assert verify_password("Legacy123!", legacy)
    assert not verify_password("wrong", legacy)
    assert password_needs_rehash(legacy)


def test_malformed_password_hashes_are_rejected() -> None:
    assert not verify_password("anything", "")
    assert not verify_password("anything", "not-a-real-hash")
    assert not verify_password("", hash_password("Password123!"))


def test_access_token_round_trip() -> None:
    user_id = uuid.uuid4()
    token, expires_in = create_access_token(
        subject=str(user_id),
        role="customer",
    )

    payload = decode_access_token(token)
    assert payload["sub"] == str(user_id)
    assert payload["role"] == "customer"
    assert payload["type"] == "access"
    assert payload["iss"] == settings.JWT_ISSUER
    assert payload["aud"] == settings.JWT_AUDIENCE
    assert expires_in == settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60


def test_expired_access_token_is_rejected() -> None:
    token, _ = create_access_token(
        subject=str(uuid.uuid4()),
        role="customer",
        expires_delta=timedelta(seconds=-60),
    )

    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(token)


def test_tampered_access_token_is_rejected() -> None:
    token, _ = create_access_token(
        subject=str(uuid.uuid4()),
        role="customer",
    )
    replacement = "A" if token[-1] != "A" else "B"
    tampered = token[:-1] + replacement

    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(tampered)


def test_token_with_wrong_type_is_rejected() -> None:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(uuid.uuid4()),
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

    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(token)


def test_token_signed_with_another_key_is_rejected() -> None:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(uuid.uuid4()),
        "role": "customer",
        "type": "access",
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
    }
    token = jwt.encode(
        payload,
        "a-different-secret-key-that-is-long-enough-0123456789",
        algorithm="HS256",
    )

    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(token)
