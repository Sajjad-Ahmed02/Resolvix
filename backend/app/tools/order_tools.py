"""Allow-listed order lookup tools for the support agent."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.ai.providers.base import ToolDefinition
from app.repositories import orders
from app.tools.base import (
    Tool,
    ToolArgumentError,
    ToolContext,
    ToolOutcome,
)

logger = logging.getLogger(__name__)

ORDER_DETAILS_TOOL_NAME = "get_order_details"

INVALID_ARGUMENTS_MESSAGE = (
    "The order number is missing or invalid. Ask the customer for the order "
    "number shown on their order confirmation."
)
ORDER_NOT_FOUND_MESSAGE = (
    "No order with that number was found for the signed-in customer. Ask the "
    "customer to check the order number."
)
DATABASE_ERROR_MESSAGE = (
    "Order information is temporarily unavailable. Ask the customer to try "
    "again in a moment."
)


class OrderDetailsArguments(BaseModel):
    """Arguments accepted from the model for the order lookup tool.

    ``authenticated_user_id`` is intentionally absent. Extra arguments are
    rejected so a model cannot attempt to supply or override the identity that
    the backend derives from the verified request.
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    order_number: str = Field(
        min_length=1,
        max_length=30,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9-]*$",
        description=(
            "The order number exactly as shown on the customer's order "
            "confirmation, for example RX-2026-1001."
        ),
    )

    @field_validator("order_number")
    @classmethod
    def normalize_order_number(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("Order number must not be blank")
        return normalized


class OrderNotFoundError(Exception):
    """The order does not exist for the authenticated customer."""


class OrderLookupUnavailableError(Exception):
    """The database could not complete the order lookup."""


def _error_outcome(code: str, message: str) -> ToolOutcome:
    return ToolOutcome(
        tool_name=ORDER_DETAILS_TOOL_NAME,
        ok=False,
        error_code=code,
        error_message=message,
    )


def _rollback_safely(context: ToolContext) -> None:
    try:
        context.session.rollback()
    except Exception:  # pragma: no cover - defensive cleanup
        logger.exception("Failed to roll back the tool database session")


def get_order_details(
    order_number: str,
    authenticated_user_id: UUID,
    *,
    session: Session,
) -> dict[str, Any]:
    """Return one authorized order and its items.

    ``authenticated_user_id`` must come from the verified request context. The
    model never supplies it. The parent order is loaded first with an
    ownership-scoped query; item rows are fetched only after that check passes.
    """
    try:
        parsed = OrderDetailsArguments.model_validate(
            {"order_number": order_number}
        )
    except ValidationError as error:
        raise ToolArgumentError(INVALID_ARGUMENTS_MESSAGE) from error

    try:
        order = orders.get_for_user_by_number(
            session,
            authenticated_user_id,
            parsed.order_number,
            with_items=False,
        )
    except SQLAlchemyError as error:
        raise OrderLookupUnavailableError from error

    if order is None:
        raise OrderNotFoundError

    # The repository query is already ownership-scoped. This explicit check is
    # defense in depth and guarantees items are never loaded before the parent
    # order has been authorized.
    if order.user_id != authenticated_user_id:
        logger.error(
            "Order ownership check failed for user %s",
            authenticated_user_id,
        )
        raise OrderNotFoundError

    try:
        items = orders.list_items_for_order(session, order.id)
    except SQLAlchemyError as error:
        raise OrderLookupUnavailableError from error

    return {
        "order_number": order.order_number,
        "status": order.status,
        "shipping_status": order.shipping_status,
        "estimated_delivery": (
            order.estimated_delivery.isoformat()
            if order.estimated_delivery is not None
            else None
        ),
        "order_date": order.order_date.isoformat(),
        "total_amount": str(order.total_amount),
        "items": [
            {
                "product_name": item.product_name,
                "quantity": item.quantity,
                "unit_price": str(item.unit_price),
            }
            for item in items
        ],
    }


class OrderDetailsTool(Tool):
    """Fetch one order and its items for the authenticated customer."""

    definition = ToolDefinition(
        name=ORDER_DETAILS_TOOL_NAME,
        description=(
            "Look up one order belonging to the signed-in customer by its "
            "order number. Returns the order status, shipping status, "
            "estimated delivery date, total amount, and line items. Use this "
            "when the customer asks about an order and provides an order "
            "number. Never provide a user id; authorization comes from the "
            "signed-in session."
        ),
        parameters=OrderDetailsArguments.model_json_schema(),
    )

    def execute(
        self,
        context: ToolContext,
        arguments: dict[str, Any],
    ) -> ToolOutcome:
        try:
            parsed = OrderDetailsArguments.model_validate(arguments)
        except ValidationError as error:
            logger.info(
                "Rejected order tool arguments for user %s: %s",
                context.user_id,
                error.error_count(),
            )
            raise ToolArgumentError(INVALID_ARGUMENTS_MESSAGE) from error

        try:
            data = get_order_details(
                parsed.order_number,
                context.user_id,
                session=context.session,
            )
        except OrderNotFoundError:
            return _error_outcome("order_not_found", ORDER_NOT_FOUND_MESSAGE)
        except OrderLookupUnavailableError:
            logger.exception(
                "Order lookup database failure for user %s",
                context.user_id,
            )
            _rollback_safely(context)
            return _error_outcome("database_error", DATABASE_ERROR_MESSAGE)
        except Exception:
            logger.exception(
                "Unexpected order lookup failure for user %s",
                context.user_id,
            )
            _rollback_safely(context)
            return _error_outcome("database_error", DATABASE_ERROR_MESSAGE)

        return ToolOutcome(
            tool_name=ORDER_DETAILS_TOOL_NAME,
            ok=True,
            data=data,
        )
