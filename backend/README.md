# Resolvix Backend

FastAPI backend for the Resolvix AI customer-support application, backed by
PostgreSQL 18 with pgvector. It provides a modular API foundation, JWT
authentication, role-based authorization, a tested repository/service layer,
local-embedding semantic RAG over FAQs and policy documents, and a controlled
tool-calling agent for authenticated order lookups.

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
| `LLM_PROVIDER` | no | `gemini` | `gemini` (hosted) or `ollama` (local) |
| `LLM_MODEL` | no | `gemini-3.5-flash-lite` | Gemini model identifier |
| `GEMINI_API_KEY` | for Gemini | none | Gemini API key from Google AI Studio |
| `OLLAMA_BASE_URL` | for Ollama | `http://localhost:11434` | Local Ollama server |
| `OLLAMA_MODEL` | for Ollama | `llama3.2:3b` | Model already pulled locally |
| `LLM_TIMEOUT` | no | `60` | Provider request timeout in seconds |
| `LLM_TEMPERATURE` | no | `0.7` | Sampling temperature |
| `LLM_MAX_TOKENS` | no | `2048` | Maximum generated tokens |
| `EMBEDDING_MODEL` | no | `sentence-transformers/all-MiniLM-L6-v2` | Local embedding model (must return 384 dimensions) |
| `EMBEDDING_DEVICE` | no | `cpu` | `cpu` or a torch device such as `cuda` |
| `EMBEDDING_BATCH_SIZE` | no | `32` | Chunks encoded per model batch |
| `KNOWLEDGE_CHUNK_MAX_TOKENS` | no | `200` | Maximum model tokens per chunk (below the 256-token limit) |
| `KNOWLEDGE_CHUNK_OVERLAP_TOKENS` | no | `40` | Token overlap between consecutive chunks |
| `RAG_TOP_K` | no | `4` | Nearest chunks retrieved per customer query |
| `RAG_MAX_DISTANCE` | no | `0.7` | Cosine-distance cutoff; farther chunks are ignored |

Application settings live in `app/core/config.py`.

## LLM providers

The chat service depends on one async provider interface; vendor code stays in
`app/ai/providers/`. Select the active provider with `LLM_PROVIDER`:

```env
# Hosted Gemini
LLM_PROVIDER=gemini
LLM_MODEL=gemini-3.5-flash-lite
GEMINI_API_KEY=your-key-here
```

```env
# Local Ollama (no API key)
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2:3b
```

Gemini keys are created at <https://aistudio.google.com/apikey>. Ollama is
installed from <https://ollama.com/download>; pull the selected model once with
`ollama pull llama3.2:3b`.

The selected model must support tool/function calling. The configured
`gemini-3.5-flash-lite` model and Ollama's `llama3.2:3b` both provide that
capability. If you switch either model, choose one with tool calling enabled,
otherwise the model will not request the registered order lookup.

`GEMINI_API_KEY` takes precedence over `LLM_API_KEY`. Keys and private
endpoints belong in `backend/.env` only. `.env.example` contains placeholders and
is the only environment file committed.

Provider selection is evaluated per request. Gemini uses the official
`google-genai` SDK, while Ollama uses its native `/api/chat` HTTP endpoint.
Both adapters translate the same provider-neutral tool definitions into their
native function/tool-calling formats and normalize model-requested calls back
into application-owned tool calls. Timeouts, rate limits, missing models,
connection failures, and malformed responses are converted into one of the
normalized errors in `app/ai/providers/base.py`. The chat service logs the
failure and persists a controlled fallback assistant reply instead of exposing
vendor details.

## Agent tools

Tools live in `app/tools/` and are intentionally separate from provider code:

- `base.py` defines trusted `ToolContext`, structured `ToolOutcome`, and the
  `Tool` contract.
- `order_tools.py` owns the `get_order_details` definition, argument schema,
  validation, and PostgreSQL lookup.
