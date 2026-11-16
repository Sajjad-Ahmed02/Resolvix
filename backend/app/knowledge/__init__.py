"""Local knowledge ingestion and semantic retrieval."""

from app.knowledge.chunking import TextChunk, TextChunker, chunk_faq
from app.knowledge.embeddings import (
    DEFAULT_EMBEDDING_MODEL,
    EMBEDDING_DIMENSION,
    Embedder,
    EmbeddingConfigurationError,
    EmbeddingError,
    EmbeddingInputTooLongError,
    SentenceTransformerEmbedder,
    get_embedder,
)
from app.knowledge.grounding import build_context_prompt
from app.knowledge.ingestion import IngestionReport, KnowledgeIngestor
from app.knowledge.retrieval import KnowledgeRetriever, RetrievedChunk

__all__ = [
    "DEFAULT_EMBEDDING_MODEL",
    "EMBEDDING_DIMENSION",
    "Embedder",
    "EmbeddingConfigurationError",
    "EmbeddingError",
    "EmbeddingInputTooLongError",
    "IngestionReport",
    "KnowledgeIngestor",
    "KnowledgeRetriever",
    "RetrievedChunk",
    "SentenceTransformerEmbedder",
    "TextChunk",
    "TextChunker",
    "build_context_prompt",
    "chunk_faq",
    "get_embedder",
]
