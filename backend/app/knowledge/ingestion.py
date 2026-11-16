"""Knowledge ingestion: chunk sources, embed them, and synchronize pgvector.

Ingestion is independent of FastAPI routes and of the LLM provider. The CLI
(``scripts/index_knowledge.py``) and tests call this module directly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

from sqlalchemy.orm import Session

from app.knowledge.chunking import (
    ChunkingError,
    TextChunk,
    TextChunker,
    chunk_faq,
)
from app.knowledge.embeddings import Embedder, EmbeddingError
from app.models import FAQ, KnowledgeDocument
from app.repositories import knowledge

logger = logging.getLogger(__name__)

SourceType = Literal["faq", "document"]
SourceAction = Literal["indexed", "refreshed", "skipped", "deleted", "failed"]


@dataclass(frozen=True, slots=True)
class SourceSyncResult:
    """Outcome of synchronizing one FAQ or knowledge document."""

    source_type: SourceType
    source_id: UUID
    title: str
    action: SourceAction
    chunks: int = 0
    error: str | None = None


@dataclass(slots=True)
class IngestionReport:
    """Aggregate result used by the CLI and tests."""

    results: list[SourceSyncResult] = field(default_factory=list)

    def add(self, result: SourceSyncResult) -> None:
        self.results.append(result)

    @property
    def indexed(self) -> int:
        return sum(result.action == "indexed" for result in self.results)

    @property
    def refreshed(self) -> int:
        return sum(result.action == "refreshed" for result in self.results)

    @property
    def skipped(self) -> int:
        return sum(result.action == "skipped" for result in self.results)

    @property
    def deleted(self) -> int:
        return sum(result.action == "deleted" for result in self.results)

    @property
    def failed(self) -> int:
        return sum(result.action == "failed" for result in self.results)

    @property
    def chunks_written(self) -> int:
        return sum(
            result.chunks
            for result in self.results
            if result.action == "indexed"
        )

    def summary(self) -> dict[str, int]:
        return {
            "sources": len(self.results),
            "indexed": self.indexed,
            "refreshed": self.refreshed,
            "skipped": self.skipped,
            "deleted": self.deleted,
            "failed": self.failed,
            "chunks_written": self.chunks_written,
        }


class KnowledgeIngestor:
    """Synchronize FAQ and document chunks with the configured embedder."""

    def __init__(
        self,
        embedder: Embedder,
        *,
        max_tokens: int,
        overlap_tokens: int,
        force: bool = False,
    ) -> None:
        self.embedder = embedder
        self.force = force

        token_limit = embedder.reusable_token_limit()
        if max_tokens > token_limit:
            raise ChunkingError(
                f"KNOWLEDGE_CHUNK_MAX_TOKENS={max_tokens} exceeds the "
                f"{token_limit} content tokens available in "
                f"'{embedder.model_name}' (max_seq_length="
                f"{embedder.max_seq_length}). Lower the chunk size so text is "
                "not silently truncated."
            )

        self.chunker = TextChunker(
            embedder,
            max_tokens=max_tokens,
            overlap_tokens=overlap_tokens,
        )

    async def sync_all(self, session: Session) -> IngestionReport:
        """Synchronize every FAQ and document, including inactive sources."""
        report = IngestionReport()

        for faq in knowledge.list_faqs(session, active_only=False):
            report.add(await self.sync_faq(session, faq))

        for document in knowledge.list_documents(session, active_only=False):
            report.add(await self.sync_document(session, document))

        return report

    async def sync_faq(
        self,
        session: Session,
        faq: FAQ,
    ) -> SourceSyncResult:
        if not faq.is_active:
            return self._remove_inactive_faq(session, faq)

        try:
            desired = chunk_faq(faq.question, faq.answer, self.chunker)
            existing = knowledge.list_chunks_for_faq(session, faq.id)
            state = self._compare(existing, desired, faq.updated_at)
            if not self.force and state == "current":
                return self._result(faq, "skipped", len(existing))
            if not self.force and state == "version_only":
                knowledge.mark_chunks_current(
                    session,
                    existing,
                    source_updated_at=faq.updated_at,
                )
                session.commit()
                return self._result(faq, "refreshed", len(existing))

            embeddings = await self._embed_chunks(desired)
            knowledge.replace_faq_chunks(
                session,
                faq.id,
                contents=[chunk.content for chunk in desired],
                embeddings=embeddings,
                embedding_model=self.embedder.model_name,
                source_updated_at=faq.updated_at,
            )
            session.commit()
            return self._result(faq, "indexed", len(desired))
        except Exception as error:
            session.rollback()
            logger.exception("FAQ %s re-index failed", faq.id)
            return self._failed(faq, error)

    async def sync_document(
        self,
        session: Session,
        document: KnowledgeDocument,
    ) -> SourceSyncResult:
        if not document.is_active:
            return self._remove_inactive_document(session, document)

        try:
            desired = self.chunker.split(document.content)
            existing = knowledge.list_chunks_for_document(session, document.id)
            state = self._compare(existing, desired, document.updated_at)
            if not self.force and state == "current":
                return self._result(document, "skipped", len(existing))
            if not self.force and state == "version_only":
                knowledge.mark_chunks_current(
                    session,
                    existing,
                    source_updated_at=document.updated_at,
                )
                session.commit()
                return self._result(document, "refreshed", len(existing))

            embeddings = await self._embed_chunks(desired)
            knowledge.replace_document_chunks(
                session,
                document.id,
                contents=[chunk.content for chunk in desired],
                embeddings=embeddings,
                embedding_model=self.embedder.model_name,
                source_updated_at=document.updated_at,
            )
            session.commit()
            return self._result(document, "indexed", len(desired))
        except Exception as error:
            session.rollback()
            logger.exception("Document %s re-index failed", document.id)
            return self._failed(document, error)

    def _compare(
        self,
        existing,
        desired: list[TextChunk],
        source_updated_at,
    ) -> Literal["current", "version_only", "stale"]:
        if not existing or len(existing) != len(desired):
            return "stale"

        contents = [chunk.content for chunk in existing]
        if contents != [chunk.content for chunk in desired]:
            return "stale"
        if any(
            chunk.embedding_model != self.embedder.model_name
            for chunk in existing
        ):
            return "stale"
        if any(
            chunk.source_updated_at != source_updated_at
            for chunk in existing
        ):
            return "version_only"
        return "current"

    async def _embed_chunks(
        self,
        chunks: list[TextChunk],
    ) -> list[list[float]]:
        embeddings = await self.embedder.embed_documents(
            [chunk.content for chunk in chunks]
        )
        if len(embeddings) != len(chunks):
            raise EmbeddingError(
                "Embedding model returned a different number of vectors than "
                "chunks."
            )
        for vector in embeddings:
            if len(vector) != self.embedder.dimension:
                raise EmbeddingError(
                    f"Expected {self.embedder.dimension}-dimensional vectors."
                )
        return embeddings

    def _remove_inactive_faq(
        self,
        session: Session,
        faq: FAQ,
    ) -> SourceSyncResult:
        try:
            deleted = knowledge.delete_chunks_for_faq(session, faq.id)
            session.commit()
        except Exception as error:
            session.rollback()
            logger.exception("Could not remove chunks for inactive FAQ %s", faq.id)
            return self._failed(faq, error)
        action: SourceAction = "deleted" if deleted else "skipped"
        return self._result(faq, action, deleted)

    def _remove_inactive_document(
        self,
        session: Session,
        document: KnowledgeDocument,
    ) -> SourceSyncResult:
        try:
            deleted = knowledge.delete_chunks_for_document(
                session,
                document.id,
            )
            session.commit()
        except Exception as error:
            session.rollback()
            logger.exception(
                "Could not remove chunks for inactive document %s",
                document.id,
            )
            return self._failed(document, error)
        action: SourceAction = "deleted" if deleted else "skipped"
        return self._result(document, action, deleted)

    @staticmethod
    def _result(source, action: SourceAction, chunks: int) -> SourceSyncResult:
        source_type: SourceType = (
            "faq" if isinstance(source, FAQ) else "document"
        )
        title = source.question if isinstance(source, FAQ) else source.title
        return SourceSyncResult(
            source_type=source_type,
            source_id=source.id,
            title=title,
            action=action,
            chunks=chunks,
        )

    @staticmethod
    def _failed(source, error: Exception) -> SourceSyncResult:
        result = KnowledgeIngestor._result(source, "failed", 0)
        return SourceSyncResult(
            source_type=result.source_type,
            source_id=result.source_id,
            title=result.title,
            action="failed",
            chunks=0,
            error=f"{type(error).__name__}: {error}",
        )
