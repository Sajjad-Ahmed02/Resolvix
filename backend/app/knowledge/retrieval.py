"""Semantic retrieval over pgvector knowledge chunks."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy.orm import Session

from app.knowledge.embeddings import Embedder
from app.repositories import knowledge

logger = logging.getLogger(__name__)

SourceType = Literal["faq", "document"]

@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    """One relevant chunk with traceable source metadata."""

    source_type: SourceType
    source_id: UUID
    title: str
    category: str
    chunk_index: int
    content: str
    distance: float

    @property
    def similarity(self) -> float:
        """Convert pgvector cosine distance to a 1.0-is-identical score."""
        return 1.0 - self.distance

    def as_metadata(self) -> dict[str, object]:
        """Return a JSON-safe citation for message metadata."""
        return {
            "source_type": self.source_type,
            "source_id": str(self.source_id),
            "title": self.title,
            "category": self.category,
            "chunk_index": self.chunk_index,
            "distance": round(self.distance, 6),
        }


class KnowledgeRetriever:
    """Embed a customer query and return the nearest active source chunks."""

    def __init__(
        self,
        embedder: Embedder,
        *,
        top_k: int = 4,
        max_distance: float | None = 0.8,
    ) -> None:
        if top_k < 1:
            raise ValueError("top_k must be positive.")
        if max_distance is not None and max_distance < 0:
            raise ValueError("max_distance must not be negative.")
        self.embedder = embedder
        self.top_k = top_k
        self.max_distance = max_distance

    async def retrieve(
        self,
        session: Session,
        query: str,
        *,
        top_k: int | None = None,
    ) -> list[RetrievedChunk]:
        normalized = query.strip()
        if not normalized:
            logger.info(
                "Knowledge retrieval skipped for a blank query",
                extra={
                    "event": "retrieval_skipped",
                    "operation": "knowledge_retrieval",
                    "result_count": 0,
                },
            )
            return []

        limit = top_k or self.top_k
        started = time.perf_counter()
        try:
            embedding = await self.embedder.embed_query(normalized)
            rows = knowledge.search_chunks(
                session,
                embedding,
                limit=limit,
                max_distance=self.max_distance,
                embedding_model=self.embedder.model_name,
            )
        except Exception as error:
            logger.exception(
                "Knowledge retrieval failed",
                extra={
                    "event": "retrieval_error",
                    "operation": "knowledge_retrieval",
                    "top_k": limit,
                    "embedding_model": self.embedder.model_name,
                    "error_type": type(error).__name__,
                    "duration_ms": round(
                        (time.perf_counter() - started) * 1000,
                        2,
                    ),
                },
            )
            raise

        results: list[RetrievedChunk] = []
        for chunk, faq, document, distance in rows:
            if faq is not None:
                results.append(
                    RetrievedChunk(
                        source_type="faq",
                        source_id=faq.id,
                        title=faq.question,
                        category=faq.category,
                        chunk_index=chunk.chunk_index,
                        content=chunk.content,
                        distance=distance,
                    )
                )
            elif document is not None:
                results.append(
                    RetrievedChunk(
                        source_type="document",
                        source_id=document.id,
                        title=document.title,
                        category=document.category,
                        chunk_index=chunk.chunk_index,
                        content=chunk.content,
                        distance=distance,
                    )
                )

        logger.info(
            "Knowledge retrieval completed",
            extra={
                "event": "retrieval_completed",
                "operation": "knowledge_retrieval",
                "top_k": limit,
                "result_count": len(results),
                "query_chars": len(normalized),
                "embedding_model": self.embedder.model_name,
                "duration_ms": round(
                    (time.perf_counter() - started) * 1000,
                    2,
                ),
            },
        )
        return results
