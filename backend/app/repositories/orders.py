from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Order


def list_for_user(
    session: Session,
    user_id: UUID,
    *,
    with_items: bool = True,
) -> list[Order]:
    """Return only the orders owned by ``user_id``."""
    statement = (
        select(Order)
        .where(Order.user_id == user_id)
        .order_by(Order.order_date.desc(), Order.id)
    )
    if with_items:
        statement = statement.options(selectinload(Order.items))
    return list(session.scalars(statement).all())


def get_for_user_by_number(
    session: Session,
    user_id: UUID,
    order_number: str,
    *,
    with_items: bool = True,
) -> Order | None:
    """Return an order only when it belongs to ``user_id``.

    The user id always comes from the authenticated token, never from a request
    parameter, body field, or LLM tool argument.
    """
    statement = select(Order).where(
        Order.user_id == user_id,
        Order.order_number == order_number,
    )
    if with_items:
        statement = statement.options(selectinload(Order.items))
    return session.scalar(statement)


def get_by_number(
    session: Session,
    order_number: str,
    *,
    with_items: bool = True,
) -> Order | None:
    """Return any order by number. Used by explicitly authorized admin code."""
    statement = select(Order).where(Order.order_number == order_number)
    if with_items:
        statement = statement.options(selectinload(Order.items))
    return session.scalar(statement)


def list_all(session: Session) -> list[Order]:
    """Return every order for administrator reporting."""
    return list(
        session.scalars(
            select(Order).order_by(Order.order_date.desc(), Order.id)
        ).all()
    )
