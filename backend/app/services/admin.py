from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Order, User
from app.repositories import orders, users


def list_users(session: Session) -> list[User]:
    """Administrator-only user listing. Schemas exclude password hashes."""
    return users.list_all(session)


def list_orders(session: Session) -> list[Order]:
    """Administrator-only order listing."""
    return orders.list_all(session)
