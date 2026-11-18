from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models import Order, OrderItem


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
    parameter, body field, or LLM tool argument. Order numbers are compared
    case-insensitively because customers may retype them with different
    casing.
    """
    statement = select(Order).where(
        Order.user_id == user_id,
        func.lower(Order.order_number) == order_number.strip().lower(),
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


def list_items_for_order(
    session: Session,
    order_id: UUID,
) -> list[OrderItem]:
    """Return items only after the caller has authorized the parent order.

    This deliberately accepts an order id rather than a customer-supplied order
    number so item access cannot bypass the ownership-scoped order query.
    """
    return list(
        session.scalars(
            select(OrderItem)
            .where(OrderItem.order_id == order_id)
            .order_by(OrderItem.product_name, OrderItem.id)
        ).all()
    )


def get_by_id(
    session: Session,
    order_id: UUID,
    *,
    with_items: bool = True,
) -> Order | None:
    """Return an order for an explicitly authorized administrator view."""
    statement = select(Order).where(Order.id == order_id)
    if with_items:
        statement = statement.options(
            selectinload(Order.items),
            joinedload(Order.user),
        )
    return session.scalar(statement)


def get_item(
    session: Session,
    order_id: UUID,
    item_id: UUID,
) -> OrderItem | None:
    return session.scalar(
        select(OrderItem).where(
            OrderItem.id == item_id,
            OrderItem.order_id == order_id,
        )
    )


def list_all(session: Session) -> list[Order]:
    """Return every order for administrator management."""
    return list(
        session.scalars(
            select(Order)
            .options(
                selectinload(Order.items),
                joinedload(Order.user),
            )
            .order_by(Order.order_date.desc(), Order.id)
        ).all()
    )


def count(session: Session) -> int:
    return int(session.scalar(select(func.count()).select_from(Order)) or 0)
