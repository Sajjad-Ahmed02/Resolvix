from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import RefreshToken


def create(
    session: Session,
    *,
    user_id: UUID,
    token_hash: str,
    expires_at: datetime,
) -> RefreshToken:
    token = RefreshToken(
        user_id=user_id,
        token_hash=token_hash,
        expires_at=expires_at,
    )
    session.add(token)
    session.flush()
    return token


def get_by_hash(session: Session, token_hash: str) -> RefreshToken | None:
    """Return a token row by digest, including revoked/expired rows."""
    return session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )


def revoke(session: Session, token: RefreshToken, *, at: datetime) -> None:
    token.revoked_at = at
    session.flush()


def revoke_all_for_user(
    session: Session,
    user_id: UUID,
    *,
    at: datetime,
) -> None:
    tokens = session.scalars(
        select(RefreshToken).where(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked_at.is_(None),
        )
    ).all()
    for token in tokens:
        token.revoked_at = at
    session.flush()


def delete_expired(session: Session, *, now: datetime) -> int:
    """Remove rows that can no longer authenticate anyone."""
    result = session.execute(
        delete(RefreshToken).where(RefreshToken.expires_at <= now)
    )
    return result.rowcount or 0