- `registry.py` is the allow-list. A model can only execute a tool whose name
  is registered; unknown names, malformed arguments, oversized arguments, and
  unexpected failures return controlled tool results.

`get_order_details` accepts only an `order_number` from the model. The
authenticated user id comes from the verified bearer token through
`ToolContext`; it is never a model argument. The parent order is queried with an
ownership-scoped SQLAlchemy statement, ownership is checked explicitly, and
order items are fetched only after that check. Not-found and cross-customer
lookups return the same non-disclosing result. The tool returns status,
shipping status, estimated delivery, order date, total, and line items.

During a chat request the service runs a bounded loop:

1. send recent history, policy context, and tool schemas to the provider;
2. validate the requested tool name and arguments;
3. execute the allow-listed backend function with the trusted request context;
4. send the structured tool result back to the model;
5. persist the final customer-visible reply.

At most three tool rounds are executed. Repeated requests, provider failures,
database errors, invalid arguments, and unknown tools never expose raw vendor,
SQL, or internal exception details. Customer-visible assistant metadata records
`tool_calls` (name, validated arguments, status, and error code) and
`tool_rounds`; tool-result payloads are not stored as separate customer
messages.

## Database

```powershell
# Apply all migrations
.\venv\Scripts\python.exe -m alembic upgrade head

# Generate/upgrade the synthetic development data (safe to run repeatedly)
.\venv\Scripts\python.exe -m scripts.seed

# Chunk FAQs/documents, embed them, and upsert knowledge_chunks
.\venv\Scripts\python.exe -m scripts.index_knowledge

# Prove the relational and vector features still work
.\venv\Scripts\python.exe -m scripts.verify

# Ensure models and migrations are in sync
.\venv\Scripts\python.exe -m alembic check
```

The schema contains eight application tables:

`users`, `conversations`, `messages`, `orders`, `order_items`, `faqs`,
`knowledge_documents`, `knowledge_chunks`.

`knowledge_chunks.embedding` is `VECTOR(384)` with an HNSW cosine-distance
index. The seed creates the FAQ/document sources but does not load the embedding
model; run `scripts.index_knowledge` after seeding or after changing source
content. The first run downloads `all-MiniLM-L6-v2` (about 90 MB) to the local
Hugging Face cache; later runs reuse it and skip unchanged sources.

## Knowledge ingestion and RAG

`app/knowledge/` contains the pipeline and has no FastAPI or provider
dependencies, so ingestion and retrieval can be tested independently:

| Module | Responsibility |
|---|---|
| `embeddings.py` | Lazy local model load, 384-dimension validation, normalized vectors, tokenizer access |
| `chunking.py` | Ordered, token-aware chunks with overlap; FAQs become one `Q:`/`A:` unit |
| `ingestion.py` | Atomic per-source sync: index, refresh, skip, delete, or report a failure |
| `retrieval.py` | Embed the query, run cosine search, return content and source metadata |
| `grounding.py` | Format retrieved chunks into a reference-material system message |

Every chunk stores its content, exactly one of `faq_id`/`document_id`,
`chunk_index`, the normalized embedding, `embedding_model`, and
`source_updated_at`. FAQ and document chunks use the same embedder as customer
queries, so vectors are comparable.

Retrieval uses exact pgvector cosine distance
(`embedding <=> query_vector`) ordered ascending, limited to `RAG_TOP_K`, and
filtered by `RAG_MAX_DISTANCE`. Only chunks from active sources whose
`source_updated_at` matches the source's current `updated_at` are eligible. That
version check means an edited source whose re-index failed is not served with
stale text. Search also filters on `embedding_model`, so chunks built by a
different model are never compared against the active model's query vectors.

Re-indexing is safe to repeat:

- unchanged text and model: skipped without re-embedding;
- metadata-only source changes: chunk version refreshed without re-embedding;
- content changes: embeddings generated first, then old chunks deleted and new
  rows inserted in one transaction;
- inactive or deleted sources: chunks removed during the next sync, and always
  excluded from retrieval.

