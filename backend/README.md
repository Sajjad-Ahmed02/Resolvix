# Resolvix Backend

FastAPI backend for the Resolvix AI customer-support application, backed by
PostgreSQL 18 with pgvector. It provides a modular API foundation, JWT
authentication, role-based authorization, and a tested repository/service
layer.

## Requirements

- Python 3.14 (the project virtual environment is `backend/venv`)
- PostgreSQL 18 with the `vector` extension
- The database URL and JWT secret configured in `backend/.env`

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
# generate a JWT secret and paste it after JWT_SECRET_KEY= in .env:
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

`backend/.env` is gitignored. Never commit real database passwords, JWT
secrets, or provider API keys.

## Configuration

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `DATABASE_URL` | yes | none | SQLAlchemy PostgreSQL URL (`postgresql+psycopg://...`) |
| `JWT_SECRET_KEY` | yes | none | HMAC signing key, at least 32 characters |
| `JWT_ALGORITHM` | no | `HS256` | Allowed values: `HS256`, `HS384`, `HS512` |
| `JWT_ISSUER` | no | `resolvix` | Validated `iss` claim |
| `JWT_AUDIENCE` | no | `resolvix-api` | Validated `aud` claim |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | no | `30` | Access-token lifetime |
| `DB_CONNECT_TIMEOUT` | no | `5` | PostgreSQL connect timeout in seconds |
| `CORS_ORIGINS` | no | Vite localhost origins | JSON list of allowed frontend origins |

Application settings live in `app/core/config.py`.

## Database

```powershell
# Apply all migrations
.\venv\Scripts\python.exe -m alembic upgrade head

# Generate/upgrade the synthetic development data (safe to run repeatedly)
.\venv\Scripts\python.exe -m scripts.seed

# Prove the relational and vector features still work
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
- Health (includes PostgreSQL check): http://localhost:8000/health

## Authentication

Public registration is intentionally unavailable. Only pre-seeded accounts can
log in.

| Role | Email | Password |
|---|---|---|
| Admin | `admin@resolvix.local` | `Admin123!` |
| Customer | `alice.morgan@example.com` | `Customer123!` |

These credentials are development-only and use synthetic data.

```powershell
$body = @{
  email = "alice.morgan@example.com"
  password = "Customer123!"
} | ConvertTo-Json

$login = Invoke-RestMethod -Method Post `
  -Uri http://localhost:8000/auth/login `
  -ContentType "application/json" `
  -Body $body

$headers = @{ Authorization = "Bearer $($login.access_token)" }
Invoke-RestMethod -Uri http://localhost:8000/auth/me -Headers $headers
```

In Swagger, call `POST /auth/login`, copy `access_token`, click **Authorize**,
paste the token, and confirm. The HTTP bearer scheme adds the `Bearer` prefix.

Security properties:

- New passwords are hashed with salted **Argon2id**. Legacy Phase 1 PBKDF2
  hashes still verify and are upgraded transparently after a successful login.
- JWTs are signed with HMAC, include `sub`, `role`, `type`, `iat`, `nbf`,
  `exp`, `iss`, `aud`, and `jti`, and are validated on every protected call.
- The current-user dependency reloads the user from PostgreSQL, so role
  changes and deleted accounts take effect immediately. The token's role claim
  is informational only.
- Customer identity always comes from the token subject. Routes never accept a
  `user_id` that can override it.
- Logout is stateless: the client discards the token. Refresh-token revocation
  is not implemented yet.
- Unknown emails and wrong passwords return the same `401` response.

## Endpoints

| Method | Endpoint | Access | Purpose |
|---|---|---|---|
| GET | `/` | public | API root |
| GET | `/health` | public | API and PostgreSQL health (`503` when DB is down) |
| POST | `/auth/login` | public | Authenticate and issue a JWT |
| GET | `/auth/me` | bearer | Return the authenticated user and role |
| POST | `/auth/logout` | bearer | Acknowledge stateless logout (`204`) |
| GET | `/conversations` | bearer | List only the caller's conversations |
| POST | `/conversations` | bearer | Create a conversation for the caller (`201`) |
| GET | `/conversations/{id}` | bearer | Read an owned conversation and messages |
| GET | `/conversations/{id}/messages` | bearer | Read messages in an owned conversation |
| POST | `/conversations/{id}/messages` | bearer | Save a customer message and temporary assistant reply (`201`) |
| GET | `/orders` | bearer | List only the caller's orders |
| GET | `/orders/{order_number}` | bearer | Read an owned order (`404` for another customer) |
| GET | `/admin/users` | admin | List all users (no password hashes) |
| GET | `/admin/orders` | admin | List all orders |
| GET | `/admin/knowledge/faqs` | admin | List FAQs including inactive entries |
| GET | `/admin/knowledge/documents` | admin | List documents including inactive entries |

Customers receive `403` on admin endpoints. Another customer's order or
conversation returns `404`, which avoids revealing that the record exists.

Conversation creation takes its owner from the bearer token. Sending a message
trims and validates the content, stores the customer message, stores a
temporary assistant reply, sets the first message as the conversation title,
and advances the conversation timestamp. The placeholder reply is marked with
`metadata.temporary = true` so it is easy to replace when an AI provider is
connected.

## Tests

```powershell
.\venv\Scripts\python.exe -m pytest
```

The suite uses the configured PostgreSQL database, creates isolated users,
conversations, and orders, and deletes them afterwards. It covers:

- valid, wrong-password, unknown-email, and normalized-email logins;
- Argon2id hashing, legacy-hash upgrades, JWT round-trips, expiry, tampering,
  wrong token type, and wrong signing key;
- missing/invalid tokens on protected endpoints;
- customer/admin authorization, forged role claims, and live role changes;
- cross-customer order and conversation isolation;
- conversation creation, message persistence, auto-titles, timestamp updates,
  chronological reload, and the temporary assistant reply;
- message validation and 404s for another customer's conversation;
- database health failures and sanitized internal errors;
- Swagger/OpenAPI documentation and the bearer security scheme.

## Layout

```
app/
  api/
    dependencies.py     JWT current-user and admin dependencies
    routes/             thin HTTP route handlers
  core/                 settings, Argon2id/JWT security helpers
  db/                   SQLAlchemy Base, engine, session, DB health check
  models/               eight SQLAlchemy models
  schemas/              Pydantic request/response schemas
  repositories/         SQL-only data access (users, conversations, messages,
                        orders, knowledge sources)
  services/             authentication, ownership, and admin business rules
  ai/                   LLM and embedding integration (later phase)
  knowledge/            ingestion and retrieval (Phase 5)
  tools/                agent tools (later phase)
  main.py               FastAPI app, routers, CORS, sanitized error handler
migrations/             Alembic environment and versioned migrations
scripts/                seed and verification scripts
tests/                  API and security tests
```

Design notes and the ERD: [`../docs/database-design.md`](../docs/database-design.md).
