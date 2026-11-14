from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.faq import FAQ
    from app.models.knowledge_document import KnowledgeDocument


EMBEDDING_DIMENSION = 384
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


class KnowledgeChunk(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "knowledge_chunks"

    document_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
        nullable=True,
    )
    faq_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("faqs.id", ondelete="CASCADE"),
        nullable=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(
        Vector(EMBEDDING_DIMENSION),
        nullable=False,
    )
    embedding_model: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    document: Mapped[Optional["KnowledgeDocument"]] = relationship(
        back_populates="chunks",
    )
    faq: Mapped[Optional["FAQ"]] = relationship(back_populates="chunks")

    __table_args__ = (
        CheckConstraint(
            "(document_id IS NOT NULL) <> (faq_id IS NOT NULL)",
            name="exactly_one_source",
        ),
        CheckConstraint("chunk_index >= 0", name="chunk_index_non_negative"),
        CheckConstraint(
            "char_length(btrim(content)) > 0",
            name="content_not_blank",
        ),
        CheckConstraint(
            "char_length(btrim(embedding_model)) > 0",
            name="embedding_model_not_blank",
        ),
        Index(
            "uq_knowledge_chunks_document_id_chunk_index",
            "document_id",
            "chunk_index",
            unique=True,
            postgresql_where=text("document_id IS NOT NULL"),
        ),
        Index(
            "uq_knowledge_chunks_faq_id_chunk_index",
            "faq_id",
            "chunk_index",
            unique=True,
            postgresql_where=text("faq_id IS NOT NULL"),
        ),
        Index(
            "ix_knowledge_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )
