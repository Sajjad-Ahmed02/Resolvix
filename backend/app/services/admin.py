from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import Order, OrderItem, User
from app.models.faq import FAQ
from app.models.knowledge_document import KnowledgeDocument
from app.repositories import conversations, knowledge, orders, users
from app.schemas.admin import (
    AdminStats,
    OrderItemWrite,
)


class AdminNotFoundError(LookupError):
    """A referenced administrator resource does not exist."""


class AdminConflictError(ValueError):
    """The requested change conflicts with existing data."""


class AdminValidationError(ValueError):
    """The requested values are not valid for this operation."""


ZERO = Decimal("0.00")


def list_users(session: Session) -> list[User]:
    """Administrator-only user listing. Schemas exclude password hashes."""
    return users.list_all(session)


def list_orders(session: Session) -> list[Order]:
    """Administrator-only order listing with owners and line items."""
    return orders.list_all(session)


def get_order(session: Session, order_id: UUID) -> Order:
    order = orders.get_by_id(session, order_id)
    if order is None:
        raise AdminNotFoundError("Order not found")
    return order


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


def _recalculate_total(order: Order) -> None:
    order.total_amount = _money(
        sum(
            (
                item.unit_price * item.quantity
                for item in order.items
            ),
            ZERO,
        )
    )


def create_order(
    session: Session,
    *,
    user_id: UUID,
    order_number: str,
    order_date: datetime | None,
    status: str,
    shipping_status: str | None,
    estimated_delivery: date | None,
    items: list[OrderItemWrite],
) -> Order:
    user = users.get_by_id(session, user_id)
    if user is None:
        raise AdminNotFoundError("Customer not found")
    if orders.get_by_number(session, order_number, with_items=False) is not None:
        raise AdminConflictError("An order with this number already exists")

    order = Order(
        user_id=user.id,
        order_number=order_number,
        order_date=order_date or datetime.now(timezone.utc),
        status=status,
        shipping_status=shipping_status,
        total_amount=ZERO,
        estimated_delivery=estimated_delivery,
    )
    order.items = [
        OrderItem(
            product_name=item.product_name,
            quantity=item.quantity,
            unit_price=_money(item.unit_price),
        )
        for item in items
    ]
    _recalculate_total(order)
    session.add(order)
    session.commit()
    session.refresh(order)
    return get_order(session, order.id)


def update_order(
    session: Session,
    order_id: UUID,
    *,
    status: str | None = None,
    shipping_status: str | None = None,
    update_shipping: bool = False,
    order_date: datetime | None = None,
    estimated_delivery: date | None = None,
    update_estimated_delivery: bool = False,
) -> Order:
    order = get_order(session, order_id)

    if status is not None:
        order.status = status
    if update_shipping:
        order.shipping_status = shipping_status
    if order_date is not None:
        order.order_date = order_date
    if update_estimated_delivery:
        order.estimated_delivery = estimated_delivery

    session.commit()
    session.refresh(order)
    return get_order(session, order.id)


def add_order_item(
    session: Session,
    order_id: UUID,
    *,
    item: OrderItemWrite,
) -> Order:
    order = get_order(session, order_id)
    order.items.append(
        OrderItem(
            product_name=item.product_name,
            quantity=item.quantity,
            unit_price=_money(item.unit_price),
        )
    )
    _recalculate_total(order)
    session.commit()
    session.refresh(order)
    return get_order(session, order.id)


def update_order_item(
    session: Session,
    order_id: UUID,
    item_id: UUID,
    *,
    product_name: str | None = None,
    quantity: int | None = None,
    unit_price: Decimal | None = None,
) -> Order:
    order = get_order(session, order_id)
    item = orders.get_item(session, order_id, item_id)
    if item is None:
        raise AdminNotFoundError("Order item not found")

    if product_name is not None:
        item.product_name = product_name
    if quantity is not None:
        item.quantity = quantity
    if unit_price is not None:
        item.unit_price = _money(unit_price)

    _recalculate_total(order)
    session.commit()
    session.refresh(order)
    return get_order(session, order.id)


def delete_order_item(
    session: Session,
    order_id: UUID,
    item_id: UUID,
) -> Order:
    order = get_order(session, order_id)
    item = orders.get_item(session, order_id, item_id)
    if item is None:
        raise AdminNotFoundError("Order item not found")

    order.items.remove(item)
    _recalculate_total(order)
    session.commit()
    session.refresh(order)
    return get_order(session, order.id)


def list_conversations(
    session: Session,
) -> list[tuple]:
    """Return every conversation with its owner and message count."""
    return conversations.list_all_with_counts(session)


def get_conversation(session: Session, conversation_id: UUID):
    conversation = conversations.get_with_user(session, conversation_id)
    if conversation is None:
        raise AdminNotFoundError("Conversation not found")
    return conversation


def stats(session: Session) -> AdminStats:
    return AdminStats(
        users=users.count(session),
        customers=users.count(session, role="customer"),
        orders=orders.count(session),
        conversations=conversations.count(session),
        faqs=knowledge.count_faqs(session, active_only=False),
        active_faqs=knowledge.count_faqs(session, active_only=True),
        documents=knowledge.count_documents(session, active_only=False),
        active_documents=knowledge.count_documents(session, active_only=True),
    )


def knowledge_source_counts(
    session: Session,
) -> tuple[list[FAQ], list[KnowledgeDocument]]:
    """Convenience helper used by administrator knowledge listings."""
    return (
        knowledge.list_faqs(session, active_only=False),
        knowledge.list_documents(session, active_only=False),
    )
