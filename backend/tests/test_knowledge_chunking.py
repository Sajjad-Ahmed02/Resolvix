from __future__ import annotations

import pytest

from app.knowledge.chunking import (
    ChunkingError,
    TextChunker,
    chunk_faq,
    faq_text,
)


class WordTokenCounter:
    """Small deterministic tokenizer for chunking unit tests."""

    def __init__(self) -> None:
        self._vocabulary: dict[str, int] = {}
        self._tokens: list[str] = []

    def _token_id(self, token: str) -> int:
        if token not in self._vocabulary:
            self._vocabulary[token] = len(self._tokens)
            self._tokens.append(token)
        return self._vocabulary[token]

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def encode_tokens(self, text: str) -> list[int]:
        return [self._token_id(token) for token in text.split()]

    def decode_tokens(self, tokens: list[int]) -> str:
        return " ".join(self._tokens[token] for token in tokens)


def test_chunks_are_ordered_bounded_and_overlap() -> None:
    words = " ".join(f"word{index}" for index in range(60))
    chunker = TextChunker(
        WordTokenCounter(),
        max_tokens=20,
        overlap_tokens=5,
    )

    chunks = chunker.split(words)

    assert [chunk.index for chunk in chunks] == list(range(len(chunks)))
    assert all(chunk.token_count <= 20 for chunk in chunks)
    assert len(chunks) >= 3
    assert chunks[0].content.startswith("word0")
    assert chunks[-1].content.endswith("word59")

    first_words = chunks[0].content.split()
    second_words = chunks[1].content.split()
    assert first_words[-5:] == second_words[:5]


def test_sentences_are_packed_without_exceeding_the_limit() -> None:
    text = "One two three. Four five six. Seven eight nine."
    chunker = TextChunker(
        WordTokenCounter(),
        max_tokens=6,
        overlap_tokens=0,
    )

    chunks = chunker.split(text)

    assert [chunk.content for chunk in chunks] == [
        "One two three. Four five six.",
        "Seven eight nine.",
    ]
    assert all(chunk.token_count <= 6 for chunk in chunks)


def test_paragraphs_keep_their_reading_order() -> None:
    text = "First paragraph sentence.\n\nSecond paragraph sentence."
    chunker = TextChunker(
        WordTokenCounter(),
        max_tokens=5,
        overlap_tokens=0,
    )

    chunks = chunker.split(text)

    assert [chunk.content for chunk in chunks] == [
        "First paragraph sentence.",
        "Second paragraph sentence.",
    ]


def test_faqs_are_combined_into_one_retrieval_unit() -> None:
    counter = WordTokenCounter()
    chunker = TextChunker(counter, max_tokens=100, overlap_tokens=10)

    chunks = chunk_faq(
        "How long does shipping take?",
        "Standard shipping arrives in three to five business days.",
        chunker,
    )

    assert len(chunks) == 1
    assert chunks[0].content == faq_text(
        "How long does shipping take?",
        "Standard shipping arrives in three to five business days.",
    )
    assert chunks[0].content.startswith("Q: ")
    assert "\nA: " in chunks[0].content


def test_long_faqs_are_split_without_truncation() -> None:
    answer = " ".join(f"detail{index}" for index in range(40))
    chunker = TextChunker(
        WordTokenCounter(),
        max_tokens=12,
        overlap_tokens=3,
    )

    chunks = chunk_faq("Question?", answer, chunker)

    assert len(chunks) > 1
    assert all(chunk.token_count <= 12 for chunk in chunks)
    assert "detail39" in chunks[-1].content


def test_blank_input_and_invalid_configuration_are_rejected() -> None:
    assert TextChunker(WordTokenCounter()).split("   \n  ") == []

    with pytest.raises(ChunkingError):
        TextChunker(WordTokenCounter(), max_tokens=10, overlap_tokens=10)
    with pytest.raises(ChunkingError):
        TextChunker(WordTokenCounter(), max_tokens=0)
    with pytest.raises(ChunkingError):
        TextChunker(WordTokenCounter(), max_tokens=10, overlap_tokens=-1)
