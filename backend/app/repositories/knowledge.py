from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.orm import Session

from app.models import FAQ, KnowledgeChunk, KnowledgeDocument


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


def list_chunks_for_faq(
    session: Session,
    faq_id: UUID,
) -> list[KnowledgeChunk]:
    return list(
        session.scalars(
            select(KnowledgeChunk)
            .where(KnowledgeChunk.faq_id == faq_id)
            .order_by(KnowledgeChunk.chunk_index)
        ).all()
    )


def list_chunks_for_document(
    session: Session,
    document_id: UUID,
) -> list[KnowledgeChunk]:
    return list(
        session.scalars(
            select(KnowledgeChunk)
            .where(KnowledgeChunk.document_id == document_id)
            .order_by(KnowledgeChunk.chunk_index)
        ).all()
    )


def delete_chunks_for_faq(session: Session, faq_id: UUID) -> int:
    result = session.execute(
        delete(KnowledgeChunk).where(KnowledgeChunk.faq_id == faq_id)
    )
    return result.rowcount or 0


def delete_chunks_for_document(session: Session, document_id: UUID) -> int:
    result = session.execute(
        delete(KnowledgeChunk).where(
            KnowledgeChunk.document_id == document_id
        )
    )
    return result.rowcount or 0


def replace_faq_chunks(
    session: Session,
    faq_id: UUID,
    *,
    contents: Sequence[str],
    embeddings: Sequence[Sequence[float]],
    embedding_model: str,
    source_updated_at: datetime,
) -> list[KnowledgeChunk]:
    """Atomically replace every chunk for one FAQ.

    Callers generate embeddings before calling this function. The delete and
    inserts share one transaction, so a database failure restores the previous
    chunks instead of leaving a partial index.
    """
    if len(contents) != len(embeddings):
        raise ValueError("contents and embeddings must have equal length.")

    delete_chunks_for_faq(session, faq_id)
    chunks = [
        KnowledgeChunk(
            faq_id=faq_id,
            chunk_index=index,
            content=content,
            embedding=list(embedding),
            embedding_model=embedding_model,
            source_updated_at=source_updated_at,
        )
        for index, (content, embedding) in enumerate(
            zip(contents, embeddings, strict=True)
        )
    ]
    session.add_all(chunks)
    session.flush()
    return chunks


def replace_document_chunks(
    session: Session,
    document_id: UUID,
    *,
    contents: Sequence[str],
    embeddings: Sequence[Sequence[float]],
    embedding_model: str,
    source_updated_at: datetime,
) -> list[KnowledgeChunk]:
    """Atomically replace every chunk for one knowledge document."""
    if len(contents) != len(embeddings):
        raise ValueError("contents and embeddings must have equal length.")

    delete_chunks_for_document(session, document_id)
    chunks = [
        KnowledgeChunk(
            document_id=document_id,
            chunk_index=index,
            content=content,
            embedding=list(embedding),
            embedding_model=embedding_model,
            source_updated_at=source_updated_at,
        )
        for index, (content, embedding) in enumerate(
            zip(contents, embeddings, strict=True)
        )
    ]
    session.add_all(chunks)
    session.flush()
    return chunks


def mark_chunks_current(
    session: Session,
    chunks: Sequence[KnowledgeChunk],
    *,
    source_updated_at: datetime,
) -> None:
    """Refresh the source version when chunk text and model did not change."""
    for chunk in chunks:
        chunk.source_updated_at = source_updated_at
    session.flush()


def search_chunks(
    session: Session,
    embedding: Sequence[float],
    *,
    limit: int,
    max_distance: float | None = None,
    embedding_model: str | None = None,
) -> list[tuple[KnowledgeChunk, FAQ | None, KnowledgeDocument | None, float]]:
    """Return nearest active chunks using pgvector cosine distance.

    Inactive sources, chunks built from an older source revision, and chunks
    produced by a different embedding model are excluded. The outer joins keep
    FAQ and document metadata available for citations without a second query.
    """
    distance = KnowledgeChunk.embedding.cosine_distance(list(embedding)).label(
        "distance"
    )
    source_is_current = or_(
        and_(
            KnowledgeChunk.faq_id.is_not(None),
            FAQ.is_active.is_(True),
            KnowledgeChunk.source_updated_at.is_not(None),
            KnowledgeChunk.source_updated_at == FAQ.updated_at,
        ),
        and_(
            KnowledgeChunk.document_id.is_not(None),
            KnowledgeDocument.is_active.is_(True),
            KnowledgeChunk.source_updated_at.is_not(None),
            KnowledgeChunk.source_updated_at == KnowledgeDocument.updated_at,
        ),
    )

    statement = (
        select(
            KnowledgeChunk,
            FAQ,
            KnowledgeDocument,
            distance,
        )
        .outerjoin(FAQ, KnowledgeChunk.faq_id == FAQ.id)
        .outerjoin(
            KnowledgeDocument,
            KnowledgeChunk.document_id == KnowledgeDocument.id,
        )
        .where(source_is_current)
        .order_by(distance)
        .limit(limit)
    )
    if max_distance is not None:
        statement = statement.where(distance <= max_distance)
    if embedding_model is not None:
        statement = statement.where(
            KnowledgeChunk.embedding_model == embedding_model
        )

    return [
        (row[0], row[1], row[2], float(row[3]))
        for row in session.execute(statement).all()
    ]
