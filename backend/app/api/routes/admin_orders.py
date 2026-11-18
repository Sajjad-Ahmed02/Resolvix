from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import require_admin
from app.db.session import get_db
from app.schemas.admin import (
    AdminOrderCreate,
    AdminOrderItemUpdate,
    AdminOrderUpdate,
    OrderItemWrite,
)
from app.schemas.common import ErrorResponse
from app.schemas.order import AdminOrderRead
from app.services import admin as admin_service


router = APIRouter(
    prefix="/orders",
    tags=["Administration"],
    dependencies=[Depends(require_admin)],
)


def _read(order) -> AdminOrderRead:
    return AdminOrderRead.model_validate(order)


def _not_found(message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=message,
    )


def _conflict(message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=message,
    )


def _unprocessable(message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=message,
    )


@router.get(
    "",
    response_model=list[AdminOrderRead],
    summary="List all orders with customers and line items",
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "model": ErrorResponse,
            "description": "Missing, invalid, or expired credentials.",
        },
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "Administrator access required.",
        },
    },
)
def list_orders(session: Session = Depends(get_db)) -> list[AdminOrderRead]:
    return [
        _read(order)
        for order in admin_service.list_orders(session)
    ]


@router.post(
    "",
    response_model=AdminOrderRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a synthetic order with line items",
    responses={
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "Customer not found.",
        },
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
            "description": "Order number already exists.",
        },
    },
)
def create_order(
    payload: AdminOrderCreate,
    session: Session = Depends(get_db),
) -> AdminOrderRead:
    try:
        order = admin_service.create_order(
            session,
            user_id=payload.user_id,
            order_number=payload.order_number,
            order_date=payload.order_date,
            status=payload.status,
            shipping_status=payload.shipping_status,
            estimated_delivery=payload.estimated_delivery,
            items=payload.items,
        )
    except admin_service.AdminNotFoundError as error:
        raise _not_found(str(error)) from None
    except admin_service.AdminConflictError as error:
        raise _conflict(str(error)) from None
    return _read(order)


@router.get(
    "/{order_id}",
    response_model=AdminOrderRead,
    summary="Read one order with line items",
    responses={
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "Order not found.",
        }
    },
)
def get_order(
    order_id: UUID,
    session: Session = Depends(get_db),
) -> AdminOrderRead:
    try:
        order = admin_service.get_order(session, order_id)
    except admin_service.AdminNotFoundError as error:
        raise _not_found(str(error)) from None
    return _read(order)


@router.patch(
    "/{order_id}",
    response_model=AdminOrderRead,
    summary="Update order status, shipping status, or dates",
    responses={
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "Order not found.",
        }
    },
)
def update_order(
    order_id: UUID,
    payload: AdminOrderUpdate,
    session: Session = Depends(get_db),
) -> AdminOrderRead:
    fields = payload.model_fields_set
    if "status" in fields and payload.status is None:
        raise _unprocessable("Order status cannot be empty")
    if "order_date" in fields and payload.order_date is None:
        raise _unprocessable("Order date cannot be empty")

    try:
        order = admin_service.update_order(
            session,
            order_id,
            status=payload.status,
            shipping_status=payload.shipping_status,
            update_shipping="shipping_status" in fields,
            order_date=payload.order_date,
            estimated_delivery=payload.estimated_delivery,
            update_estimated_delivery="estimated_delivery" in fields,
        )
    except admin_service.AdminNotFoundError as error:
        raise _not_found(str(error)) from None
    return _read(order)


@router.post(
    "/{order_id}/items",
    response_model=AdminOrderRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a line item and recalculate the order total",
    responses={
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "Order not found.",
        }
    },
)
def add_order_item(
    order_id: UUID,
    payload: OrderItemWrite,
    session: Session = Depends(get_db),
) -> AdminOrderRead:
    try:
        order = admin_service.add_order_item(
            session,
            order_id,
            item=payload,
        )
    except admin_service.AdminNotFoundError as error:
        raise _not_found(str(error)) from None
    return _read(order)


@router.patch(
    "/{order_id}/items/{item_id}",
    response_model=AdminOrderRead,
    summary="Update a line item and recalculate the order total",
    responses={
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "Order or line item not found.",
        }
    },
)
def update_order_item(
    order_id: UUID,
    item_id: UUID,
    payload: AdminOrderItemUpdate,
    session: Session = Depends(get_db),
) -> AdminOrderRead:
    try:
        order = admin_service.update_order_item(
            session,
            order_id,
            item_id,
            product_name=payload.product_name,
            quantity=payload.quantity,
            unit_price=payload.unit_price,
        )
    except admin_service.AdminNotFoundError as error:
        raise _not_found(str(error)) from None
    return _read(order)


@router.delete(
    "/{order_id}/items/{item_id}",
    response_model=AdminOrderRead,
    summary="Delete a line item and recalculate the order total",
    responses={
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "Order or line item not found.",
        }
    },
)
def delete_order_item(
    order_id: UUID,
    item_id: UUID,
    session: Session = Depends(get_db),
) -> AdminOrderRead:
    try:
        order = admin_service.delete_order_item(
            session,
            order_id,
            item_id,
        )
    except admin_service.AdminNotFoundError as error:
        raise _not_found(str(error)) from None
    return _read(order)
