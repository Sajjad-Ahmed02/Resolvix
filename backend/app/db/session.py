from __future__ import annotations

import logging
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
    """FastAPI dependency that provides one session per request."""
    with SessionLocal() as session:
        yield session


def check_database_connection() -> bool:
    """Return True when PostgreSQL answers a trivial query.

    The detailed exception is logged server-side only. Callers expose a
    generic status so connection strings and credentials never reach a client.
    """
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except SQLAlchemyError:
        logger.warning("Database health check failed", exc_info=True)
        return False
