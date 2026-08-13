# Checkpoint 08 - Typed Streaming and Operational Progress

| Field | Value |
|---|---|
| Status | In review |
| Date | 2026-08-13 |
| Branch | `codex/typed-chat-streaming` |
| Pull request | [#8 - Add typed chat streaming and progress events](https://github.com/Ajbil/agentic-chatbot-fastapi/pull/8) |
| Implementation commit | [`ef1f826`](https://github.com/Ajbil/agentic-chatbot-fastapi/commit/ef1f826) |

## Objective

Stream safe operational progress and final-answer fragments from FastAPI to Streamlit while preserving the typed API, evidence ownership, retry behavior, and atomic conversation history established by earlier checkpoints.

## Why this checkpoint came next

The application already had stable request, context, and search-evidence contracts, but the UI waited for one complete response. Search could take longer than the frontend's single 30-second timeout while giving no indication that useful work was occurring.

Checkpoint 07 deliberately defined search execution and provenance before streaming. That gives this checkpoint real domain events to expose instead of vague “thinking” messages or raw framework traces.

## Starting condition

- `POST /chat` returned one JSON document after the entire agent run.
- Streamlit used one timeout for connection, provider work, and response reading.
- LangChain's internal model and tool steps were not exposed.
- A failed request had no partial assistant presentation state.
- Successful turns were already committed atomically with context and search evidence.

## Plan

1. Define a strict version-one stream-event union.
2. Keep `POST /chat` and add `POST /chat/stream` using NDJSON.
3. Validate predictable failures before starting the stream.
4. Translate LangChain token and step updates into application-owned events.
5. Suppress intermediate tool-decision prose and private reasoning.
6. Validate ordering and terminal invariants in the frontend client.
7. Stream safe output through Streamlit without prematurely committing history.
8. Preserve incomplete output separately when a stream fails.
9. Add offline contract, adapter, API, transport, session, and UI regression tests.

## Decisions and alternatives

### Add a new endpoint

- **Decision:** Preserve synchronous `POST /chat` and add `POST /chat/stream`.
- **Reason:** A single JSON response and an event sequence have different parsing and failure semantics.
- **Alternative:** Change `/chat` in place.
- **Tradeoff:** The backend maintains two delivery paths.
- **Revisit when:** All supported clients use streaming and a versioned API migration is planned.

### Use NDJSON for this client topology

- **Decision:** Send one compact JSON event per line as `application/x-ndjson`.
- **Reason:** The operation is a POST consumed by Python `requests`; NDJSON is incremental, independently validatable, and requires no new dependency.
- **Alternatives:** SSE, WebSockets, or polling.
- **Tradeoff:** The protocol does not provide browser `EventSource` reconnection or bidirectional messaging.
- **Revisit when:** A browser-native JavaScript client or strong interactive cancellation becomes a requirement.

### Own the public event vocabulary

- **Decision:** Publish `started`, `status`, `delta`, `complete`, and `error` events with version and contiguous sequence numbers.
- **Reason:** LangChain events are framework implementation details and may contain unstable or sensitive fields.
- **Alternative:** Pass raw graph events to clients.
- **Tradeoff:** The adapter needs maintenance when useful internal events change.
- **Revisit when:** Multiple workflows reveal a broader application event model.

### Expose operations, not chain-of-thought

- **Decision:** Allow-list model, search, source-processing, and finalization stages.
- **Reason:** Users need latency feedback, not private reasoning tokens or provider internals.
- **Alternative:** Display every agent event or label the stream “thinking.”
- **Tradeoff:** Progress is deliberately coarse.
- **Revisit when:** A new tool has a user-meaningful, safe lifecycle stage.

### Buffer tool-decision model passes

- **Decision:** Do not release text from a model pass that ends in a tool call; release fragments only from the final no-tool-call pass.
- **Reason:** Intermediate prose may not belong to the authoritative answer.
- **Alternative:** Forward all text immediately.
- **Tradeoff:** Search-enabled answers may begin displaying text later than single-pass answers.
- **Revisit when:** An explicit LangGraph final-answer node makes final-token identity unambiguous.

### Keep partial presentation outside history

- **Decision:** Preserve partial text on `FailedTurn`, clearly label it incomplete, and never include it in canonical history.
- **Reason:** Visible bytes are not proof of a successfully completed turn.
- **Alternative:** Commit whatever arrived before failure.
- **Tradeoff:** Retrying repeats the request instead of continuing the partial answer.
- **Revisit when:** The backend supports durable run IDs and resumable generation.

### Separate connection and idle-read timeouts

- **Decision:** Retain the 30-second connection/request setting and add a 120-second streaming idle-read timeout.
- **Reason:** A live stream may legitimately run longer than 30 seconds, while a stream that produces no bytes still needs a bound.
- **Alternative:** Disable timeouts or use one total timeout.
- **Tradeoff:** `requests` does not enforce an overall operation deadline with this tuple.
- **Revisit when:** Production latency objectives define connect, idle, and total deadlines.

## Implementation outcome

- Added a frozen, extra-forbidden Pydantic stream-event union with a discriminating `type` field.
- Added a versioned NDJSON endpoint without breaking the synchronous endpoint.
- Moved credential and agent construction into an eager preparation boundary.
- Consumed LangGraph v2 `messages` and `updates` modes through an application adapter.
- Added safe operational stages and final-answer delta reconciliation.
- Distinguished pre-stream HTTP errors from terminal in-stream errors.
- Added strict frontend sequence, model, terminal, schema, and assembled-reply validation.
- Added progressive Streamlit output with a distinct idle-read timeout.
- Kept incomplete assistant output visible but outside committed conversation history.
- Added no runtime dependency.

## Validation evidence

- The pre-change baseline contained 119 passing offline tests.
- Contract tests reject unknown versions, types, stages, extra fields, blank deltas, and invalid sequences.
- Agent tests prove tool-decision prose is suppressed while final answer fragments and safe search stages are retained.
- Backend tests prove contiguous events, NDJSON media type, terminal completion, and sanitized mid-stream failure.
- Frontend tests cover timeout tuples, HTTP errors, partial errors, malformed ordering, premature EOF, and answer reconciliation.
- Session and Streamlit tests preserve atomic commits, retry behavior, source ownership, and existing history behavior.
- No automated test calls Groq, OpenAI, or Tavily.
- `python -m pytest -q`: 134 tests pass in the locked environment.
- The application modules compile successfully with Python 3.12.
- [GitHub Actions run `31703830904`](https://github.com/Ajbil/agentic-chatbot-fastapi/actions/runs/31703830904) passed on the draft pull request in a clean Ubuntu/Python 3.12 environment.

## Senior-engineering lessons

### HTTP success and operation success diverge during streaming

After response headers are sent, the server cannot change the HTTP status. A stream therefore needs an application-level terminal event that proves success or failure.

### Streaming is a protocol, not a UI animation

Versioning, ordering, termination, validation, and reconciliation make partial delivery trustworthy. Rendering chunks without those invariants merely moves corruption closer to the user.

### Framework telemetry is not a public contract

Internal graph events optimize framework execution. Public events should express stable product meaning and expose only fields the application is willing to support.

### Perceived state and durable state can differ

The user may see partial output before the application owns a valid answer. Explicit commit semantics keep visible progress from silently becoming conversational truth.

### Backpressure can begin with iteration

A pull-based generator produces the next item as the consumer advances. This bounds buffering naturally, although it is not a substitute for production queue, proxy, and provider-flow analysis.

### Automatic retries can duplicate expensive work

A chat POST can spend money and invoke tools. Reconnecting invisibly could repeat those effects, so retry remains an explicit user decision.

## Applying this elsewhere

- Define terminal success and failure before adding a streaming transport.
- Version and validate every event at trust boundaries.
- Keep internal telemetry separate from public product semantics.
- Reconcile streamed fragments with the authoritative final record.
- Decide when partially visible work becomes durable state.
- Separate connection, idle, and total deadline concepts.
- Make retries explicit for non-idempotent operations.
- Test arbitrary chunking, malformed order, premature EOF, and mid-stream failure.

## Common mistakes

- Treating HTTP `200` as proof that a stream completed.
- Sending raw provider or orchestration events directly to the browser.
- Exposing chain-of-thought under the name “progress.”
- Committing partial output to conversation history.
- Allowing sequence gaps or multiple terminal events.
- Automatically reconnecting a paid, non-idempotent request.
- Using a short total-response timeout as a streaming idle timeout.
- Introducing WebSockets when the server only needs one-way delivery.
- Assuming `async` alone makes synchronous provider calls non-blocking.

## Explain-back questions

1. Why can an HTTP `200` stream still end in application failure?
2. Why must a stream contain exactly one terminal event?
3. Why does NDJSON fit this Python POST client better than browser `EventSource`?
4. When would WebSockets become justified?
5. Why are raw LangChain events unsuitable as the public API?
6. What separates operational progress from chain-of-thought?
7. Why might text from a tool-decision model pass not belong to the final answer?
8. Why must the final reply equal the concatenated delta text?
9. Why is partial output visible but excluded from conversation history?
10. What backpressure does a synchronous generator provide?
11. Why is automatic reconnection unsafe for this request?
12. How do connection, idle-read, and total timeouts differ?
13. Why would converting only the FastAPI function to `async` not make all dependencies non-blocking?
14. What additional architecture is required for strong cancellation or stream resumption?

## Deferred work

- Strong cancellation needs durable run identity and cooperative cancellation across every dependency.
- Resumption needs stored ordered events, authorization, expiry, and idempotency policy.
- Immediate final-answer tokens during multi-pass search are safer after an explicit LangGraph final-answer node exists.
- Production deployment must verify reverse-proxy buffering and idle-timeout settings.
- Generic tool progress should wait for a second tool to reveal real common semantics.
- Claim-level grounding, provider-specific errors, observability, and persistent conversations remain separate checkpoints.
