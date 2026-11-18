# Resolvix Backend

FastAPI backend for the Resolvix AI customer-support application, backed by
PostgreSQL 18 with pgvector. It provides a modular API foundation, cookie-based
JWT authentication with revocable refresh sessions, role-based authorization,
a tested repository/service layer, local-embedding semantic RAG over FAQs and
policy documents, a controlled tool-calling agent with deterministic intent
routing, bounded conversation context, authenticated order lookups, and an
administrator API for managing the synthetic store and knowledge base.

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
| `REFRESH_TOKEN_EXPIRE_DAYS` | no | `30` | Sliding refresh-session lifetime |
| `ACCESS_TOKEN_COOKIE_NAME` | no | `resolvix_access` | HttpOnly access cookie name |
| `REFRESH_TOKEN_COOKIE_NAME` | no | `resolvix_refresh` | HttpOnly refresh cookie name |
| `COOKIE_DOMAIN` | no | host-only | Optional cookie domain for subdomain deployments |
| `COOKIE_SECURE` | no | `false` | Set `true` behind HTTPS |
| `COOKIE_SAMESITE` | no | `lax` | `lax`, `strict`, or `none` (`none` requires secure cookies) |
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
| `AGENT_CONTEXT_MESSAGE_LIMIT` | no | `100` | Recent message rows loaded before bounded context assembly |
| `AGENT_MAX_HISTORY_MESSAGES` | no | `40` | Maximum user/assistant messages sent to the provider |
| `AGENT_MAX_HISTORY_CHARS` | no | `12000` | Character budget for the provider history |
| `AGENT_MAX_TOOL_ROUNDS` | no | `3` | Maximum model/tool rounds per customer turn |
| `AGENT_MAX_TOOL_CALLS` | no | `6` | Hard tool-attempt cap per customer turn |

Application settings live in `app/core/config.py`.

## LLM providers

The support agent depends on one async provider interface; vendor code stays in
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
otherwise the model cannot request the registered order or knowledge tools.

`GEMINI_API_KEY` takes precedence over `LLM_API_KEY`. Keys and private
endpoints belong in `backend/.env` only. `.env.example` contains placeholders and
is the only environment file committed.

Provider selection is evaluated per request. Gemini uses the official
`google-genai` SDK, while Ollama uses its native `/api/chat` HTTP endpoint.
Both adapters translate the same provider-neutral tool definitions into their
native function/tool-calling formats and normalize model-requested calls back
into application-owned tool calls. Timeouts, rate limits, missing models,
connection failures, and malformed responses are converted into one of the
normalized errors in `app/ai/providers/base.py`. The orchestrator logs the
failure and persists a controlled fallback assistant reply instead of exposing
vendor details.

## Agent orchestration and tools

`app/ai/orchestrator.py` coordinates one support turn end to end. HTTP routing
and persistence stay in `app/api/` and `app/services/`; the orchestrator owns:

- bounded context construction from recent persisted messages;
- deterministic intent-to-capability routing;
- preflight execution of approved backend capabilities;
- the model -> validate -> execute -> tool-result loop;
- provider-failure fallback and unsupported-success guards.

`app/ai/context.py` loads a bounded window of recent user/assistant turns for
the provider. Tool rows stay in the stored conversation for auditing, but they
are excluded from the provider dialogue. Their safe metadata supplies routing
hints such as the last successfully looked-up order number.

`app/ai/routing.py` is the routing table:

| Customer request | Capabilities | Behavior |
|---|---|---|
| Order status or items, with an order number | `order_lookup`, `llm_response` | Run the registered order tool first, then answer from its result |
| Return/refund, shipping, or payment policy/FAQ | `knowledge_search`, `llm_response` | Run `search_knowledge_base` first, then answer from retrieved passages |
| General supported question | `llm_response` | Answer with the system rules and conversation history |
| Missing order number or ambiguous request | `ask_for_details` | Ask a deterministic clarifying question without calling the provider |

Follow-ups reuse conversation context. For example, after a successful order
lookup, "When will it arrive?" reuses the last order number. A policy follow-up
such as "What about opened items?" inherits the previous policy intent and adds
the earlier question to the knowledge query.

Tools live in `app/tools/` and are intentionally separate from provider code:

- `base.py` defines trusted `ToolContext`, structured `ToolOutcome`, and the
  asynchronous `Tool` contract.
- `order_tools.py` owns `get_order_details`: argument validation and an
  ownership-scoped PostgreSQL lookup.
- `knowledge_tools.py` owns `search_knowledge_base`: a focused `query`
  argument, citation-bearing results, and controlled unavailability errors.
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

Each turn executes at most `AGENT_MAX_TOOL_CALLS` tool attempts across at most
`AGENT_MAX_TOOL_ROUNDS` model rounds. A repeated call with identical arguments
is rejected as `duplicate_tool_call` without running the backend function.
Invalid arguments, database errors, retrieval failures, and unknown tools never
expose raw vendor, SQL, embedding, or internal exception details. A failed
policy search produces an ungrounded reply with an explicit "cannot confirm"
instruction; a failed order lookup cannot be turned into a successful status
claim.

