from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import FAQ, KnowledgeDocument
from app.repositories import knowledge


def list_faqs(
    session: Session,
    *,
    active_only: bool = True,
) -> list[FAQ]:
    """Return FAQs. Admin callers may include inactive sources."""
    return knowledge.list_faqs(session, active_only=active_only)


def list_documents(
    session: Session,
    *,
    active_only: bool = True,
) -> list[KnowledgeDocument]:
    """Return knowledge documents. Admin callers may include inactive sources."""
    return knowledge.list_documents(session, active_only=active_only)
