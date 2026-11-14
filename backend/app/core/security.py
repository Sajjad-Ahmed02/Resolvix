"""Password hashing helpers used by seed data and future authentication code."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets


ALGORITHM = "pbkdf2_sha256"
PBKDF2_ITERATIONS = 600_000


def hash_password(password: str) -> str:
    """Hash a password with PBKDF2-HMAC-SHA256 and a random salt.

    Format: ``pbkdf2_sha256$<iterations>$<salt>$<base64-digest>``.
    The plaintext password is never stored.
    """
    if not password:
        raise ValueError("Password must not be empty")

    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("ascii"),
        PBKDF2_ITERATIONS,
    )
    encoded = base64.b64encode(digest).decode("ascii")
    return f"{ALGORITHM}${PBKDF2_ITERATIONS}${salt}${encoded}"


def verify_password(password: str, password_hash: str) -> bool:
    """Return True when ``password`` matches a stored PBKDF2 hash."""
    try:
        algorithm, iterations_text, salt, expected = password_hash.split("$", 3)
        if algorithm != ALGORITHM:
            return False

        iterations = int(iterations_text)
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
