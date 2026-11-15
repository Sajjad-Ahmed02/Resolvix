from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.dependencies import require_admin
from app.db.session import get_db
from app.schemas.common import ErrorResponse
from app.schemas.knowledge import FAQRead, KnowledgeDocumentRead
from app.schemas.order import AdminOrderRead
from app.schemas.user import UserRead
from app.services import admin as admin_service
from app.services import knowledge as knowledge_service


router = APIRouter(
    prefix="/admin",
    tags=["Administration"],
    dependencies=[Depends(require_admin)],
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "model": ErrorResponse,
            "description": "Missing, invalid, or expired access token.",
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
    "/orders",
    response_model=list[AdminOrderRead],
    summary="List all orders (admin only)",
)
def list_orders(session: Session = Depends(get_db)) -> list[AdminOrderRead]:
    return admin_service.list_orders(session)


@router.get(
    "/knowledge/faqs",
    response_model=list[FAQRead],
    summary="List all FAQs including inactive entries (admin only)",
)
def list_faqs(session: Session = Depends(get_db)) -> list[FAQRead]:
    return knowledge_service.list_faqs(session, active_only=False)


@router.get(
    "/knowledge/documents",
    response_model=list[KnowledgeDocumentRead],
    summary=(
        "List all knowledge documents including inactive entries (admin only)"
    ),
)
def list_documents(
    session: Session = Depends(get_db),
) -> list[KnowledgeDocumentRead]:
    return knowledge_service.list_documents(session, active_only=False)
