"""Migration and database-constraint tests against a disposable database.

The development database is never migrated or modified by this module. A
temporary PostgreSQL database is created from the server in ``DATABASE_URL``,
``alembic upgrade head`` runs in a subprocess with an overridden URL, the
schema and constraints are exercised, and the database is dropped afterwards.

If PostgreSQL is unreachable or the configured role cannot create databases,
the tests skip with an explicit reason instead of silently passing.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import DataError, IntegrityError, SQLAlchemyError

from app.core.config import settings

BACKEND_DIR = Path(__file__).resolve().parents[1]
EXPECTED_TABLES = {
    "alembic_version",
    "users",
    "refresh_tokens",
    "conversations",
    "messages",
    "orders",
    "order_items",
    "faqs",
    "knowledge_documents",
    "knowledge_chunks",
}
EXPECTED_INDEXES = {
    "uq_users_email",
    "ix_conversations_user_id",
    "ix_messages_conversation_id_created_at",
    "uq_orders_order_number",
    "ix_orders_user_id",
    "ix_order_items_order_id",
    "ix_refresh_tokens_user_id",
    "uq_knowledge_chunks_document_id_chunk_index",
    "uq_knowledge_chunks_faq_id_chunk_index",
    "ix_knowledge_chunks_embedding_hnsw",
}
EXPECTED_CHECKS = {
    "ck_users_role",
    "ck_users_email_lowercase",
    "ck_orders_status",
    "ck_orders_shipping_status",
    "ck_orders_total_amount_non_negative",
    "ck_order_items_quantity_positive",
    "ck_order_items_unit_price_non_negative",
    "ck_knowledge_chunks_exactly_one_source",
    "ck_knowledge_chunks_content_not_blank",
    "ck_refresh_tokens_token_hash_length",
}


def _temporary_database_url() -> tuple[str, str]:
    url = make_url(settings.DATABASE_URL)
    if not url.drivername.startswith("postgresql"):
        pytest.skip("Migration tests require PostgreSQL with pgvector.")
    name = f"resolvix_test_{uuid.uuid4().hex[:12]}"
    temporary = url.set(database=name)
    return name, temporary.render_as_string(hide_password=False)


def _admin_engine() -> Engine:
    url = make_url(settings.DATABASE_URL).set(database="postgres")
    return create_engine(
        url,
        isolation_level="AUTOCOMMIT",
        pool_pre_ping=True,
        connect_args={"connect_timeout": settings.DB_CONNECT_TIMEOUT},
    )


def _pgvector_available(admin: Engine) -> bool:
    """Return True when the server can install the ``vector`` extension."""
    with admin.connect() as connection:
        return bool(
            connection.execute(
                text(
                    "SELECT 1 FROM pg_available_extensions "
                    "WHERE name = 'vector'"
                )
            ).scalar()
        )


def _run_alembic(database_url: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url
    environment.setdefault(
        "JWT_SECRET_KEY",
        "migration-test-only-secret-key-0123456789abcdef0123456789abcdef",
    )
    return subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        env=environment,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )


@pytest.fixture(scope="module")
def migrated_database():
    name, database_url = _temporary_database_url()
    admin = _admin_engine()
    created = False
    temporary_engine: Engine | None = None

    try:
        try:
            with admin.connect() as connection:
                connection.execute(text("SELECT 1"))
        except SQLAlchemyError as error:
            pytest.skip(f"PostgreSQL is not reachable for migration tests: {error}")

        try:
            has_pgvector = _pgvector_available(admin)
        except SQLAlchemyError as error:
            pytest.skip(f"Could not inspect PostgreSQL extensions: {error}")
        if not has_pgvector:
            pytest.skip(
                "The local PostgreSQL server does not provide the 'vector' "
                "extension. Install pgvector (see docs/pgvector-setup.md) or "
                "run this suite with the pgvector/pgvector:pg18 image."
            )

        try:
            with admin.connect() as connection:
                connection.execute(text(f'CREATE DATABASE "{name}"'))
            created = True
        except SQLAlchemyError as error:
            pytest.skip(
                "The configured PostgreSQL role cannot create a temporary "
                f"database: {error}"
            )

        completed = _run_alembic(database_url)
        assert completed.returncode == 0, (
            "alembic upgrade head failed:\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )

        temporary_engine = create_engine(
            database_url,
            pool_pre_ping=True,
            connect_args={"connect_timeout": settings.DB_CONNECT_TIMEOUT},
        )
        try:
            with temporary_engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except SQLAlchemyError as error:
            pytest.fail(f"Could not connect to the migrated database: {error}")

        yield temporary_engine
    finally:
        if temporary_engine is not None:
            temporary_engine.dispose()
        if created:
            try:
                with admin.connect() as connection:
                    connection.execute(
                        text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
                    )
            except SQLAlchemyError:
                # Leaving a uniquely named disposable database behind is
                # better than masking the original test failure.
                pass
        admin.dispose()


def _assert_rejected(
    engine: Engine,
    statement: str,
    parameters: dict | None,
    error_type: type[Exception],
    expected: str,
) -> None:
    with engine.connect() as connection:
        with pytest.raises(error_type) as error:
            with connection.begin_nested():
                connection.execute(text(statement), parameters or {})
        connection.rollback()
    assert expected.lower() in str(error.value).lower()


def test_alembic_upgrade_creates_schema_indexes_and_pgvector(
    migrated_database: Engine,
) -> None:
    inspector = inspect(migrated_database)

    assert set(inspector.get_table_names()) == EXPECTED_TABLES

    indexes: set[str] = set()
    checks: set[str] = set()
    for table in EXPECTED_TABLES - {"alembic_version"}:
        indexes.update(
            index["name"]
            for index in inspector.get_indexes(table)
            if index.get("name")
        )
        checks.update(
            check["name"]
            for check in inspector.get_check_constraints(table)
            if check.get("name")
        )

    assert EXPECTED_INDEXES <= indexes
    assert EXPECTED_CHECKS <= checks

    with migrated_database.connect() as connection:
        assert connection.execute(
            text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        ).scalar_one()
        revision = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
    assert revision == "0003_refresh_tokens"


def test_database_constraints_reject_invalid_rows(
    migrated_database: Engine,
) -> None:
    with migrated_database.begin() as connection:
        user_id = connection.execute(
            text(
                "INSERT INTO users (name, email, password_hash) "
                "VALUES ('Constraint User', 'constraint@example.com', 'hash') "
                "RETURNING id"
            )
        ).scalar_one()
        order_id = connection.execute(
            text(
                "INSERT INTO orders "
                "(user_id, order_number, order_date, status, total_amount) "
                "VALUES (:user_id, 'RX-MIG-1001', now(), 'processing', 10.00) "
                "RETURNING id"
            ),
            {"user_id": user_id},
        ).scalar_one()
        document_id = connection.execute(
            text(
                "INSERT INTO knowledge_documents "
                "(title, content, category) "
                "VALUES ('Migration test', 'Migration test content', 'Testing') "
                "RETURNING id"
            )
        ).scalar_one()

    _assert_rejected(
        migrated_database,
        "INSERT INTO users (name, email, password_hash) "
        "VALUES ('Duplicate', 'constraint@example.com', 'hash')",
        None,
        IntegrityError,
        "uq_users_email",
    )
    _assert_rejected(
        migrated_database,
        "INSERT INTO users (name, email, password_hash) "
        "VALUES ('Uppercase', 'Uppercase@example.com', 'hash')",
        None,
        IntegrityError,
        "ck_users_email_lowercase",
    )
    _assert_rejected(
        migrated_database,
        "INSERT INTO users (name, email, password_hash, role) "
        "VALUES ('Bad role', 'bad-role@example.com', 'hash', 'owner')",
        None,
        IntegrityError,
        "ck_users_role",
    )
    _assert_rejected(
        migrated_database,
        "INSERT INTO orders "
        "(user_id, order_number, order_date, status, total_amount) "
        "VALUES (:user_id, 'RX-MIG-1002', now(), 'processing', -1.00)",
        {"user_id": user_id},
        IntegrityError,
        "ck_orders_total_amount_non_negative",
    )
    _assert_rejected(
        migrated_database,
        "INSERT INTO order_items "
        "(order_id, product_name, quantity, unit_price) "
        "VALUES (:order_id, 'Invalid quantity', 0, 1.00)",
        {"order_id": order_id},
        IntegrityError,
        "ck_order_items_quantity_positive",
    )
    _assert_rejected(
        migrated_database,
        "INSERT INTO knowledge_chunks "
        "(chunk_index, content, embedding, embedding_model) "
        "VALUES (0, 'No source', CAST(:embedding AS vector), 'test-model')",
        {"embedding": "[" + ",".join(["0.5"] * 384) + "]"},
        IntegrityError,
        "ck_knowledge_chunks_exactly_one_source",
    )
    _assert_rejected(
        migrated_database,
        "INSERT INTO knowledge_chunks "
        "(document_id, chunk_index, content, embedding, embedding_model) "
        "VALUES (:document_id, 0, 'Wrong dimensions', "
        "'[0.1,0.2,0.3]'::vector, 'test-model')",
        {"document_id": document_id},
        DataError,
        "dimensions",
    )
    _assert_rejected(
        migrated_database,
        "INSERT INTO refresh_tokens "
        "(user_id, token_hash, expires_at) "
        "VALUES (:user_id, :token_hash, now() + interval '1 day')",
        {"user_id": user_id, "token_hash": "x" * 63},
        IntegrityError,
        "ck_refresh_tokens_token_hash_length",
    )


def test_foreign_keys_restrict_orders_and_cascade_items(
    migrated_database: Engine,
) -> None:
    with migrated_database.begin() as connection:
        user_id = connection.execute(
            text(
                "INSERT INTO users (name, email, password_hash) "
                "VALUES ('FK User', 'fk-user@example.com', 'hash') "
                "RETURNING id"
            )
        ).scalar_one()
        order_id = connection.execute(
            text(
                "INSERT INTO orders "
                "(user_id, order_number, order_date, status, total_amount) "
                "VALUES (:user_id, 'RX-MIG-2001', now(), 'processing', 12.00) "
                "RETURNING id"
            ),
            {"user_id": user_id},
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO order_items "
                "(order_id, product_name, quantity, unit_price) "
                "VALUES (:order_id, 'Cascade item', 1, 12.00)"
            ),
            {"order_id": order_id},
        )

    _assert_rejected(
        migrated_database,
        "DELETE FROM users WHERE id = :user_id",
        {"user_id": user_id},
        IntegrityError,
        "fk_orders_user_id_users",
    )

    with migrated_database.begin() as connection:
        connection.execute(
            text("DELETE FROM orders WHERE id = :order_id"),
            {"order_id": order_id},
        )
        remaining = connection.execute(
            text(
                "SELECT count(*) FROM order_items WHERE order_id = :order_id"
            ),
            {"order_id": order_id},
        ).scalar_one()
        connection.execute(
            text("DELETE FROM users WHERE id = :user_id"),
            {"user_id": user_id},
        )

    assert remaining == 0
