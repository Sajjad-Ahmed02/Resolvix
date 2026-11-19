from __future__ import annotations

import logging
import time
from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings


logger = logging.getLogger(__name__)

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    connect_args={"connect_timeout": settings.DB_CONNECT_TIMEOUT},
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that provides one session per request.

    Any exception rolls the transaction back and is re-raised for the API-level
    handlers. Database failures are logged as one structured boundary event;
    response sanitization happens in ``app.main``.
    """
    with SessionLocal() as session:
        try:
            yield session
        except Exception as error:
            session.rollback()
            if isinstance(error, SQLAlchemyError):
                logger.exception(
                    "Database session failed",
                    extra={
                        "event": "database_error",
                        "operation": "database_session",
                        "error_type": type(error).__name__,
                    },
                )
            raise


def check_database_connection() -> bool:
    """Return True when PostgreSQL answers a trivial query.

    The detailed exception is logged server-side only. Callers expose a
    generic status so connection strings and credentials never reach a client.
    """
    started = time.perf_counter()
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as error:
        logger.warning(
            "Database health check failed",
            exc_info=True,
            extra={
                "event": "database_health",
                "operation": "database_health",
                "ok": False,
                "error_type": type(error).__name__,
                "duration_ms": round(
                    (time.perf_counter() - started) * 1000,
                    2,
                ),
            },
        )
        return False

    logger.info(
        "Database health check succeeded",
        extra={
            "event": "database_health",
            "operation": "database_health",
            "ok": True,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        },
    )
    return True
