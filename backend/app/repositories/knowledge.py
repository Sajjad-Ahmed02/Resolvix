from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import FAQ, KnowledgeDocument


def list_faqs(session: Session, *, active_only: bool = True) -> list[FAQ]:
    """Return FAQs, optionally excluding inactive support knowledge."""
    statement = select(FAQ).order_by(FAQ.category, FAQ.question)
    if active_only:
        statement = statement.where(FAQ.is_active.is_(True))
    return list(session.scalars(statement).all())


def get_faq(
    session: Session,
    faq_id: UUID,
    *,
    active_only: bool = True,
) -> FAQ | None:
    statement = select(FAQ).where(FAQ.id == faq_id)
    if active_only:
        statement = statement.where(FAQ.is_active.is_(True))
    return session.scalar(statement)


def list_documents(
    session: Session,
    *,
    active_only: bool = True,
) -> list[KnowledgeDocument]:
    """Return knowledge documents, optionally excluding inactive sources."""
    statement = select(KnowledgeDocument).order_by(
        KnowledgeDocument.category,
        KnowledgeDocument.title,
    )
    if active_only:
        statement = statement.where(KnowledgeDocument.is_active.is_(True))
    return list(session.scalars(statement).all())


def get_document(
    session: Session,
    document_id: UUID,
    *,
    active_only: bool = True,
) -> KnowledgeDocument | None:
    statement = select(KnowledgeDocument).where(
        KnowledgeDocument.id == document_id
    )
    if active_only:
        statement = statement.where(KnowledgeDocument.is_active.is_(True))
    return session.scalar(statement)
