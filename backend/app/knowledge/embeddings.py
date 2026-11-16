"""Local sentence-transformer embeddings for ingestion and retrieval.

The same embedder instance type produces chunk vectors during ingestion and
query vectors during retrieval. The model is loaded lazily so importing the
application does not download or initialize it, and encoding runs in a worker
thread so FastAPI's event loop stays responsive.
"""

from __future__ import annotations

import asyncio
import logging
import math
import threading
from collections.abc import Sequence
from typing import Protocol

from app.core.config import settings

DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIMENSION = 384

logger = logging.getLogger(__name__)


class EmbeddingError(RuntimeError):
    """Base class for safe embedding failures."""


class EmbeddingConfigurationError(EmbeddingError):
    """The model or its output does not match the application contract."""


class EmbeddingInputTooLongError(EmbeddingError):
    """A chunk exceeds the model's context window instead of being truncated."""


def _model_dimension(model) -> int:
    """Read the vector size across sentence-transformers API versions."""
    getter = getattr(model, "get_embedding_dimension", None)
    if getter is None:  # sentence-transformers < 6.3
        getter = model.get_sentence_embedding_dimension
    return int(getter())


class Embedder(Protocol):
    """Interface shared by the real model and deterministic test doubles."""

    model_name: str
    dimension: int
    max_seq_length: int

    async def embed_documents(
        self,
        texts: Sequence[str],
    ) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...

    def count_tokens(self, text: str) -> int: ...

    def encode_tokens(self, text: str) -> list[int]: ...

    def decode_tokens(self, tokens: Sequence[int]) -> str: ...

    def reusable_token_limit(self) -> int: ...


