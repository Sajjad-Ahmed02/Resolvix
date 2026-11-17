# Agent orchestration and conversation context

Phase 7 moves customer-support coordination out of the HTTP/service layer and
into `backend/app/ai/`. The API still validates ownership and persists rows, but
one orchestrator owns context assembly, routing, capability execution, provider
calls, and controlled failure handling.

## Components

| Module | Responsibility |
|---|---|
| `app/ai/context.py` | Build a bounded provider history from recent messages and recover safe routing hints such as the last successful order number. |
| `app/ai/routing.py` | Deterministic intent detection, order-number extraction, capability mapping, follow-up inheritance, and clarification routes. |
| `app/ai/orchestrator.py` | Preflight capabilities, the bounded model/tool loop, duplicate and limit guards, provider fallback, and unsupported-success guards. |
| `app/tools/order_tools.py` | `get_order_details(order_number)`, scoped to the authenticated customer. |
| `app/tools/knowledge_tools.py` | `search_knowledge_base(query)`, returning citation-bearing policy/FAQ passages. |
| `app/tools/registry.py` | Allow-list, argument validation, async execution, route subsets, and compact audit records. |

## One turn

1. `POST /conversations/{id}/messages` verifies that the conversation belongs to
   the token subject.
2. The service loads at most `AGENT_CONTEXT_MESSAGE_LIMIT` recent rows, commits
   the new customer message, and starts the orchestrator.
3. `build_conversation_context` keeps only recent user/assistant turns within
   `AGENT_MAX_HISTORY_MESSAGES` and `AGENT_MAX_HISTORY_CHARS`. Tool rows are
   excluded from the provider dialogue but inspected for routing hints.
4. `resolve_route` produces one intent and a finite capability set. Missing
   required details and ambiguous requests return a clarification without a
   provider call.
5. Approved preflight capabilities run through the route's registry subset:
   an order lookup when an order number is known, or a knowledge search for
   policy/FAQ intents.
6. The provider receives the system rules, trusted preflight results, the
   bounded history, and the current message. Only the route's tools are offered.
7. Model-requested tools are allow-list checked and argument validated before
   execution. Repeating the same name and arguments returns
   `duplicate_tool_call` without running the backend function again.
8. The final reply is persisted, along with useful tool rows and assistant
   metadata. The conversation timestamp advances.

## Routing table

| Intent | Capabilities | Notes |
|---|---|---|
| Order status | order lookup, LLM | Reuses the last successful order number for follow-ups such as "When will it arrive?" |
| Order items | order lookup, LLM | Same order context recovery |
| Return/refund policy | knowledge search, LLM | Includes return, refund, exchange, warranty, and damaged-item questions |
| Shipping FAQ | knowledge search, LLM | Shipping, delivery, carrier, and tracking questions |
| Payment FAQ | knowledge search, LLM | Payment, billing, invoice, and checkout questions |
| General | LLM | No backend capability beyond the model |
| Ambiguous or missing order number | ask for details | Deterministic clarification; no provider call |

A follow-up inherits the previous supported intent only when its own text is
generic. Order follow-ups also reuse the last successfully looked-up order
number. Policy follow-ups add the earlier question to the new retrieval query so
"what about opened items?" keeps the original topic.

## Context and persistence

`AGENT_CONTEXT_MESSAGE_LIMIT` bounds the database read. Context assembly then
applies a message-count limit and a character budget, dropping the oldest turns
first and truncating only an oversized newest message. A leading assistant turn
is removed so provider dialogues start with a user message.

Persisted rows:

- `user`: the customer message.
- `tool`: one row per executed preflight or model-requested capability. Metadata
  includes the tool name, validated arguments, status, error code, and a compact
  order summary or knowledge citations. Duplicate and limit-blocked attempts are
  audited on the assistant message but are not stored as tool rows.
- `assistant`: the customer-visible reply. Metadata includes `source`,
  `provider`, `model`, `intent`, `capabilities`, `grounded`, `sources`,
  `context_messages`, and `tool_calls`/`tool_rounds` when relevant.

Assistant `source` values:

| Source | Meaning |
|---|---|
| `llm` | Normal generated reply |
| `clarification` | Deterministic request for missing details |
| `fallback` | Provider failed; controlled fallback was stored |
| `tool_limit` | A tool round or call limit stopped the loop |
| `guarded` | A reply that contradicted a failed order lookup was replaced |

## Failure handling

- A provider failure produces a safe fallback and never leaks vendor details.
- A tool failure produces a structured `ToolOutcome`; the model is told what
  failed and may still answer from other available information.
- A failed knowledge search forces an ungrounded reply and a "cannot confirm"
  instruction.
- A failed order lookup is independent from provider failure. If the model then
  claims a status or delivery without a successful order result, the
  orchestrator replaces the claim with a controlled lookup-failure reply.
- Unknown tools, invalid or extra arguments, oversized arguments, and unexpected
  backend exceptions are converted into controlled tool results.
- `AGENT_MAX_TOOL_ROUNDS` and `AGENT_MAX_TOOL_CALLS` bound the model/tool loop.

## Tests

Phase 7 coverage lives in:

- `tests/test_agent_routing.py`
- `tests/test_agent_context.py`
- `tests/test_knowledge_tools.py`
- `tests/test_agent_orchestration.py`
- `tests/test_conversations_api.py` (updated end-to-end behavior)
