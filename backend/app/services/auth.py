from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    create_access_token,
    create_refresh_token_value,
    hash_password,
    hash_refresh_token,
    password_needs_rehash,
    verify_password,
)
from app.models import User
from app.repositories import refresh_tokens, users


@dataclass(frozen=True, slots=True)
class AuthTokens:
    """Newly issued access token plus the sliding refresh cookie value."""

    access_token: str
    expires_in: int
    refresh_token: str
    refresh_expires_in: int


def authenticate_user(
    session: Session,
    *,
    email: str,
    password: str,
) -> User | None:
    """Verify a pre-seeded account's credentials.

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

    return user


def _refresh_expiry(now: datetime) -> datetime:
    return now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)


def issue_session_tokens(session: Session, user: User) -> AuthTokens:
    """Create an access JWT and persist a new hashed refresh token."""
    now = datetime.now(timezone.utc)
    raw_refresh = create_refresh_token_value()
    refresh_tokens.create(
        session,
        user_id=user.id,
        token_hash=hash_refresh_token(raw_refresh),
        expires_at=_refresh_expiry(now),
    )
    session.commit()

    access_token, expires_in = create_access_token(
        subject=str(user.id),
        role=user.role,
    )
    return AuthTokens(
        access_token=access_token,
        expires_in=expires_in,
        refresh_token=raw_refresh,
        refresh_expires_in=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
    )


def refresh_session(
    session: Session,
    raw_refresh_token: str | None,
) -> tuple[User, AuthTokens] | None:
    """Exchange a valid refresh cookie for a fresh access token.

    The refresh token is not rotated on every request, which keeps concurrent
    tabs from invalidating each other. Its database expiry and HttpOnly cookie
    expiry both slide forward on each successful use. Revoked, expired, and
    unknown tokens return ``None`` without revealing which condition failed.
    """
    if not raw_refresh_token:
        return None

    try:
        token_hash = hash_refresh_token(raw_refresh_token)
    except ValueError:
        return None

    now = datetime.now(timezone.utc)
    row = refresh_tokens.get_by_hash(session, token_hash)
    if row is None or row.revoked_at is not None or row.expires_at <= now:
        return None

    user = users.get_by_id(session, row.user_id)
    if user is None:
        refresh_tokens.revoke(session, row, at=now)
        session.commit()
        return None

    row.expires_at = _refresh_expiry(now)
    row.last_used_at = now
    session.commit()

    access_token, expires_in = create_access_token(
        subject=str(user.id),
        role=user.role,
    )
    return user, AuthTokens(
        access_token=access_token,
        expires_in=expires_in,
        # Re-send the same opaque token so the browser cookie expiry slides.
        refresh_token=raw_refresh_token,
        refresh_expires_in=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
    )


def revoke_session(session: Session, raw_refresh_token: str | None) -> None:
    """Revoke the presented refresh token. Unknown tokens are ignored."""
    if not raw_refresh_token:
        return
    try:
        token_hash = hash_refresh_token(raw_refresh_token)
    except ValueError:
        return

    row = refresh_tokens.get_by_hash(session, token_hash)
    if row is None or row.revoked_at is not None:
        return
    refresh_tokens.revoke(
        session,
        row,
        at=datetime.now(timezone.utc),
    )
    session.commit()


def revoke_all_sessions(session: Session, user_id) -> None:
    """Revoke every refresh token for one user, e.g. after a role change."""
    refresh_tokens.revoke_all_for_user(
        session,
        user_id,
        at=datetime.now(timezone.utc),
    )
    session.commit()
