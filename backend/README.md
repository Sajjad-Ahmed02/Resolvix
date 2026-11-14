# Resolvix Backend

FastAPI backend for the Resolvix AI customer-support application, backed by
PostgreSQL 18 with pgvector.

## Requirements

- Python 3.14 (the project virtual environment is `backend/venv`)
- PostgreSQL 18 with the `vector` extension
- The database URL configured in `backend/.env`

See [`../docs/pgvector-setup.md`](../docs/pgvector-setup.md) if pgvector is not
installed yet.

## Setup

```powershell
cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
# edit DATABASE_URL in .env
```

## Database

```powershell
# Apply all migrations
.\venv\Scripts\python.exe -m alembic upgrade head

# Generate the synthetic development data (safe to run repeatedly)
.\venv\Scripts\python.exe -m scripts.seed

# Prove the relational and vector features work
.\venv\Scripts\python.exe -m scripts.verify

# Ensure models and migrations are in sync
.\venv\Scripts\python.exe -m alembic check
```

The schema contains eight application tables:

`users`, `conversations`, `messages`, `orders`, `order_items`, `faqs`,
`knowledge_documents`, `knowledge_chunks`.

`knowledge_chunks.embedding` is `VECTOR(384)` with an HNSW cosine-distance
index. Chunk ingestion and embedding generation are Phase 5 work; the seed
leaves this table empty.

## Run the API

```powershell
.\venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

- API: http://localhost:8000
- Swagger: http://localhost:8000/docs
- Health: http://localhost:8000/health

## Local demo accounts

| Role | Email | Password |
|---|---|---|
| Admin | `admin@resolvix.local` | `Admin123!` |
| Customer | `alice.morgan@example.com` | `Customer123!` |

These credentials are development-only and use synthetic data.

## Layout

```
app/
  core/       settings and password hashing
  db/         SQLAlchemy Base, engine and session factory
  models/     eight SQLAlchemy models
  schemas/    Pydantic request/response schemas (later phases)
  api/        FastAPI routes (later phases)
  services/   business logic (later phases)
  repositories/ data access (later phases)
  ai/         LLM and embedding integration (later phases)
  tools/      agent tools (later phases)
migrations/   Alembic environment and versioned migrations
scripts/      seed and verification scripts
```

Design notes and the ERD: [`../docs/database-design.md`](../docs/database-design.md).
