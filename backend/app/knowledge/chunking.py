"""Token-aware, ordered chunking for FAQs and knowledge documents.

Chunk sizes are counted with the same tokenizer used by the embedding model.
This keeps every chunk inside the model's context window instead of relying on
silent truncation inside sentence-transformers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

DEFAULT_MAX_TOKENS = 200
DEFAULT_OVERLAP_TOKENS = 40


class ChunkingError(ValueError):
    """Invalid chunking configuration or input."""


@dataclass(frozen=True, slots=True)
class TextChunk:
    """One ordered unit ready for embedding."""

    index: int
    content: str
    token_count: int


class TokenCounter(Protocol):
    """Tokenizer operations required by :class:`TextChunker`."""

    def count_tokens(self, text: str) -> int: ...

    def encode_tokens(self, text: str) -> list[int]: ...

    def decode_tokens(self, tokens: list[int]) -> str: ...


def normalize_text(text: str) -> str:
    """Normalize line endings and whitespace without changing wording."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"[ \t]+", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def _iter_units(text: str):
    """Yield paragraphs and sentences in reading order."""
    for block in re.split(r"\n\s*\n", text):
        block = " ".join(block.split())
        if not block:
            continue
        for sentence in re.split(r"(?<=[.!?])\s+", block):
            sentence = sentence.strip()
            if sentence:
                yield sentence


class TextChunker:
    """Split text into token-bounded chunks with configurable overlap."""

    def __init__(
        self,
        counter: TokenCounter,
        *,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
    ) -> None:
        if max_tokens <= 0:
            raise ChunkingError("max_tokens must be positive.")
        if overlap_tokens < 0:
            raise ChunkingError("overlap_tokens must not be negative.")
        if overlap_tokens >= max_tokens:
            raise ChunkingError("overlap_tokens must be smaller than max_tokens.")

        self._counter = counter
        self.max_tokens = max_tokens
        self.overlap_tokens = overlap_tokens

    def count(self, text: str) -> int:
        return self._counter.count_tokens(text)

    def split(self, text: str) -> list[TextChunk]:
        """Return ordered chunks whose content never exceeds ``max_tokens``."""
        normalized = normalize_text(text)
        if not normalized:
            return []

        chunks: list[TextChunk] = []
        window: list[str] = []
        window_tokens = 0

        def flush_window() -> None:
            nonlocal window, window_tokens
            if window:
                self._append_text(chunks, " ".join(window))
            window = []
            window_tokens = 0

        for unit in _iter_units(normalized):
            unit_ids = self._counter.encode_tokens(unit)
            unit_tokens = len(unit_ids)
            if unit_tokens == 0:
                continue

            if unit_tokens > self.max_tokens:
                # A single sentence longer than the window: split its tokens
                # directly, preserving overlap between the pieces.
                flush_window()
                self._append_token_windows(chunks, unit_ids)
                continue

            if window and window_tokens + unit_tokens > self.max_tokens:
                flush_window()
                window = self._overlap_window(chunks)
                window_tokens = self.count(" ".join(window)) if window else 0
                if window and window_tokens + unit_tokens > self.max_tokens:
                    window = []
                    window_tokens = 0

            window.append(unit)
            window_tokens += unit_tokens

        flush_window()
        return chunks

    def _overlap_window(self, chunks: list[TextChunk]) -> list[str]:
        if self.overlap_tokens == 0 or not chunks:
            return []

        token_ids = self._counter.encode_tokens(chunks[-1].content)
        tail = token_ids[-self.overlap_tokens :]
        if not tail:
            return []
        text = self._counter.decode_tokens(tail).strip()
        return [text] if text else []

    def _append_text(self, chunks: list[TextChunk], text: str) -> None:
        normalized = " ".join(text.split()).strip()
        if not normalized:
            return

        token_ids = self._counter.encode_tokens(normalized)
        if len(token_ids) > self.max_tokens:
            self._append_token_windows(chunks, token_ids)
            return

        chunks.append(
            TextChunk(
                index=len(chunks),
                content=normalized,
                token_count=len(token_ids),
            )
        )

    def _append_token_windows(
        self,
        chunks: list[TextChunk],
        token_ids: list[int],
    ) -> None:
        start = 0
        total = len(token_ids)

        while start < total:
            end = min(start + self.max_tokens, total)
            content = self._counter.decode_tokens(token_ids[start:end]).strip()

            # Decoding and re-encoding can add a boundary token. Trim the
            # window instead of allowing the embedder to truncate it.
            while content and self.count(content) > self.max_tokens and end > start:
                end -= 1
                content = self._counter.decode_tokens(
                    token_ids[start:end]
                ).strip()

            if content:
                chunks.append(
                    TextChunk(
                        index=len(chunks),
                        content=content,
                        token_count=self.count(content),
                    )
                )

            if end >= total:
                break
            next_start = end - self.overlap_tokens
            if next_start <= start:
                next_start = max(end, start + 1)
            start = next_start


def faq_text(question: str, answer: str) -> str:
    """Combine an FAQ question and answer into one retrieval unit."""
    return (
        f"Q: {' '.join(question.split())}\n"
        f"A: {' '.join(answer.split())}"
    )


def chunk_faq(
    question: str,
    answer: str,
    chunker: TextChunker,
) -> list[TextChunk]:
    """Return one chunk for a typical FAQ, or token-split an unusually long one."""
    text = faq_text(question, answer)
    token_count = chunker.count(text)
    if token_count <= chunker.max_tokens:
        return [TextChunk(index=0, content=text, token_count=token_count)]
    return chunker.split(text)
