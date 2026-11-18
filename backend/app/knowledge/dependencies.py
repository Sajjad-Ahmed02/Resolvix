"""FastAPI dependencies for knowledge retrieval and ingestion."""

from __future__ import annotations

from app.core.config import settings
from app.knowledge.embeddings import get_embedder
from app.knowledge.ingestion import KnowledgeIngestor
from app.knowledge.retrieval import KnowledgeRetriever


def get_knowledge_retriever() -> KnowledgeRetriever:
    """Build a retriever backed by the process-wide local embedder.

    Construction is cheap; the sentence-transformers model loads on the first
    query and is then shared across requests.
    """
    return KnowledgeRetriever(
        get_embedder(),
        top_k=settings.RAG_TOP_K,
        max_distance=settings.RAG_MAX_DISTANCE,
    )


def get_knowledge_ingestor() -> KnowledgeIngestor:
    """Build an ingestor using the same process-wide embedder as retrieval."""
    return KnowledgeIngestor(
        get_embedder(),
        max_tokens=settings.KNOWLEDGE_CHUNK_MAX_TOKENS,
        overlap_tokens=settings.KNOWLEDGE_CHUNK_OVERLAP_TOKENS,
    )
