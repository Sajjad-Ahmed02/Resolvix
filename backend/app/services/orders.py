from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.models import Order
from app.repositories import orders


def list_for_user(session: Session, user_id: UUID) -> list[Order]:
    """Return only the authenticated customer's orders."""
    return orders.list_for_user(session, user_id)


def get_for_user(
    session: Session,
    user_id: UUID,
    order_number: str,
) -> Order | None:
    """Return an order only when it belongs to the authenticated customer.

    A different customer's order is indistinguishable from a missing order, so
    the API returns 404 and does not reveal that the order number exists.
    """
    return orders.get_for_user_by_number(session, user_id, order_number)


def list_all_for_admin(session: Session) -> list[Order]:
    """Administrator-only order listing."""
    return orders.list_all(session)
