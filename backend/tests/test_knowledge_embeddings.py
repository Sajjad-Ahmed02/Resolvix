from __future__ import annotations

import asyncio
import math

import pytest

from app.knowledge.embeddings import (
    EMBEDDING_DIMENSION,
    SentenceTransformerEmbedder,
    EmbeddingInputTooLongError,
)


@pytest.fixture(scope="module")
def embedder() -> SentenceTransformerEmbedder:
    return SentenceTransformerEmbedder(device="cpu", batch_size=8)


def test_local_embedding_model_contract(embedder: SentenceTransformerEmbedder) -> None:
    assert embedder.model_name == "sentence-transformers/all-MiniLM-L6-v2"
    assert embedder.dimension == EMBEDDING_DIMENSION == 384
    assert embedder.max_seq_length == 256
    assert embedder.reusable_token_limit() == 254


def test_query_embeddings_have_the_database_dimension(
    embedder: SentenceTransformerEmbedder,
) -> None:
    vector = asyncio.run(embedder.embed_query("What is the return window?"))

    assert len(vector) == 384
    assert all(isinstance(value, float) for value in vector)
    norm = math.sqrt(sum(value * value for value in vector))
    assert norm == pytest.approx(1.0, abs=1e-4)


def test_document_embeddings_are_normalized_and_ordered(
    embedder: SentenceTransformerEmbedder,
) -> None:
    vectors = asyncio.run(
        embedder.embed_documents(
            [
                "Unused items can be returned within 30 days.",
                "Payments are processed by a PCI-compliant provider.",
            ]
        )
    )

    assert len(vectors) == 2
    assert all(len(vector) == 384 for vector in vectors)
    for vector in vectors:
        norm = math.sqrt(sum(value * value for value in vector))
        assert norm == pytest.approx(1.0, abs=1e-4)


def test_oversized_chunks_are_rejected_instead_of_truncated(
    embedder: SentenceTransformerEmbedder,
) -> None:
    oversized = " ".join(f"word{index}" for index in range(400))

    with pytest.raises(EmbeddingInputTooLongError, match="tokens"):
        asyncio.run(embedder.embed_documents([oversized]))


def test_long_queries_are_explicitly_trimmed(
    embedder: SentenceTransformerEmbedder,
) -> None:
    vector = asyncio.run(embedder.embed_query("word " * 400))

    assert len(vector) == 384
    assert math.isfinite(sum(vector))
