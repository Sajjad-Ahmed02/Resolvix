from __future__ import annotations

import asyncio
import uuid
from collections.abc import Sequence

import pytest
from sqlalchemy import delete

from app.db.session import SessionLocal
from app.knowledge.embeddings import SentenceTransformerEmbedder
from app.knowledge.ingestion import KnowledgeIngestor
from app.knowledge.retrieval import KnowledgeRetriever
from app.models import FAQ, KnowledgeDocument
from app.repositories import knowledge

CATEGORY_PREFIX = "phase5-test-"


@pytest.fixture(scope="module")
def embedder() -> SentenceTransformerEmbedder:
    return SentenceTransformerEmbedder(device="cpu", batch_size=8)


@pytest.fixture()
def session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


class CountingEmbedder:
    """Delegate to the real model while counting embedding batches."""

    def __init__(self, base: SentenceTransformerEmbedder) -> None:
        self.base = base
        self.document_calls = 0
        self.embedded_texts: list[str] = []

    @property
    def model_name(self) -> str:
        return self.base.model_name

    @property
    def dimension(self) -> int:
        return self.base.dimension

    @property
    def max_seq_length(self) -> int:
        return self.base.max_seq_length

    def reusable_token_limit(self) -> int:
        return self.base.reusable_token_limit()

    def count_tokens(self, text: str) -> int:
        return self.base.count_tokens(text)

    def encode_tokens(self, text: str) -> list[int]:
        return self.base.encode_tokens(text)

    def decode_tokens(self, tokens: Sequence[int]) -> str:
        return self.base.decode_tokens(tokens)

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.document_calls += 1
        self.embedded_texts.extend(texts)
        return await self.base.embed_documents(texts)

    async def embed_query(self, text: str) -> list[float]:
        return await self.base.embed_query(text)


class FailingEmbedder(CountingEmbedder):
    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        raise RuntimeError("simulated embedding outage")


def _create_faq(
    session,
    *,
    question: str,
    answer: str,
    suffix: str,
    active: bool = True,
) -> FAQ:
    faq = FAQ(
        question=question,
        answer=answer,
        category=f"{CATEGORY_PREFIX}{suffix}",
        is_active=active,
    )
    session.add(faq)
    session.commit()
    session.refresh(faq)
    return faq


def _create_document(
    session,
    *,
    title: str,
    content: str,
    suffix: str,
) -> KnowledgeDocument:
    document = KnowledgeDocument(
        title=title,
        content=content,
        category=f"{CATEGORY_PREFIX}{suffix}",
    )
    session.add(document)
    session.commit()
    session.refresh(document)
    return document


def _ingestor(
    embedder: SentenceTransformerEmbedder,
    *,
    force: bool = False,
) -> KnowledgeIngestor:
    return KnowledgeIngestor(
        embedder,
        max_tokens=200,
        overlap_tokens=40,
        force=force,
    )


def _cleanup_faqs(session, *faqs: FAQ) -> None:
    ids = [faq.id for faq in faqs]
    if ids:
        session.execute(delete(FAQ).where(FAQ.id.in_(ids)))
        session.commit()


def _cleanup_documents(session, *documents: KnowledgeDocument) -> None:
    ids = [document.id for document in documents]
    if ids:
        session.execute(
            delete(KnowledgeDocument).where(KnowledgeDocument.id.in_(ids))
        )
        session.commit()


