from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.knowledge.ingestion import (
    IngestionReport,
    KnowledgeIngestor,
    SourceSyncResult,
)
from app.models import FAQ, KnowledgeDocument
from app.repositories import knowledge


def list_faqs(
    session: Session,
    *,
    active_only: bool = True,
) -> list[FAQ]:
    """Return FAQs. Admin callers may include inactive sources."""
    return knowledge.list_faqs(session, active_only=active_only)


def get_faq(session: Session, faq_id: UUID) -> FAQ | None:
    """Return an FAQ even when it is inactive, for administrator editing."""
    return knowledge.get_faq(session, faq_id, active_only=False)


def list_documents(
    session: Session,
    *,
    active_only: bool = True,
) -> list[KnowledgeDocument]:
    """Return knowledge documents. Admin callers may include inactive sources."""
    return knowledge.list_documents(session, active_only=active_only)


def get_document(
    session: Session,
    document_id: UUID,
) -> KnowledgeDocument | None:
    """Return a document even when inactive, for administrator editing."""
    return knowledge.get_document(
        session,
        document_id,
        active_only=False,
    )


def _sync_result_to_indexing(result: SourceSyncResult):
    from app.schemas.admin import IndexingResult

    return IndexingResult(
        status=result.action,
        chunks=result.chunks,
        error=result.error,
    )


def indexing_result(result: SourceSyncResult):
    """Convert an ingestion result to the administrator response schema."""
    return _sync_result_to_indexing(result)


async def create_faq(
    session: Session,
    *,
    ingestor: KnowledgeIngestor,
    question: str,
    answer: str,
    category: str,
    is_active: bool,
) -> tuple[FAQ, SourceSyncResult]:
    faq = FAQ(
        question=question,
        answer=answer,
        category=category,
        is_active=is_active,
    )
    session.add(faq)
    session.commit()
    session.refresh(faq)

    result = await ingestor.sync_faq(session, faq)
    session.refresh(faq)
    return faq, result


async def update_faq(
    session: Session,
    faq: FAQ,
    *,
    ingestor: KnowledgeIngestor,
    question: str,
    answer: str,
    category: str,
    is_active: bool,
) -> tuple[FAQ, SourceSyncResult]:
    faq.question = question
    faq.answer = answer
    faq.category = category
    faq.is_active = is_active
    session.commit()
    session.refresh(faq)

    result = await ingestor.sync_faq(session, faq)
    session.refresh(faq)
    return faq, result


async def reindex_faq(
    session: Session,
    faq: FAQ,
    *,
    ingestor: KnowledgeIngestor,
) -> SourceSyncResult:
    return await ingestor.sync_faq(session, faq)


def delete_faq(session: Session, faq: FAQ) -> None:
    """Delete the FAQ. Its chunks are removed by the database cascade."""
    session.delete(faq)
    session.commit()


async def create_document(
    session: Session,
    *,
    ingestor: KnowledgeIngestor,
    title: str,
    content: str,
    category: str,
    is_active: bool,
) -> tuple[KnowledgeDocument, SourceSyncResult]:
    document = KnowledgeDocument(
        title=title,
        content=content,
        category=category,
        is_active=is_active,
    )
    session.add(document)
    session.commit()
    session.refresh(document)

    result = await ingestor.sync_document(session, document)
    session.refresh(document)
    return document, result


async def update_document(
    session: Session,
    document: KnowledgeDocument,
    *,
    ingestor: KnowledgeIngestor,
    title: str,
    content: str,
    category: str,
    is_active: bool,
) -> tuple[KnowledgeDocument, SourceSyncResult]:
    document.title = title
    document.content = content
    document.category = category
    document.is_active = is_active
    session.commit()
    session.refresh(document)

    result = await ingestor.sync_document(session, document)
    session.refresh(document)
    return document, result


async def reindex_document(
    session: Session,
    document: KnowledgeDocument,
    *,
    ingestor: KnowledgeIngestor,
) -> SourceSyncResult:
    return await ingestor.sync_document(session, document)


def delete_document(session: Session, document: KnowledgeDocument) -> None:
    """Delete the document. Its chunks are removed by the database cascade."""
    session.delete(document)
    session.commit()


async def reindex_all(
    session: Session,
    *,
    ingestor: KnowledgeIngestor,
) -> IngestionReport:
    """Synchronize every FAQ and document, reporting per-source failures."""
    return await ingestor.sync_all(session)
