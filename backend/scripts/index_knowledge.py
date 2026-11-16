"""Index FAQs and knowledge documents into pgvector.

Run from the backend directory:

    python -m scripts.index_knowledge
    python -m scripts.index_knowledge --force

Run this after seeding or after changing FAQ/document content. The first run
downloads sentence-transformers/all-MiniLM-L6-v2 (about 90 MB) to the local
Hugging Face cache; later runs reuse it.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Allow ``python scripts/index_knowledge.py`` as well as module invocation.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.db.session import SessionLocal
from app.knowledge.embeddings import get_embedder
from app.knowledge.ingestion import KnowledgeIngestor


async def index_all(*, force: bool) -> int:
    embedder = get_embedder()
    ingestor = KnowledgeIngestor(
        embedder,
        max_tokens=settings.KNOWLEDGE_CHUNK_MAX_TOKENS,
        overlap_tokens=settings.KNOWLEDGE_CHUNK_OVERLAP_TOKENS,
        force=force,
    )

    session = SessionLocal()
    try:
        report = await ingestor.sync_all(session)
    finally:
        session.close()

    summary = report.summary()
    print(f"Embedding model: {embedder.model_name} ({embedder.dimension}d)")
    print(f"Sources scanned: {summary['sources']}")
    print(f"Indexed:         {summary['indexed']}")
    print(f"Version refresh: {summary['refreshed']}")
    print(f"Skipped:         {summary['skipped']}")
    print(f"Deleted:         {summary['deleted']}")
    print(f"Failed:          {summary['failed']}")
    print(f"Chunks written:  {summary['chunks_written']}")

    failures = [
        result for result in report.results if result.action == "failed"
    ]
    for result in failures:
        print(
            f"FAILED {result.source_type} {result.source_id} "
            f"({result.title}): {result.error}"
        )

    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate embeddings for Resolvix FAQs and documents.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-embed every source even when chunks are unchanged.",
    )
    args = parser.parse_args()
    return asyncio.run(index_all(force=args.force))


if __name__ == "__main__":
    sys.exit(main())