def test_paraphrased_queries_retrieve_relevant_faq_chunks(
    session,
    embedder: SentenceTransformerEmbedder,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    specs = [
        (
            "How many days do I have to send back an unused item?",
            "Unused items can be returned within 30 days of delivery for a "
            "full refund.",
        ),
        (
            "How long does a refund take to reach my bank account?",
            "Refunds are processed within 2 business days after inspection. "
            "Banks may take another 5 to 10 business days.",
        ),
        (
            "When will my standard delivery arrive?",
            "Standard delivery arrives 3 to 5 business days after dispatch.",
        ),
        (
            "Which credit cards and wallets can I use at checkout?",
            "We accept Visa, Mastercard, Apple Pay, Google Pay, and PayPal.",
        ),
        (
            "How do I get help with a faulty device under warranty?",
            "Contact support with the order number and serial number. "
            "Approved claims are repaired or replaced.",
        ),
    ]
    faqs = [
        _create_faq(
            session,
            question=question,
            answer=answer,
            suffix=f"{suffix}-{index}",
        )
        for index, (question, answer) in enumerate(specs)
    ]
    ingestor = _ingestor(embedder)

    try:
        for faq in faqs:
            result = asyncio.run(ingestor.sync_faq(session, faq))
            assert result.action == "indexed", result

        retriever = KnowledgeRetriever(embedder, top_k=20, max_distance=None)
        queries = [
            ("Can I send an item back if it does not fit?", faqs[0]),
            ("When will the money be back on my card?", faqs[1]),
            ("What is the normal delivery time?", faqs[2]),
            ("Do you take PayPal or Apple Pay?", faqs[3]),
            ("My device is broken and still covered, what now?", faqs[4]),
        ]

        for query, expected in queries:
            results = asyncio.run(retriever.retrieve(session, query))
            retrieved_ids = [result.source_id for result in results]
            diagnostics = [
                (result.title, round(result.distance, 4))
                for result in results[:5]
            ]
            assert retrieved_ids, (query, diagnostics)
            assert expected.id in retrieved_ids, (query, diagnostics)
            expected_result = next(
                result
                for result in results
                if result.source_id == expected.id
            )
            assert expected_result.distance < 0.7, (query, diagnostics)
            assert expected_result.content.strip(), query
    finally:
        _cleanup_faqs(session, *faqs)


def test_similarity_threshold_filters_unrelated_queries(
    session,
    embedder: SentenceTransformerEmbedder,
) -> None:
    retriever = KnowledgeRetriever(embedder, top_k=4, max_distance=0.7)

    results = asyncio.run(
        retriever.retrieve(session, "What is the capital of France?")
    )

    assert results == []


def test_document_ingestion_preserves_order_and_source_traceability(
    session,
    embedder: SentenceTransformerEmbedder,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    paragraphs = " ".join(
        f"Sentence {index} explains warranty coverage in detail."
        for index in range(80)
    )
    document = _create_document(
        session,
        title=f"Phase 5 Warranty Guide {suffix}",
        content=(
            "Warranty Guide\n\n"
            "Most hardware products include a one-year limited warranty. "
            f"{paragraphs}"
        ),
        suffix=suffix,
    )
    ingestor = _ingestor(embedder)

    try:
        result = asyncio.run(ingestor.sync_document(session, document))
        assert result.action == "indexed", result

        chunks = knowledge.list_chunks_for_document(session, document.id)
        assert len(chunks) > 1
        assert [chunk.chunk_index for chunk in chunks] == list(
            range(len(chunks))
        )
        assert all(chunk.faq_id is None for chunk in chunks)
        assert all(chunk.document_id == document.id for chunk in chunks)
        assert all(
            chunk.embedding_model == embedder.model_name for chunk in chunks
        )
        assert all(
            chunk.source_updated_at == document.updated_at for chunk in chunks
        )
        assert all(len(chunk.embedding) == 384 for chunk in chunks)

        retriever = KnowledgeRetriever(embedder, top_k=20, max_distance=None)
        results = asyncio.run(
            retriever.retrieve(
                session,
                "How long is the hardware warranty?",
            )
        )
        assert document.id in [item.source_id for item in results]
    finally:
        _cleanup_documents(session, document)


def test_unchanged_sources_skip_re_embedding(
    session,
    embedder: SentenceTransformerEmbedder,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    faq = _create_faq(
        session,
        question=f"Phase 5 skip test {suffix}: how do I track a parcel?",
        answer="Open the order details page to see the latest carrier scan.",
        suffix=suffix,
    )
    counting = CountingEmbedder(embedder)

    try:
        first = asyncio.run(_ingestor(counting).sync_faq(session, faq))
        assert first.action == "indexed"
        assert counting.document_calls == 1

        second = asyncio.run(_ingestor(counting).sync_faq(session, faq))
        assert second.action == "skipped"
        assert counting.document_calls == 1

        forced = asyncio.run(_ingestor(counting, force=True).sync_faq(session, faq))
        assert forced.action == "indexed"
        assert counting.document_calls == 2
    finally:
        _cleanup_faqs(session, faq)


def test_metadata_only_source_update_refreshes_version_without_re_embedding(
    session,
    embedder: SentenceTransformerEmbedder,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    faq = _create_faq(
        session,
        question=f"Phase 5 version test {suffix}: can I cancel an order?",
        answer="Orders can be cancelled while their status is Pending.",
        suffix=suffix,
    )
    counting = CountingEmbedder(embedder)

    try:
        assert (
            asyncio.run(_ingestor(counting).sync_faq(session, faq)).action
            == "indexed"
        )
        chunks = knowledge.list_chunks_for_faq(session, faq.id)
        chunk_ids = [chunk.id for chunk in chunks]
        assert counting.document_calls == 1

        faq.category = f"{CATEGORY_PREFIX}{suffix}-renamed"
        session.commit()
        session.refresh(faq)

        refreshed = asyncio.run(_ingestor(counting).sync_faq(session, faq))
        assert refreshed.action == "refreshed"
        assert counting.document_calls == 1

        current = knowledge.list_chunks_for_faq(session, faq.id)
        assert [chunk.id for chunk in current] == chunk_ids
        assert all(
            chunk.source_updated_at == faq.updated_at for chunk in current
        )
    finally:
        _cleanup_faqs(session, faq)


def test_content_update_replaces_chunks_and_embeddings(
    session,
    embedder: SentenceTransformerEmbedder,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    faq = _create_faq(
        session,
        question=f"Phase 5 update test {suffix}: how long is the return window?",
        answer="Unused items can be returned within 30 days.",
        suffix=suffix,
    )
    ingestor = _ingestor(embedder)

    try:
        assert asyncio.run(ingestor.sync_faq(session, faq)).action == "indexed"
        old_chunks = knowledge.list_chunks_for_faq(session, faq.id)
        old_ids = [chunk.id for chunk in old_chunks]
        assert "30 days" in old_chunks[0].content

        faq.answer = "Unused items can be returned within 45 days."
        session.commit()
        session.refresh(faq)

        updated = asyncio.run(ingestor.sync_faq(session, faq))
        assert updated.action == "indexed"

        new_chunks = knowledge.list_chunks_for_faq(session, faq.id)
        assert [chunk.id for chunk in new_chunks] != old_ids
        assert "45 days" in new_chunks[0].content
        assert all(
            chunk.source_updated_at == faq.updated_at for chunk in new_chunks
        )

        retriever = KnowledgeRetriever(embedder, top_k=20, max_distance=None)
        results = asyncio.run(
            retriever.retrieve(
                session,
                "How long do I have to return something?",
            )
        )
        assert faq.id in [item.source_id for item in results]
        assert any("45 days" in item.content for item in results)
    finally:
        _cleanup_faqs(session, faq)


def test_chunks_from_other_embedding_models_are_excluded(
    session,
    embedder: SentenceTransformerEmbedder,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    faq = _create_faq(
        session,
        question=(
            f"Phase 5 model filter {suffix}: how long is the return window?"
        ),
        answer="Unused items can be returned within 30 days.",
        suffix=suffix,
    )
    ingestor = _ingestor(embedder)
    query = f"Phase 5 model filter {suffix} return window"
    retriever = KnowledgeRetriever(embedder, top_k=20, max_distance=None)

    try:
        assert asyncio.run(ingestor.sync_faq(session, faq)).action == "indexed"
        chunks = knowledge.list_chunks_for_faq(session, faq.id)
        chunks[0].embedding_model = "different-embedding-model"
        session.commit()

        stale_results = asyncio.run(retriever.retrieve(session, query))
        assert faq.id not in [item.source_id for item in stale_results]

        reindexed = asyncio.run(ingestor.sync_faq(session, faq))
        assert reindexed.action == "indexed"

        current_results = asyncio.run(retriever.retrieve(session, query))
        assert faq.id in [item.source_id for item in current_results]
    finally:
        _cleanup_faqs(session, faq)


def test_failed_reindex_does_not_serve_stale_chunks(
    session,
    embedder: SentenceTransformerEmbedder,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    faq = _create_faq(
        session,
        question=f"Phase 5 failure test {suffix}: what is the refund timeline?",
        answer="Refunds are processed within 2 business days after inspection.",
        suffix=suffix,
    )

    try:
        assert (
            asyncio.run(_ingestor(embedder).sync_faq(session, faq)).action
            == "indexed"
        )
        stale_chunks = knowledge.list_chunks_for_faq(session, faq.id)
        assert stale_chunks

        faq.answer = "Refunds are processed within 10 business days after inspection."
        session.commit()
        session.refresh(faq)

        failing = _ingestor(FailingEmbedder(embedder))
        result = asyncio.run(failing.sync_faq(session, faq))
        assert result.action == "failed"
        assert "simulated embedding outage" in (result.error or "")

        # The old rows still exist, but their source version no longer matches
        # the edited FAQ, so retrieval must not serve them.
        session.expire_all()
        remaining = knowledge.list_chunks_for_faq(session, faq.id)
        assert remaining
        assert all(
            chunk.source_updated_at != faq.updated_at for chunk in remaining
        )

        retriever = KnowledgeRetriever(embedder, top_k=5, max_distance=None)
        results = asyncio.run(
            retriever.retrieve(
                session,
                "How fast are refunds processed?",
            )
        )
        assert faq.id not in [item.source_id for item in results]
    finally:
        _cleanup_faqs(session, faq)


def test_inactive_sources_are_excluded_from_retrieval(
    session,
    embedder: SentenceTransformerEmbedder,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    active = _create_faq(
        session,
        question=f"Phase 5 active sale policy {suffix}: are final sale items returnable?",
        answer="Final sale items cannot be returned unless they arrive damaged.",
        suffix=f"{suffix}-active",
    )
    inactive = _create_faq(
        session,
        question=f"Phase 5 inactive sale policy {suffix}: are final sale items returnable?",
        answer="Final sale items cannot be returned unless they arrive damaged.",
        suffix=f"{suffix}-inactive",
        active=False,
    )
    ingestor = _ingestor(embedder)

    try:
        assert asyncio.run(ingestor.sync_faq(session, active)).action == "indexed"
        inactive_result = asyncio.run(ingestor.sync_faq(session, inactive))
        assert inactive_result.action == "skipped"
        assert knowledge.list_chunks_for_faq(session, inactive.id) == []

        retriever = KnowledgeRetriever(embedder, top_k=5, max_distance=None)
        results = asyncio.run(
            retriever.retrieve(session, "Can I return a final sale item?")
        )
        source_ids = [item.source_id for item in results]
        assert active.id in source_ids
        assert inactive.id not in source_ids

        inactive.is_active = True
        session.commit()
        session.refresh(inactive)
        assert (
            asyncio.run(ingestor.sync_faq(session, inactive)).action
            == "indexed"
        )

        inactive.is_active = False
        session.commit()
        session.refresh(inactive)
        deleted = asyncio.run(ingestor.sync_faq(session, inactive))
        assert deleted.action == "deleted"
        assert knowledge.list_chunks_for_faq(session, inactive.id) == []
    finally:
        _cleanup_faqs(session, active, inactive)
