from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import User


def get_by_id(session: Session, user_id: UUID) -> User | None:
    """Return a user by primary key."""
    return session.get(User, user_id)


def get_by_email(session: Session, email: str) -> User | None:
    """Return a user by their normalized lowercase email address."""
    return session.scalar(
        select(User).where(User.email == email.strip().lower())
    )


def list_all(session: Session) -> list[User]:
    """Return every user, newest first. For administrator endpoints only."""
    return list(
        session.scalars(
            select(User).order_by(User.created_at.desc(), User.email)
        ).all()
    )


def count(session: Session, *, role: str | None = None) -> int:
    statement = select(func.count()).select_from(User)
    if role is not None:
        statement = statement.where(User.role == role)
    return int(session.scalar(statement) or 0)
