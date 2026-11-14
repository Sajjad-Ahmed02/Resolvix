"""Phase 1 database verification.

Run from the backend directory after ``alembic upgrade head`` and
``python -m scripts.seed``:

    python -m scripts.verify

The script exercises the real PostgreSQL database through SQLAlchemy. It is
safe to run repeatedly: temporary rows use a ``phase1-verify-`` prefix and are
removed before and after the checks.
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

# Allow ``python scripts/verify.py`` as well as ``python -m scripts.verify``.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, func, insert, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.security import hash_password, verify_password
from app.db.session import SessionLocal
from app.models import (
    EMBEDDING_DIMENSION,
    EMBEDDING_MODEL,
    Conversation,
    FAQ,
    KnowledgeChunk,
    KnowledgeDocument,
    Message,
    Order,
    OrderItem,
    User,
)


EXPECTED_TABLES = {
    "users",
    "conversations",
    "messages",
    "orders",
    "order_items",
    "faqs",
    "knowledge_documents",
    "knowledge_chunks",
}

REQUIRED_INDEXES = {
    "uq_users_email",
    "ix_conversations_user_id",
    "ix_messages_conversation_id_created_at",
    "uq_orders_order_number",
    "ix_orders_user_id",
    "ix_order_items_order_id",
    "uq_knowledge_chunks_document_id_chunk_index",
    "uq_knowledge_chunks_faq_id_chunk_index",
    "ix_knowledge_chunks_embedding_hnsw",
}

REQUIRED_CHECKS = {
    "ck_users_role",
    "ck_orders_status",
    "ck_orders_shipping_status",
    "ck_orders_total_amount_non_negative",
    "ck_order_items_quantity_positive",
    "ck_order_items_unit_price_non_negative",
    "ck_knowledge_chunks_exactly_one_source",
}

TEMP_PREFIX = "phase1-verify-"
TEMP_MARKER = "[verify]"


def section(title: str) -> None:
    print(f"\n{title}")


def ok(message: str) -> None:
    print(f"  [OK] {message}")


def cleanup(session: Session) -> None:
    """Remove any rows left by this script (cascades handle children)."""
    session.execute(
        delete(KnowledgeDocument).where(
            KnowledgeDocument.title.like(f"{TEMP_MARKER}%")
        )
    )
    session.execute(delete(FAQ).where(FAQ.question.like(f"{TEMP_MARKER}%")))
    session.execute(delete(User).where(User.email.like(f"{TEMP_PREFIX}%")))
    session.flush()


def expect_integrity_error(
    session: Session,
    statement,
    label: str,
) -> None:
    try:
        with session.begin_nested():
            session.execute(statement)
        raise AssertionError(f"{label}: expected an IntegrityError")
    except IntegrityError:
        ok(f"{label} was rejected by a database constraint")


def check_schema(session: Session) -> None:
    section("1. Extension, tables, vector column and constraints")

    extension_version = session.scalar(
        text("select extversion from pg_extension where extname = 'vector'")
    )
    assert extension_version, "pgvector extension is not installed"
    ok(f"pgvector extension is enabled (version {extension_version})")

    table_names = set(
        session.scalars(
            text(
                "select tablename from pg_tables "
                "where schemaname = 'public' and tablename <> 'alembic_version'"
            )
        ).all()
    )
    missing_tables = sorted(EXPECTED_TABLES - table_names)
    assert not missing_tables, f"missing tables: {missing_tables}"
    ok(f"all 8 application tables exist: {', '.join(sorted(EXPECTED_TABLES))}")

    vector_type = session.scalar(
        text(
            "select format_type(atttypid, atttypmod) from pg_attribute "
            "where attrelid = 'public.knowledge_chunks'::regclass "
            "and attname = 'embedding'"
        )
    )
    assert vector_type == f"vector({EMBEDDING_DIMENSION})", vector_type
    ok(f"knowledge_chunks.embedding is {vector_type}")

    vector_not_null = session.scalar(
        text(
            "select attnotnull from pg_attribute "
            "where attrelid = 'public.knowledge_chunks'::regclass "
            "and attname = 'embedding'"
        )
    )
    assert vector_not_null is True
    ok("embedding column is NOT NULL")

    check_names = set(
        session.scalars(
            text(
                "select conname from pg_constraint "
                "where contype = 'c' and connamespace = 'public'::regnamespace"
            )
        ).all()
    )
    missing_checks = sorted(REQUIRED_CHECKS - check_names)
    assert not missing_checks, f"missing check constraints: {missing_checks}"
    ok("role, status, amount, quantity and source CHECK constraints exist")

    fk_rows = session.execute(
        text(
            "select conrelid::regclass::text as table_name, "
            "pg_get_constraintdef(oid) as definition "
            "from pg_constraint where contype = 'f' "
            "and connamespace = 'public'::regnamespace"
        )
    ).all()
    fk_definitions = {
        (row.table_name, row.definition) for row in fk_rows
    }

    expected_fks = (
        ("conversations", "REFERENCES users(id) ON DELETE CASCADE"),
        ("messages", "REFERENCES conversations(id) ON DELETE CASCADE"),
        ("orders", "REFERENCES users(id) ON DELETE RESTRICT"),
        ("order_items", "REFERENCES orders(id) ON DELETE CASCADE"),
        (
            "knowledge_chunks",
            "REFERENCES knowledge_documents(id) ON DELETE CASCADE",
        ),
        ("knowledge_chunks", "REFERENCES faqs(id) ON DELETE CASCADE"),
    )
    for table_name, expected in expected_fks:
        assert any(
            actual_table == table_name and expected in definition
            for actual_table, definition in fk_definitions
        ), f"missing foreign key: {table_name} {expected}"
    ok("all foreign keys and delete rules are present")

    index_definitions = {
        row.indexname: row.indexdef
        for row in session.execute(
            text(
                "select indexname, indexdef from pg_indexes "
                "where schemaname = 'public'"
            )
        ).all()
    }
    missing_indexes = sorted(REQUIRED_INDEXES - set(index_definitions))
    assert not missing_indexes, f"missing indexes: {missing_indexes}"
    ok("required lookup and uniqueness indexes exist")

    hnsw_def = index_definitions["ix_knowledge_chunks_embedding_hnsw"]
    assert "USING hnsw" in hnsw_def, hnsw_def
    assert "vector_cosine_ops" in hnsw_def, hnsw_def
    ok("HNSW cosine-distance index exists on knowledge_chunks.embedding")

    for index_name, column in (
        ("uq_knowledge_chunks_document_id_chunk_index", "document_id"),
        ("uq_knowledge_chunks_faq_id_chunk_index", "faq_id"),
    ):
        definition = index_definitions[index_name]
        assert "UNIQUE" in definition and "WHERE" in definition
        assert column in definition
    ok("document/FAQ chunk uniqueness is enforced by partial unique indexes")


def check_seed_data(session: Session) -> None:
    section("2. Seeded synthetic data and relationships")

    counts = {
        "users": session.scalar(select(func.count()).select_from(User)),
        "orders": session.scalar(select(func.count()).select_from(Order)),
        "order_items": session.scalar(select(func.count()).select_from(OrderItem)),
        "faqs": session.scalar(select(func.count()).select_from(FAQ)),
        "knowledge_documents": session.scalar(
            select(func.count()).select_from(KnowledgeDocument)
        ),
        "knowledge_chunks": session.scalar(
            select(func.count()).select_from(KnowledgeChunk)
        ),
        "customers": session.scalar(
            select(func.count()).select_from(User).where(User.role == "customer")
        ),
        "admins": session.scalar(
            select(func.count()).select_from(User).where(User.role == "admin")
        ),
    }
    assert counts["customers"] >= 5, counts
    assert counts["customers"] <= 10, counts
    assert counts["admins"] >= 1, counts
    assert 10 <= counts["orders"] <= 15, counts
    assert counts["order_items"] >= counts["orders"], counts
    assert 10 <= counts["faqs"] <= 15, counts
    assert 3 <= counts["knowledge_documents"] <= 5, counts
    ok(
        "seed counts are within range: "
        f"{counts['customers']} customers + {counts['admins']} admin, "
        f"{counts['orders']} orders/{counts['order_items']} items, "
        f"{counts['faqs']} FAQs, {counts['knowledge_documents']} documents"
    )

    admin = session.scalar(select(User).where(User.role == "admin"))
    assert admin is not None
    assert verify_password("Admin123!", admin.password_hash)
    ok("admin password is stored as a verifiable PBKDF2 hash, never plaintext")

    orders_without_items = session.scalar(
        select(func.count())
        .select_from(Order)
        .outerjoin(Order.items)
        .where(OrderItem.id.is_(None))
    )
    assert orders_without_items == 0
    ok("every order has at least one order item")

    total_mismatches = session.execute(
        select(Order.order_number, Order.total_amount)
        .join(Order.items)
        .group_by(Order.id, Order.order_number, Order.total_amount)
        .having(
            Order.total_amount
            != func.sum(OrderItem.quantity * OrderItem.unit_price)
        )
    ).all()
    assert not total_mismatches, total_mismatches
    ok("each order total equals the sum of its line items")

    sample_order = session.scalar(
        select(Order)
        .options(selectinload(Order.items), selectinload(Order.user))
        .order_by(Order.order_number)
        .limit(1)
    )
    assert sample_order is not None
    assert sample_order.items
    assert sample_order.user.role == "customer"
    ok(
        f"order {sample_order.order_number} loads its user and "
        f"{len(sample_order.items)} items through SQLAlchemy relationships"
    )


def check_crud(session: Session) -> tuple[uuid.UUID, uuid.UUID]:
    section("3. CRUD and ORM relationship round-trip")

    email = f"{TEMP_PREFIX}{uuid.uuid4().hex[:10]}@example.com"
    user = User(
        name="Phase 1 Verifier",
        email=email,
        password_hash=hash_password("Verify123!"),
        role="customer",
    )
    conversation = Conversation(user=user, title=f"{TEMP_MARKER} Conversation")
    conversation.messages.extend(
        [
            Message(
                role="user",
                content="Where is my order?",
                message_metadata={"source": "phase1-verification", "attempt": 1},
            ),
            Message(
                role="assistant",
                content="Please share your order number.",
            ),
        ]
    )
    session.add(user)
    session.commit()

    user_id = user.id
    conversation_id = conversation.id

    loaded = session.scalar(
        select(User)
        .options(
            selectinload(User.conversations).selectinload(Conversation.messages)
        )
        .where(User.id == user_id)
    )
    assert loaded is not None
    assert loaded.name == "Phase 1 Verifier"
    assert len(loaded.conversations) == 1
    assert len(loaded.conversations[0].messages) == 2
    assert loaded.conversations[0].messages[0].role == "user"
    assert loaded.conversations[0].messages[1].role == "assistant"
    ok("created and re-read user -> conversation -> messages")

    loaded.name = "Phase 1 Verification User"
    loaded.conversations[0].title = f"{TEMP_MARKER} Updated conversation"
    loaded.conversations[0].messages[0].content = "Where is order RX-2026-1001?"
    session.commit()

    reloaded = session.scalar(
        select(User)
        .options(
            selectinload(User.conversations).selectinload(Conversation.messages)
        )
        .where(User.id == user_id)
    )
    assert reloaded is not None
    assert reloaded.name == "Phase 1 Verification User"
    assert reloaded.conversations[0].title.endswith("Updated conversation")
    assert(
        reloaded.conversations[0].messages[0].content
        == "Where is order RX-2026-1001?"
    )
    assert (
        reloaded.conversations[0].messages[0].message_metadata
        == {"source": "phase1-verification", "attempt": 1}
    )
    ok("updated user, conversation and message; JSONB metadata round-tripped")

    return user_id, conversation_id


def check_constraints(
    session: Session,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
) -> None:
    section("4. Database constraint enforcement")

    expect_integrity_error(
        session,
        insert(Message).values(
            conversation_id=conversation_id,
            role="system",
            content="Unsupported role",
        ),
        "Invalid message role",
    )

    seeded_order_id = session.scalar(select(Order.id).limit(1))
    assert seeded_order_id is not None
    expect_integrity_error(
        session,
        insert(OrderItem).values(
            order_id=seeded_order_id,
            product_name="Invalid quantity item",
            quantity=0,
            unit_price=Decimal("1.00"),
        ),
        "Non-positive order item quantity",
    )
    expect_integrity_error(
        session,
        insert(OrderItem).values(
            order_id=seeded_order_id,
            product_name="Invalid price item",
            quantity=1,
            unit_price=Decimal("-0.01"),
        ),
        "Negative order item unit price",
    )
    expect_integrity_error(
        session,
        insert(Order).values(
            user_id=user_id,
            order_number=f"VERIFY-{uuid.uuid4().hex[:10]}",
            order_date=datetime.now(timezone.utc),
            status="pending",
            total_amount=Decimal("-1.00"),
        ),
        "Negative order total",
    )
    expect_integrity_error(
        session,
        insert(Order).values(
            user_id=user_id,
            order_number=f"VERIFY-{uuid.uuid4().hex[:10]}",
            order_date=datetime.now(timezone.utc),
            status="unknown",
            total_amount=Decimal("1.00"),
        ),
        "Invalid order status",
    )

    seeded_user_with_order = session.scalar(
        select(User.id).join(Order).where(User.role == "customer").limit(1)
    )
    assert seeded_user_with_order is not None
    expect_integrity_error(
        session,
        delete(User).where(User.id == seeded_user_with_order),
        "Deleting a user who still has orders",
    )

    session.execute(delete(Conversation).where(Conversation.id == conversation_id))
    session.commit()
    remaining_messages = session.scalar(
        select(func.count())
        .select_from(Message)
        .where(Message.conversation_id == conversation_id)
    )
    assert remaining_messages == 0
    ok("deleting a conversation cascaded to its messages")


def check_vector_store(session: Session) -> None:
    section("5. pgvector insert, retrieval and cosine similarity")

    document = KnowledgeDocument(
        title=f"{TEMP_MARKER} Vector search {uuid.uuid4().hex[:8]}",
        content="Temporary document used by the Phase 1 verification script.",
        category="Verification",
    )
    faq = FAQ(
        question=f"{TEMP_MARKER} FAQ {uuid.uuid4().hex[:8]}",
        answer="Temporary FAQ used by the Phase 1 verification script.",
        category="Verification",
    )
    session.add_all([document, faq])
    session.flush()

    vector_a = [0.0] * EMBEDDING_DIMENSION
    vector_a[0] = 1.0
    vector_b = [0.0] * EMBEDDING_DIMENSION
    vector_b[1] = 1.0

    chunk_a = KnowledgeChunk(
        document_id=document.id,
        chunk_index=0,
        content="First verification chunk.",
        embedding=vector_a,
        embedding_model=EMBEDDING_MODEL,
    )
    chunk_b = KnowledgeChunk(
        document_id=document.id,
        chunk_index=1,
        content="Second verification chunk.",
        embedding=vector_b,
        embedding_model=EMBEDDING_MODEL,
    )
    faq_chunk = KnowledgeChunk(
        faq_id=faq.id,
        chunk_index=0,
        content="FAQ verification chunk.",
        embedding=vector_a,
        embedding_model=EMBEDDING_MODEL,
    )
    session.add_all([chunk_a, chunk_b, faq_chunk])
    session.commit()

    fetched = session.get(KnowledgeChunk, chunk_a.id)
    assert fetched is not None
    assert len(fetched.embedding) == EMBEDDING_DIMENSION
    ok(
        f"inserted and retrieved a {EMBEDDING_DIMENSION}-dimensional vector "
        f"(model: {fetched.embedding_model})"
    )

    distance = KnowledgeChunk.embedding.cosine_distance(vector_a)
    results = session.execute(
        select(KnowledgeChunk.id, distance.label("distance"))
        .where(KnowledgeChunk.document_id == document.id)
        .order_by(distance)
    ).all()
    assert len(results) == 2
    assert results[0].id == chunk_a.id
    assert abs(results[0].distance) < 1e-6
    assert abs(results[1].distance - 1.0) < 1e-6
    ok(
        "cosine-distance query (<=>) returned the nearest chunk first "
        f"(distance {results[0].distance:.4f})"
    )

    expect_integrity_error(
        session,
        insert(KnowledgeChunk).values(
            document_id=document.id,
            faq_id=faq.id,
            chunk_index=2,
            content="Chunk with two sources",
            embedding=vector_a,
            embedding_model=EMBEDDING_MODEL,
        ),
        "Chunk with both document_id and faq_id",
    )
    expect_integrity_error(
        session,
        insert(KnowledgeChunk).values(
            chunk_index=2,
            content="Chunk with no source",
            embedding=vector_a,
            embedding_model=EMBEDDING_MODEL,
        ),
        "Chunk with neither document_id nor faq_id",
    )
    expect_integrity_error(
        session,
        insert(KnowledgeChunk).values(
            document_id=document.id,
            chunk_index=0,
            content="Duplicate document chunk index",
            embedding=vector_a,
            embedding_model=EMBEDDING_MODEL,
        ),
        "Duplicate document chunk_index",
    )
    expect_integrity_error(
        session,
        insert(KnowledgeChunk).values(
            faq_id=faq.id,
            chunk_index=0,
            content="Duplicate FAQ chunk index",
            embedding=vector_a,
            embedding_model=EMBEDDING_MODEL,
        ),
        "Duplicate FAQ chunk_index",
    )

    section("6. Source update/delete keeps chunks synchronized")

    # Phase 5 ingestion will use this replace strategy whenever a source's
    # content changes: delete its old chunks, insert freshly embedded chunks.
    session.execute(
        delete(KnowledgeChunk).where(KnowledgeChunk.document_id == document.id)
    )
    replacement = KnowledgeChunk(
        document_id=document.id,
        chunk_index=0,
        content="Updated verification chunk after re-chunking.",
        embedding=vector_b,
        embedding_model=EMBEDDING_MODEL,
    )
    session.add(replacement)
    session.commit()

    document_chunk_count = session.scalar(
        select(func.count())
        .select_from(KnowledgeChunk)
        .where(KnowledgeChunk.document_id == document.id)
    )
    assert document_chunk_count == 1
    refreshed = session.get(KnowledgeChunk, replacement.id)
    assert refreshed is not None
    assert refreshed.content.startswith("Updated verification chunk")
    ok("document chunks were replaced atomically for re-chunking/re-embedding")

    session.execute(
        delete(KnowledgeDocument).where(KnowledgeDocument.id == document.id)
    )
    session.commit()
    document_chunk_count = session.scalar(
        select(func.count())
        .select_from(KnowledgeChunk)
        .where(KnowledgeChunk.document_id == document.id)
    )
    assert document_chunk_count == 0
    ok("deleting a knowledge document cascaded to its chunks")

    session.execute(delete(FAQ).where(FAQ.id == faq.id))
    session.commit()
    faq_chunk_count = session.scalar(
        select(func.count())
        .select_from(KnowledgeChunk)
        .where(KnowledgeChunk.faq_id == faq.id)
    )
    assert faq_chunk_count == 0
    ok("deleting an FAQ cascaded to its chunks")


def main() -> None:
    print("Resolvix Phase 1 database verification")

    with SessionLocal() as session:
        cleanup(session)
        session.commit()

        try:
            check_schema(session)
            check_seed_data(session)
            user_id, conversation_id = check_crud(session)
            check_constraints(session, user_id, conversation_id)
            check_vector_store(session)
        finally:
            session.rollback()
            cleanup(session)
            session.commit()

    print("\nAll Phase 1 database checks passed.")


if __name__ == "__main__":
    main()
