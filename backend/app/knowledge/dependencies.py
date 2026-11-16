"""FastAPI dependencies for knowledge retrieval."""

from __future__ import annotations

from app.core.config import settings
from app.knowledge.embeddings import get_embedder
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
