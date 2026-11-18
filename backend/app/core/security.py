"""Password hashing and JWT helpers.

New passwords are hashed with Argon2id. Existing Phase 1 PBKDF2-SHA256 hashes
remain verifiable so demo accounts can be upgraded transparently on login.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import (
    InvalidHashError,
    VerificationError,
    VerifyMismatchError,
)

from app.core.config import settings


# Argon2id defaults: 64 MiB memory, 3 iterations, 4 lanes.
_password_hasher = PasswordHasher()

# A real Argon2 hash used to keep failed login timing similar when an email
# does not exist. The plaintext is a random, unused development value.
DUMMY_PASSWORD_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$24IqL5qWrNsAe7OAQwyh4Q"
    "$ujQwcACqIKS/3ah+xEyGGb4Wi9NmzUpM3WRMDJnPlv8"
)

# Legacy Phase 1 format, retained for verification and transparent upgrades.
LEGACY_ALGORITHM = "pbkdf2_sha256"
LEGACY_PBKDF2_ITERATIONS = 600_000
_MAX_LEGACY_ITERATIONS = 10_000_000

ACCESS_TOKEN_TYPE = "access"

REFRESH_TOKEN_BYTES = 48


def hash_password(password: str) -> str:
    """Hash a password with Argon2id and a random salt.

    The plaintext password is never stored or logged.
    """
    if not password:
        raise ValueError("Password must not be empty")
    return _password_hasher.hash(password)


def is_argon2_hash(password_hash: str) -> bool:
    """Return True when a stored hash uses Argon2."""
    return password_hash.startswith("$argon2")


def password_needs_rehash(password_hash: str) -> bool:
    """Return True when a hash should be replaced after a successful login."""
    if not is_argon2_hash(password_hash):
        return True
    try:
        return _password_hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def _verify_legacy_pbkdf2(password: str, password_hash: str) -> bool:
    """Verify a Phase 1 PBKDF2-SHA256 hash in constant time."""
    try:
        algorithm, iterations_text, salt, expected = password_hash.split("$", 3)
        if algorithm != LEGACY_ALGORITHM:
            return False

        iterations = int(iterations_text)
        if not 1 <= iterations <= _MAX_LEGACY_ITERATIONS:
            return False

        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("ascii"),
            iterations,
        )
        encoded = base64.b64encode(digest).decode("ascii")
        return hmac.compare_digest(encoded, expected)
    except (AttributeError, TypeError, ValueError):
        return False


def verify_password(password: str, password_hash: str) -> bool:
    """Verify an Argon2id or legacy PBKDF2 password hash securely."""
    if not password or not password_hash:
        return False

    if is_argon2_hash(password_hash):
        try:
            return _password_hasher.verify(password_hash, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False

    if password_hash.startswith(f"{LEGACY_ALGORITHM}$"):
        return _verify_legacy_pbkdf2(password, password_hash)

    return False


def create_access_token(
    *,
    subject: str,
    role: str,
    expires_delta: timedelta | None = None,
) -> tuple[str, int]:
    """Create a signed access token and return ``(token, expires_in_seconds)``.

    ``subject`` is the user UUID. Authorization decisions still reload the user
    from the database; the role claim is informational for clients.
    """
    if not subject:
        raise ValueError("Token subject must not be empty")
    if role not in {"customer", "admin"}:
        raise ValueError("Unsupported role claim")

    if expires_delta is None:
        expires_delta = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    now = datetime.now(timezone.utc)
    issued_at = int(now.timestamp())
    expires_at = int((now + expires_delta).timestamp())

    payload: dict[str, Any] = {
        "sub": subject,
        "role": role,
        "type": ACCESS_TOKEN_TYPE,
        "iat": issued_at,
        "nbf": issued_at,
        "exp": expires_at,
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
        "jti": str(uuid.uuid4()),
    }

    token = jwt.encode(
        payload,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    return token, int(expires_delta.total_seconds())


def create_refresh_token_value() -> str:
    """Return a high-entropy opaque refresh token for an HttpOnly cookie."""
    return secrets.token_urlsafe(REFRESH_TOKEN_BYTES)


def hash_refresh_token(token: str) -> str:
    """Return the SHA-256 digest stored for an opaque refresh token."""
    if not token:
        raise ValueError("Refresh token must not be empty")
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT access token.

    Raises ``jwt.InvalidTokenError`` (including its ``ExpiredSignatureError``
    subclass) when the token is malformed, expired, signed with the wrong key,
    has the wrong issuer/audience, or is not an access token.
    """
    payload = jwt.decode(
        token,
        settings.JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
        audience=settings.JWT_AUDIENCE,
        issuer=settings.JWT_ISSUER,
        options={
            "require": ["sub", "role", "type", "iat", "nbf", "exp", "iss", "aud"],
        },
    )

    if payload.get("type") != ACCESS_TOKEN_TYPE:
        raise jwt.InvalidTokenError("Unsupported token type")

    subject = payload.get("sub")
    if not isinstance(subject, str) or not subject:
        raise jwt.InvalidTokenError("Invalid token subject")

    return payload


def generate_secret_key() -> str:
    """Generate a cryptographically strong secret for local configuration."""
    return secrets.token_urlsafe(48)
