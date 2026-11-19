#!/bin/sh
# Reproducible backend startup: wait for PostgreSQL, migrate, seed, index.
set -eu

echo "Waiting for PostgreSQL..."
python - <<'PY'
import time

from sqlalchemy import text

from app.db.session import engine

last_error: Exception | None = None
for attempt in range(1, 61):
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        print("PostgreSQL is ready.")
        break
    except Exception as error:  # noqa: BLE001 - startup retry loop
        last_error = error
        print(
            f"PostgreSQL not ready ({attempt}/60): "
            f"{type(error).__name__}",
            flush=True,
        )
        time.sleep(2)
else:
    raise SystemExit(f"PostgreSQL did not become ready: {last_error}")
PY

echo "Applying database migrations..."
python -m alembic upgrade head

if [ "${SEED_DATABASE:-true}" = "true" ]; then
    echo "Seeding synthetic demo data (idempotent)..."
    python -m scripts.seed
fi

if [ "${INDEX_KNOWLEDGE:-true}" = "true" ]; then
    echo "Synchronizing knowledge embeddings..."
    python -m scripts.index_knowledge
fi

echo "Starting API server..."
exec "$@"