Conversation history persists user rows, useful tool rows, and assistant rows.
Tool rows use `role = "tool"` with `metadata.tool`, validated arguments, status,
error code, and a compact order summary or knowledge citations. Assistant
metadata records `intent`, `capabilities`, grounding sources, `tool_calls`,
`tool_rounds`, and the number of context messages used. Provider failures store
`metadata.source = "fallback"`; clarification replies store
`metadata.source = "clarification"` with a reason; and a reply rewritten because
it contradicted a failed lookup stores `metadata.source = "guarded"`.

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

The schema contains nine application tables:

`users`, `refresh_tokens`, `conversations`, `messages`, `orders`,
`order_items`, `faqs`, `knowledge_documents`, `knowledge_chunks`.

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

Policy/FAQ turns use the controlled `search_knowledge_base` tool instead of
unconditional retrieval. If embedding or the database search fails, the
orchestrator logs the safe error, tells the model that reference material is
unavailable, and the reply remains ungrounded. Generated assistant messages
record `metadata.grounded` (boolean) and `metadata.sources` (source type, id,
title, category, chunk index, distance), so responses can be audited against
the retrieved chunks. The persisted tool row records the search query, result
count, and citations.

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

Browser sessions use two HttpOnly cookies:

- `resolvix_access` contains the short-lived JWT and is sent with every API
  request (`Path=/`).
- `resolvix_refresh` contains an opaque, high-entropy refresh token and is only
  sent to `/auth/*` (`Path=/auth`).

JavaScript cannot read either cookie. The refresh token is stored in PostgreSQL
only as a SHA-256 digest. `POST /auth/refresh` exchanges a valid refresh cookie
for a new access cookie and slides both the database and cookie expiry forward,
so active users stay signed in without re-entering credentials. The refresh
token is not rotated on every call, which keeps concurrent tabs from
invalidating each other.

Non-browser clients may continue to use the bearer token returned by
`POST /auth/login`. The login response still includes `access_token` for API
clients, tests, and Swagger:

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
Protected routes also accept the `Access Cookie` scheme.

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
- Logout revokes the presented refresh token and clears both cookies. It does
  not require a valid access token, so it still works after the access token
  has expired.
- Unknown emails and wrong passwords return the same `401` response.

## Endpoints

| Method | Endpoint | Access | Purpose |
|---|---|---|---|
| GET | `/` | public | API root |
| GET | `/health` | public | API and PostgreSQL health (`503` when DB is down) |
| POST | `/auth/login` | public | Authenticate; set cookies and return a JWT |
| POST | `/auth/refresh` | refresh cookie | Issue a new access cookie and slide the session expiry |
| GET | `/auth/me` | cookie or bearer | Return the authenticated user and role |
| POST | `/auth/logout` | refresh cookie | Revoke the session and clear cookies (`204`) |
| GET | `/conversations` | cookie or bearer | List only the caller's conversations |
| POST | `/conversations` | cookie or bearer | Create a conversation for the caller (`201`) |
| GET | `/conversations/{id}` | cookie or bearer | Read an owned conversation and messages |
| GET | `/conversations/{id}/messages` | cookie or bearer | Read messages in an owned conversation |
| POST | `/conversations/{id}/messages` | cookie or bearer | Save a customer message and generate an assistant reply (`201`) |
| GET | `/orders` | cookie or bearer | List only the caller's orders |
| GET | `/orders/{order_number}` | cookie or bearer | Read an owned order (`404` for another customer) |
| GET | `/admin/users` | admin | List all users (no password hashes) |
| GET | `/admin/stats` | admin | Dashboard counts |
| GET | `/admin/orders` | admin | List orders with owners and line items |
| POST | `/admin/orders` | admin | Create a synthetic order (`201`) |
| GET | `/admin/orders/{id}` | admin | Read one order with line items |
| PATCH | `/admin/orders/{id}` | admin | Update status, shipping status, or dates |
| POST | `/admin/orders/{id}/items` | admin | Add a line item and recalculate the total (`201`) |
| PATCH | `/admin/orders/{id}/items/{item_id}` | admin | Update a line item and recalculate the total |
| DELETE | `/admin/orders/{id}/items/{item_id}` | admin | Remove a line item and recalculate the total |
| GET | `/admin/knowledge/faqs` | admin | List FAQs including inactive entries |
| POST | `/admin/knowledge/faqs` | admin | Create an FAQ and index it (`201`) |
| GET | `/admin/knowledge/faqs/{id}` | admin | Read one FAQ |
| PUT | `/admin/knowledge/faqs/{id}` | admin | Update an FAQ and re-index it |
| DELETE | `/admin/knowledge/faqs/{id}` | admin | Delete an FAQ and its chunks (`204`) |
| POST | `/admin/knowledge/faqs/{id}/reindex` | admin | Re-index one FAQ (`502` on failure) |
| GET | `/admin/knowledge/documents` | admin | List documents including inactive entries |
| POST | `/admin/knowledge/documents` | admin | Create a document and generate embeddings (`201`) |
| GET | `/admin/knowledge/documents/{id}` | admin | Read one document |
| PUT | `/admin/knowledge/documents/{id}` | admin | Update a document, chunk it, and re-index it |
| DELETE | `/admin/knowledge/documents/{id}` | admin | Delete a document and its chunks (`204`) |
| POST | `/admin/knowledge/documents/{id}/reindex` | admin | Re-index one document (`502` on failure) |
| POST | `/admin/knowledge/reindex` | admin | Re-index every FAQ and document |
| GET | `/admin/conversations` | admin | List every conversation with owner and message count |
| GET | `/admin/conversations/{id}` | admin | Inspect one conversation and all messages |
| POST | `/admin/ai/test` | admin | Run a real orchestrator turn and inspect metadata |

