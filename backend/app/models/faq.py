from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.knowledge_chunk import KnowledgeChunk


class FAQ(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "faqs"

    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="true",
    )

    chunks: Mapped[list["KnowledgeChunk"]] = relationship(
        back_populates="faq",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        CheckConstraint(
            "char_length(btrim(question)) > 0",
            name="question_not_blank",
        ),
        CheckConstraint(
            "char_length(btrim(answer)) > 0",
            name="answer_not_blank",
        ),
        CheckConstraint(
            "char_length(btrim(category)) > 0",
            name="category_not_blank",
        ),
        Index("ix_faqs_category", "category"),
    )
