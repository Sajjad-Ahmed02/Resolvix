from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.order_item import OrderItem
    from app.models.user import User


ORDER_STATUSES = (
    "pending",
    "confirmed",
    "processing",
    "completed",
    "cancelled",
)
SHIPPING_STATUSES = (
    "not_shipped",
    "in_transit",
    "out_for_delivery",
    "delivered",
)


class Order(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "orders"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        # Financial records are retained if a user is removed. The
        # application must delete orders explicitly before deleting a user.
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    order_number: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        unique=True,
    )
    order_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    shipping_status: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )
    total_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    estimated_delivery: Mapped[date | None] = mapped_column(Date, nullable=True)

    user: Mapped["User"] = relationship(back_populates="orders")
    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        CheckConstraint(
            "char_length(btrim(order_number)) > 0",
            name="order_number_not_blank",
        ),
        CheckConstraint(
            "status IN ('pending', 'confirmed', 'processing', 'completed', 'cancelled')",
            name="status",
        ),
        CheckConstraint(
            "shipping_status IS NULL OR shipping_status IN "
            "('not_shipped', 'in_transit', 'out_for_delivery', 'delivered')",
            name="shipping_status",
        ),
        CheckConstraint("total_amount >= 0", name="total_amount_non_negative"),
        Index("ix_orders_user_id", "user_id"),
    )
