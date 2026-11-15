from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.security import (
    DUMMY_PASSWORD_HASH,
    create_access_token,
    hash_password,
    password_needs_rehash,
    verify_password,
)
from app.models import User
from app.repositories import users


def authenticate_and_issue_token(
    session: Session,
    *,
    email: str,
    password: str,
) -> tuple[User, str, int] | None:
    """Authenticate a pre-seeded account and return a JWT access token.

    Unknown emails still run a password verification against a dummy Argon2
    hash so response timing does not disclose whether an account exists.
    Successful logins transparently upgrade legacy Phase 1 hashes.
    """
    user = users.get_by_email(session, email)

    if user is None:
        verify_password(password, DUMMY_PASSWORD_HASH)
        return None

    if not verify_password(password, user.password_hash):
        return None

    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
        session.commit()

    token, expires_in = create_access_token(
        subject=str(user.id),
        role=user.role,
    )
    return user, token, expires_in
