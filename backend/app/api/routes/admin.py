from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.dependencies import require_admin
from app.api.routes import (
    admin_ai,
    admin_conversations,
    admin_knowledge,
    admin_orders,
)
from app.db.session import get_db
from app.schemas.admin import AdminStats
from app.schemas.common import ErrorResponse
from app.schemas.user import UserRead
from app.services import admin as admin_service


router = APIRouter(
    prefix="/admin",
    tags=["Administration"],
    dependencies=[Depends(require_admin)],
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "model": ErrorResponse,
            "description": "Missing, invalid, or expired credentials.",
        },
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The authenticated user is not an administrator.",
        },
    },
)


@router.get(
    "/users",
    response_model=list[UserRead],
    summary="List all users (admin only)",
)
def list_users(session: Session = Depends(get_db)) -> list[UserRead]:
    return admin_service.list_users(session)


@router.get(
    "/stats",
    response_model=AdminStats,
    summary="Dashboard counts for the administrator overview",
)
def read_stats(session: Session = Depends(get_db)) -> AdminStats:
    return admin_service.stats(session)


router.include_router(admin_knowledge.router)
router.include_router(admin_orders.router)
router.include_router(admin_conversations.router)
router.include_router(admin_ai.router)