`scripts.index_knowledge --force` re-embeds every source. The command exits
non-zero if any source fails, and prints a per-source failure line. Ingestion is
not run automatically at API startup.

Chat retrieval is best-effort: if embedding or the database search fails, the
service logs the error and answers without reference material. Generated
assistant messages record `metadata.grounded` (boolean) and
`metadata.sources` (source type, id, title, category, chunk index, distance) so
responses can be audited against the retrieved chunks.

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
| POST | `/conversations/{id}/messages` | bearer | Save a customer message and generate an assistant reply (`201`) |
| GET | `/orders` | bearer | List only the caller's orders |
| GET | `/orders/{order_number}` | bearer | Read an owned order (`404` for another customer) |
| GET | `/admin/users` | admin | List all users (no password hashes) |
| GET | `/admin/orders` | admin | List all orders |
| GET | `/admin/knowledge/faqs` | admin | List FAQs including inactive entries |
| GET | `/admin/knowledge/documents` | admin | List documents including inactive entries |

Customers receive `403` on admin endpoints. Another customer's order or
conversation returns `404`, which avoids revealing that the record exists.

Conversation creation takes its owner from the bearer token. Sending a message
trims and validates the content, retrieves relevant FAQ/policy chunks with the
local embedding model, stores the customer message, sends the recent history
plus the customer-support system prompt and retrieved reference material to the
configured provider, stores the generated assistant reply, sets the first
message as the conversation title, and advances the conversation timestamp.

Generated messages include `metadata.source = "llm"`, the provider, model,
finish reason, token usage, grounding status, retrieved source citations, the
id of the message they answer, and `tool_calls`/`tool_rounds` when the model
used a tool. When a provider fails, the reply is stored with
`metadata.source = "fallback"` and `metadata.fallback = true`. If the model keeps
requesting tools past the round limit, the stored reply uses
`metadata.source = "tool_limit"` with `error = "tool_round_limit"`. In both
cases the API still returns `201` so the customer message and a useful response
remain in the conversation.

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
  chronological reload, and provider-generated assistant replies;
- provider request construction, response normalization, and normalized error
  mapping for Gemini and Ollama, including native tool declarations, tool calls,
  and tool-result messages;
- provider selection through configuration and the generic API-key fallback;
- controlled fallback replies when a provider fails;
- order tool lookup of status, shipping status, estimated delivery, and items
  from PostgreSQL;
- allow-list rejection of unknown tools and invalid/extra arguments;
- cross-customer order denial without item retrieval or data disclosure;
- database-error sanitization and bounded tool rounds;
- message validation and 404s for another customer's conversation;
- local embedding model contract (384 dimensions, 256-token limit) and
  no-truncation guards;
- token-aware chunking, overlap, FAQ units, and ordering;
- paraphrased return/refund/shipping/payment/warranty queries retrieving the
  expected chunks;
- chunk persistence, source versioning, unchanged-source skips, content
  replacement, embedding-model mismatch exclusion, failed re-index exclusion,
  and inactive-source exclusion;
- grounded prompt construction and `metadata.grounded`/`metadata.sources`
  persistence, plus ungrounded fallback when retrieval fails;
- database health failures and sanitized internal errors;
- Swagger/OpenAPI documentation and the bearer security scheme.

The RAG tests load the real local embedding model, so the first test run can
take longer while the model is cached. They create sources in the
`phase5-test-` category and remove them afterwards.

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
  services/             authentication, ownership, chat, and admin rules
  ai/                   provider abstraction, Gemini/Ollama adapters, prompts
  knowledge/            ingestion and retrieval (Phase 5)
  tools/                allow-listed agent tools (Phase 6)
  main.py               FastAPI app, routers, CORS, sanitized error handler
migrations/             Alembic environment and versioned migrations
scripts/                seed and verification scripts
tests/                  API and security tests
```

Design notes and the ERD: [`../docs/database-design.md`](../docs/database-design.md).