Customers receive `403` on admin endpoints. Another customer's order or
conversation returns `404`, which avoids revealing that the record exists.

FAQ and document mutations commit the source first, then synchronize chunks and
embeddings. Their responses include `indexing.status` (`indexed`, `refreshed`,
`skipped`, `deleted`, or `failed`) and an `indexing.error` message when
embedding fails, so a failed sync is never reported as success. Dedicated
re-index endpoints return `502` with the failure reason.

Conversation creation takes its owner from the bearer token. Sending a message
trims and validates the content, checks ownership, stores the customer message,
loads a bounded recent window, resolves the intent route, executes approved
preflight capabilities (order lookup or knowledge search), sends the bounded
history plus grounded results to the configured provider, stores useful tool
rows and the generated assistant reply, sets the first message as the
conversation title, and advances the conversation timestamp.

Generated messages include `metadata.source = "llm"`, the provider, model,
finish reason, token usage, `intent`, `capabilities`, grounding status,
retrieved source citations, the id of the message they answer, the number of
context messages used, and `tool_calls`/`tool_rounds` when a backend capability
ran. When a provider fails, the reply is stored with
`metadata.source = "fallback"` and `metadata.fallback = true`. Missing order
numbers and ambiguous requests store `metadata.source = "clarification"` with a
reason. If the model keeps requesting tools past the round or call limit, the
stored reply uses `metadata.source = "tool_limit"`. The API still returns `201`
so the customer message and a useful response remain in the conversation.

## Tests

```powershell
.\venv\Scripts\python.exe -m pytest
```

The suite uses the configured PostgreSQL database, creates isolated users,
conversations, and orders, and deletes them afterwards. It covers:

- valid, wrong-password, unknown-email, and normalized-email logins;
- HttpOnly cookie issuance, `/auth/refresh` rotation, sliding expiry, and
  logout revocation;
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
- deterministic intent routing, order-number extraction and normalization, and
  follow-up inheritance for orders and policies;
- bounded conversation context, truncation, tool-row exclusion, and recovery
  of the last successful order from persisted metadata;
- controlled fallback replies when a provider fails, including later turns in
  an existing conversation;
- order tool lookup of status, shipping status, estimated delivery, and items
  from PostgreSQL, including trusted preflight lookups and follow-up reuse;
- knowledge search tool citations, invalid-query rejection, unavailable
  retrieval handling, and registry scoping;
- multi-turn order lookup -> arrival follow-up, return-policy follow-up,
  missing order-number clarification, and consecutive general turns;
- allow-list rejection of unknown tools and invalid/extra arguments;
- cross-customer order denial without item retrieval or data disclosure;
- duplicate tool-call prevention, per-round call limits, unsupported order
  success guards, database-error sanitization, and bounded tool rounds;
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
- administrator authorization on every admin route, including anonymous and
  customer requests;
- FAQ/document CRUD, chunk and embedding synchronization, source deactivation,
  re-index failures reported instead of swallowed, and retrieval exclusion of
  inactive sources;
- synthetic order creation, status updates, line-item add/edit/delete, total
  recalculation, duplicate order numbers, and unknown customers;
- conversation inspection with messages and metadata, plus admin AI testing
  through the real orchestrator with multi-turn follow-ups;
- database health failures and sanitized internal errors;
- Swagger/OpenAPI documentation for the bearer and cookie security schemes.

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
  models/               nine SQLAlchemy models
  schemas/              Pydantic request/response schemas
  repositories/         SQL-only data access (users, conversations, messages,
                        orders, knowledge sources)
  services/             authentication, ownership, conversation persistence,
                        and admin rules
  ai/                   orchestrator, routing, bounded context, prompts, and
                        Gemini/Ollama provider adapters
  knowledge/            ingestion, retrieval, and grounding
  tools/                allow-listed order and knowledge tools
  main.py               FastAPI app, routers, CORS, sanitized error handler
migrations/             Alembic environment and versioned migrations
scripts/                seed and verification scripts
tests/                  API and security tests
```

Design notes and the ERD: [`../docs/database-design.md`](../docs/database-design.md).
Agent orchestration, routing, context, and failure handling:
[`../docs/agent-orchestration.md`](../docs/agent-orchestration.md).
