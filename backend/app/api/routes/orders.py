from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.db.session import get_db
from app.models import User
from app.schemas.common import ErrorResponse
from app.schemas.order import OrderRead
from app.services import orders as order_service


router = APIRouter(prefix="/orders", tags=["Orders"])


@router.get(
    "",
    response_model=list[OrderRead],
    summary="List the authenticated customer's orders",
)
def list_orders(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> list[OrderRead]:
    return order_service.list_for_user(session, current_user.id)


@router.get(
    "/{order_number}",
    response_model=OrderRead,
    summary="Read one order owned by the authenticated customer",
    responses={
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "Order does not exist or belongs to another customer.",
        }
    },
)
def get_order(
    order_number: str = Path(min_length=1, max_length=30),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> OrderRead:
    """Look up an order by number for the customer in the bearer token.

    Ownership is applied in the database query. Another customer's order
    returns 404 rather than revealing that the order number exists.
    """
    order = order_service.get_for_user(
        session,
        current_user.id,
        order_number,
    )
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found",
        )
    return order
