from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.conversation import ConversationRead, MessageRead
from app.schemas.knowledge import FAQRead, KnowledgeDocumentRead
from app.schemas.order import OrderStatus, ShippingStatus


IndexingStatus = Literal["indexed", "refreshed", "skipped", "deleted", "failed"]

_ORDER_NUMBER_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9-]{2,29}$")


def _normalize_text(value: str) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError("Value must not be blank")
    return normalized


class IndexingResult(BaseModel):
    """Outcome of synchronizing one source with the vector index."""

    status: IndexingStatus
    chunks: int = 0
    error: str | None = None


class FAQWrite(BaseModel):
    """Administrator-editable FAQ fields."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=3, max_length=2000)
    answer: str = Field(min_length=3, max_length=20000)
    category: str = Field(min_length=1, max_length=100)
    is_active: bool = True

    @field_validator("question", "answer", "category")
    @classmethod
    def normalize_fields(cls, value: str) -> str:
        return _normalize_text(value)


class FAQMutationResponse(BaseModel):
    faq: FAQRead
    indexing: IndexingResult


class KnowledgeDocumentWrite(BaseModel):
    """Administrator-editable knowledge document fields."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=3, max_length=255)
    content: str = Field(min_length=3, max_length=200000)
    category: str = Field(min_length=1, max_length=100)
    is_active: bool = True

    @field_validator("title", "content", "category")
    @classmethod
    def normalize_fields(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Value must not be blank")
        return value.strip()


class KnowledgeDocumentMutationResponse(BaseModel):
    document: KnowledgeDocumentRead
    indexing: IndexingResult


class SourceIndexingResult(IndexingResult):
    source_type: Literal["faq", "document"]
    source_id: UUID
    title: str


class KnowledgeReindexResponse(BaseModel):
    summary: dict[str, int]
    results: list[SourceIndexingResult]


class AdminConversationRead(BaseModel):
    id: UUID
    user_id: UUID
    customer_name: str
    customer_email: str
    title: str | None
    message_count: int
    created_at: datetime
    updated_at: datetime


class AdminConversationDetail(AdminConversationRead):
    messages: list[MessageRead]


class AdminAITestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=8000)
    # Reuse an admin-owned conversation to test multi-turn follow-ups.
    conversation_id: UUID | None = None

    @field_validator("message")
    @classmethod
    def normalize_message(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Message must not be empty")
        return normalized


class AdminAITestResponse(BaseModel):
    conversation: ConversationRead
    user_message: MessageRead
    assistant_message: MessageRead
    conversation_created: bool
    latency_ms: float


class AdminStats(BaseModel):
    users: int
    customers: int
    orders: int
    conversations: int
    faqs: int
    active_faqs: int
    documents: int
    active_documents: int


class OrderItemWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_name: str = Field(min_length=1, max_length=255)
    quantity: int = Field(ge=1, le=10000)
    unit_price: Decimal = Field(ge=0, le=Decimal("9999999.99"))

    @field_validator("product_name")
    @classmethod
    def normalize_product_name(cls, value: str) -> str:
        return _normalize_text(value)


class AdminOrderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: UUID
    order_number: str = Field(min_length=3, max_length=30)
    order_date: datetime | None = None
    status: OrderStatus = "pending"
    shipping_status: ShippingStatus | None = "not_shipped"
    estimated_delivery: date | None = None
    items: list[OrderItemWrite] = Field(min_length=1, max_length=100)

    @field_validator("order_number")
    @classmethod
    def normalize_order_number(cls, value: str) -> str:
        normalized = " ".join(value.split()).upper()
        if not _ORDER_NUMBER_PATTERN.fullmatch(normalized):
            raise ValueError(
                "Order numbers must contain only letters, digits, and hyphens"
            )
        return normalized


class AdminOrderUpdate(BaseModel):
    """Partial update for administrator order fields."""

    model_config = ConfigDict(extra="forbid")

    status: OrderStatus | None = None
    shipping_status: ShippingStatus | None = None
    order_date: datetime | None = None
    estimated_delivery: date | None = None


class AdminOrderItemUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_name: str | None = Field(default=None, min_length=1, max_length=255)
    quantity: int | None = Field(default=None, ge=1, le=10000)
    unit_price: Decimal | None = Field(
        default=None,
        ge=0,
        le=Decimal("9999999.99"),
    )

    @field_validator("product_name")
    @classmethod
    def normalize_product_name(cls, value: str | None) -> str | None:
        return _normalize_text(value) if value is not None else None