class SentenceTransformerEmbedder:
    """Load ``sentence-transformers/all-MiniLM-L6-v2`` and produce vectors."""

    def __init__(
        self,
        *,
        model_name: str = DEFAULT_EMBEDDING_MODEL,
        device: str = "cpu",
        batch_size: int = 32,
    ) -> None:
        normalized_model = model_name.strip()
        if not normalized_model:
            raise EmbeddingConfigurationError("EMBEDDING_MODEL must not be blank.")

        normalized_device = device.strip()
        if not normalized_device:
            raise EmbeddingConfigurationError("EMBEDDING_DEVICE must not be blank.")
        if batch_size < 1:
            raise EmbeddingConfigurationError("EMBEDDING_BATCH_SIZE must be positive.")

        self.model_name = normalized_model
        self.device = normalized_device
        self.batch_size = batch_size
        self._model = None
        self._model_lock = threading.Lock()
        self._encode_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Lazy model loading and tokenizer access
    # ------------------------------------------------------------------

    def _load_model(self):
        if self._model is not None:
            return self._model

        with self._model_lock:
            if self._model is not None:
                return self._model

            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as error:  # pragma: no cover - dependency guard
                raise EmbeddingConfigurationError(
                    "sentence-transformers is not installed. "
                    "Install the backend requirements first."
                ) from error

            try:
                model = SentenceTransformer(self.model_name, device=self.device)
            except Exception as error:
                raise EmbeddingConfigurationError(
                    f"Could not load embedding model '{self.model_name}'."
                ) from error

            dimension = _model_dimension(model)
            if dimension != EMBEDDING_DIMENSION:
                raise EmbeddingConfigurationError(
                    f"Embedding model '{self.model_name}' returns {dimension} "
                    f"dimensions, but knowledge_chunks expects "
                    f"{EMBEDDING_DIMENSION}."
                )
            self._model = model
            return model

    @property
    def dimension(self) -> int:
        return _model_dimension(self._load_model())

    @property
    def max_seq_length(self) -> int:
        return int(self._load_model().max_seq_length)

    def _tokenizer(self):
        return self._load_model().tokenizer

    def _special_token_count(self) -> int:
        tokenizer = self._tokenizer()
        try:
            return int(tokenizer.num_special_tokens_to_add(pair=False))
        except (AttributeError, TypeError):
            return 2

    def reusable_token_limit(self) -> int:
        """Tokens available to content, excluding CLS/SEP-style tokens."""
        return self.max_seq_length - self._special_token_count()

    def count_tokens(self, text: str) -> int:
        return len(self.encode_tokens(text))

    def encode_tokens(self, text: str) -> list[int]:
        tokenizer = self._tokenizer()
        return list(tokenizer.encode(text, add_special_tokens=False))

    def decode_tokens(self, tokens: Sequence[int]) -> str:
        return self._tokenizer().decode(
            list(tokens),
            skip_special_tokens=True,
        )

    # ------------------------------------------------------------------
    # Encoding
    # ------------------------------------------------------------------

    async def embed_documents(
        self,
        texts: Sequence[str],
    ) -> list[list[float]]:
        """Embed chunk text, rejecting anything the model would truncate."""
        if not texts:
            return []
        return await asyncio.to_thread(self._embed_documents_sync, list(texts))

    async def embed_query(self, text: str) -> list[float]:
        """Embed a customer query with the same model used for chunks."""
        normalized = text.strip()
        if not normalized:
            raise ValueError("Embedding query must not be blank.")
        return await asyncio.to_thread(self._embed_query_sync, normalized)

    def _embed_documents_sync(self, texts: list[str]) -> list[list[float]]:
        model = self._load_model()
        limit = self.reusable_token_limit()

        for index, text in enumerate(texts):
            if not text.strip():
                raise EmbeddingInputTooLongError(
                    f"Chunk {index} is blank and cannot be embedded."
                )
            token_count = self.count_tokens(text)
            if token_count > limit:
                raise EmbeddingInputTooLongError(
                    f"Chunk {index} has {token_count} tokens, but "
                    f"'{self.model_name}' accepts at most {limit} content "
                    "tokens. Reduce KNOWLEDGE_CHUNK_MAX_TOKENS or re-chunk "
                    "before embedding."
                )

        with self._encode_lock:
            matrix = model.encode(
                texts,
                batch_size=self.batch_size,
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )

        return self._validate_matrix(matrix, expected_rows=len(texts))

    def _embed_query_sync(self, text: str) -> list[float]:
        model = self._load_model()
        limit = self.reusable_token_limit()
        token_ids = self.encode_tokens(text)

        # Long customer messages are common. Keep the most recent tokens
        # explicitly rather than allowing the tokenizer to truncate silently;
        # the end of a support message usually contains the actual question.
        if len(token_ids) > limit:
            logger.info(
                "Trimming retrieval query from %s to %s tokens.",
                len(token_ids),
                limit,
            )
            text = self.decode_tokens(token_ids[-limit:])

        with self._encode_lock:
            vector = model.encode(
                [text],
                batch_size=1,
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )

        values = self._validate_matrix(vector, expected_rows=1)[0]
        return values

    def _validate_matrix(
        self,
        matrix,
        *,
        expected_rows: int,
    ) -> list[list[float]]:
        try:
            rows = matrix.tolist()
        except AttributeError as error:  # pragma: no cover - defensive
            raise EmbeddingError("Embedding model returned an invalid matrix.") from error

        if len(rows) != expected_rows:
            raise EmbeddingError(
                "Embedding model returned a different number of vectors than "
                "inputs."
            )

        validated: list[list[float]] = []
        for row in rows:
            if len(row) != EMBEDDING_DIMENSION:
                raise EmbeddingError(
                    f"Expected {EMBEDDING_DIMENSION}-dimensional vectors, got "
                    f"{len(row)}."
                )
            values = [float(value) for value in row]
            if not all(math.isfinite(value) for value in values):
                raise EmbeddingError("Embedding model returned non-finite values.")
            validated.append(values)
        return validated


_embedder: SentenceTransformerEmbedder | None = None
_embedder_lock = threading.Lock()


def get_embedder() -> SentenceTransformerEmbedder:
    """Return the process-wide embedder configured by settings."""
    global _embedder
    if _embedder is None:
        with _embedder_lock:
            if _embedder is None:
                _embedder = SentenceTransformerEmbedder(
                    model_name=settings.EMBEDDING_MODEL,
                    device=settings.EMBEDDING_DEVICE,
                    batch_size=settings.EMBEDDING_BATCH_SIZE,
                )
    return _embedder
