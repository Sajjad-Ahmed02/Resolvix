from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

OrderStatus = Literal["pending", "confirmed", "processing", "completed", "cancelled"]
ShippingStatus = Literal[
    "not_shipped",
    "in_transit",
    "out_for_delivery",
    "delivered",
]


class OrderItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_name: str
    quantity: int
    unit_price: Decimal


class OrderRead(BaseModel):
    """An order belonging to the authenticated customer."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    order_number: str
    order_date: datetime
    status: OrderStatus
    shipping_status: ShippingStatus | None
    total_amount: Decimal
    estimated_delivery: date | None
    created_at: datetime
    updated_at: datetime
    items: list[OrderItemRead]


class AdminOrderUser(BaseModel):
    """Minimal customer identity for the administrator order view."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    email: str


class AdminOrderRead(BaseModel):
    """Full order view for administrator management."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    user: AdminOrderUser
    order_number: str
    order_date: datetime
    status: OrderStatus
    shipping_status: ShippingStatus | None
    total_amount: Decimal
    estimated_delivery: date | None
    created_at: datetime
    updated_at: datetime
    items: list[OrderItemRead]
