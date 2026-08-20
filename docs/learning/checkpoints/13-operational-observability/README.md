# Checkpoint 13 - Privacy-Safe Operational Observability and Request Correlation

| Field | Value |
|---|---|
| Status | In review |
| Date | 2026-08-20 |
| Branch | `codex/operational-observability` |
| Pull request | [#21 - Add privacy-safe operational observability](https://github.com/Ajbil/agentic-chatbot-fastapi/pull/21) |

## Objective

Make production-like behavior diagnosable without turning telemetry into a second database of private conversations. Correlate each API response with safe structured logs, measure bounded request and agent lifecycles, and expose process-local Prometheus metrics while preserving every existing HTTP and streaming contract.

## Why this checkpoint came next

The previous checkpoints established typed boundaries, deterministic evaluation, explicit orchestration, and enforced grounding. Those controls answer what the application should do, but an operator still could not answer basic runtime questions: Which request failed? Was the failure transport-level or agent-level? Did search or citation repair run? Are streams stuck? Is context trimming common?

Observability comes before deployment because deployment without diagnostic evidence creates an opaque service. It also comes before tuning model retries or search behavior: optimization should be based on measured outcomes, latency, and failure frequency rather than anecdotes.

## Starting condition

- API failures had stable public error codes but no cross-layer request reference.
- Backend and frontend could not correlate a user's failure with one safe log record.
- There were no request, chat, streaming, search, grounding, or context metrics.
- A streaming response could return HTTP `200` and later fail, but no measurement distinguished transport completion from domain completion.
- Adding raw framework or provider logging would have risked leaking prompts, answers, search evidence, keys, and high-cardinality values.

## Plan

1. Define the telemetry privacy and label-cardinality policy before emitting data.
2. Generate one server-owned request ID for every HTTP request and return it in `X-Request-ID`.
3. Add safe JSON and local-console logging through an explicit field allowlist.
4. Measure HTTP lifecycle independently from chat-domain lifecycle.
5. Add exact-once chat and stream trackers, including active streams and first-answer-delta latency.
6. Measure search, grounding, citation repair, and context trimming using bounded labels.
7. Expose a process-local Prometheus endpoint and isolate registries in tests.
8. Carry request references through frontend error handling without exposing internal diagnostics.
9. Test concurrency, failure, disconnect, privacy, cardinality, and metric exactness offline.

## Decisions and alternatives

### Start with application-owned logs and Prometheus metrics

- **Decision:** Add Python structured logging and the Prometheus client directly at application boundaries.
- **Reason:** This creates portable, locally testable signals with no SaaS account, external network, or vendor-specific SDK. The repository owns metric meaning instead of inheriting opaque framework defaults.
- **Alternatives:** LangSmith, OpenTelemetry immediately, Sentry, or logs alone.
- **Tradeoff:** There is no distributed trace, hosted dashboard, retention, alerting, or model-token-cost view yet.
- **Revisit when:** A deployment topology and telemetry backend exist; OpenTelemetry can then export correlated traces without replacing the domain metrics.

### Generate request IDs on the server

- **Decision:** Ignore any incoming `X-Request-ID` and issue a UUID-derived lowercase hexadecimal value.
- **Reason:** Untrusted callers must not forge another request's identity or inject arbitrary values into logs. One generated value correlates response, lifecycle logs, and domain logs.
- **Alternatives:** Trust the caller, sanitize and reuse it, or use a distributed trace header.
- **Tradeoff:** A reverse proxy's correlation value is not propagated in this checkpoint.
- **Revisit when:** A trusted edge establishes authenticated trace-context propagation.

### Use pure ASGI middleware

- **Decision:** Observe response-start and final-body messages at the ASGI boundary.
- **Reason:** Completion means the final body was sent, not merely that a response object was returned. This matters for streaming, disconnects, and send failures.
- **Alternatives:** `BaseHTTPMiddleware`, endpoint decorators, or access logs only.
- **Tradeoff:** ASGI middleware is lower-level and needs lifecycle tests.
- **Revisit when:** Framework guarantees provide an equally precise and simpler streaming lifecycle hook.

### Separate HTTP and chat-domain outcomes

- **Decision:** Record transport status independently from the typed chat terminal outcome.
- **Reason:** After streaming headers are sent, a later agent failure cannot change HTTP `200`; it becomes a terminal NDJSON error. Combining those lifecycles would incorrectly count the request as an agent success.
- **Alternatives:** Infer success from HTTP status or expose one combined counter.
- **Tradeoff:** Operators must understand two related signals instead of one misleading signal.
- **Revisit when:** Never; transport and domain semantics remain distinct even if protocol details change.

### Allowlist log fields and close metric label domains

- **Decision:** Logs accept only named operational fields, and metrics use route templates, status classes, registered model keys, booleans, and enumerated outcomes.
- **Reason:** Prompts, replies, queries, URLs, exception text, request paths, and tool metadata are private or unbounded. Using them as labels causes sensitive-data exposure and cardinality growth that can destabilize a telemetry system.
- **Alternatives:** Log full request objects, attach arbitrary dictionaries, use raw paths/errors as labels, or redact after serialization.
- **Tradeoff:** Some debugging detail is intentionally unavailable.
- **Revisit when:** New fields have a documented purpose, privacy classification, bounded domain, and tests.

### Sanitize unexpected exceptions instead of logging their messages

- **Decision:** Record only exception class and bounded file/function/line frame locations.
- **Reason:** Provider and library exception messages can echo credentials, URLs, prompt fragments, or response bodies. Frame identity usually locates the code path without copying the payload.
- **Alternatives:** Standard `logger.exception`, full traceback strings, or no diagnostic location.
- **Tradeoff:** Root-cause analysis may need controlled local reproduction or a separately secured trace store.
- **Revisit when:** A security-reviewed telemetry backend supports classified, access-controlled diagnostic events.

### Create telemetry through an application factory

- **Decision:** `create_app()` accepts a fresh telemetry object and registry.
- **Reason:** Prometheus collectors reject duplicate registration in a process. Isolated registries make tests deterministic and prevent hidden global-state coupling.
- **Alternatives:** Use the default global registry or monkeypatch module globals.
- **Tradeoff:** Application assembly has one additional explicit dependency.
- **Revisit when:** Dependency injection or a deployment lifecycle container owns shared infrastructure.

### Do not add a health endpoint in this checkpoint

- **Decision:** Limit the scope to correlation, logs, and metrics.
- **Reason:** Liveness and readiness have deployment-specific semantics. A route that always returns `200` can create false operational confidence without a defined orchestrator, dependency policy, and failure action.
- **Alternatives:** Add `/health` or probe every external provider.
- **Tradeoff:** Deployment work must define probes later.
- **Revisit when:** The deployment checkpoint defines what should restart a process and what should remove it from traffic.

## Implementation walkthrough

### Request boundary

`RequestObservabilityMiddleware` generates and context-binds a request ID, adds it to response headers, records duration only after the final body message, and records an `aborted` transport if delivery does not complete. Route templates are used after routing so IDs and user-provided URL values never become metric labels.

### Domain lifecycle

Each chat endpoint creates a `ChatRunTracker`. The tracker learns the model key only after registry validation, finalizes once, and records a closed terminal outcome. Sync and stream paths share the same domain evidence. A stream increments an active gauge while producing events and observes time to the first real or buffered answer delta.

Successful typed responses supply search execution status, source counts, grounding status, repair use, estimated input size, and truncation evidence. Unknown models remain `unknown` rather than becoming attacker-controlled labels.

### Privacy-safe logs

The formatter builds records from a fixed schema. Unexpected exceptions use class names and bounded traceback frame locations, never raw messages. Domain completion records counts and states, not AI content. JSON is the deployment-oriented default; console format is a local readability option with the same field policy.

### Metrics and frontend

`GET /metrics` renders a dedicated Prometheus registry. The endpoint does not measure itself, preventing scrape traffic from distorting application-request signals. Frontend client errors retain a valid response request ID, failed-turn state stores it, and the UI displays it as a support reference.

## Verification strategy

- Concurrent requests prove generated IDs are unique and correlate headers with log records.
- Caller-supplied IDs, raw paths, unusual methods, unknown model values, prompts, replies, queries, sources, and exception messages are tested as absent from telemetry.
- Sync and stream tests assert exact metric deltas for success, search, grounding, repair, first delta, mid-stream failure, disconnect, and aborted response delivery.
- Idempotence tests prove one chat run cannot be finalized twice and active-stream gauges return to zero.
- Formatter tests run both JSON and console modes through the same allowlist.
- Existing API, streaming, frontend, evaluation, quality, and coverage gates protect prior contracts.

Final local evidence before publication:

- Dependency lock verification: passed with one intentionally added runtime package, `prometheus-client` 0.26.0.
- Ruff lint and format checks: passed for 55 files.
- mypy: passed for 17 source modules.
- Evaluation v2 validation: 15 valid cases.
- Deterministic replay: 15/15 hard-pass cases and 4/4 citation-required cases.
- pytest: 199 passed, including 14 focused observability tests.
- Branch-aware coverage: 91.80% against an 80% gate.
- Python compilation and whitespace validation: passed.

## What this checkpoint does not prove

- Metrics are not scraped, retained, visualized, or alerted on.
- Logs and request IDs do not provide distributed tracing across services.
- A request ID is not a security credential, user identity, or idempotency key.
- Process-local metrics reset when the process restarts and aggregate separately across workers.
- Latency histograms and counts do not define service-level objectives by themselves.
- Telemetry safety depends on preserving the field and label policy as the application evolves.

## Explain-back questions and expected senior-level answers

### Why is a request ID not the same as a trace ID?

A request ID correlates records for one service request. A distributed trace models causal work across processes with trace and span relationships, sampling, propagation, and timing. A request ID can later be attached to a trace, but renaming it does not create those semantics.

### Why must labels be bounded?

Every unique label combination creates a time series. Raw paths, user IDs, queries, URLs, or exception messages can grow without limit, increasing memory, storage, and query cost until telemetry itself becomes an outage risk. Stable route templates and closed enums preserve useful aggregation.

### Why are prompts and answers absent even if logs are private?

Logs are copied, retained, indexed, and accessed differently from application data. Treating them as another conversation store expands the breach surface and complicates deletion, retention, and access controls. Operational diagnosis should begin with metadata; content capture needs a separate product, legal, and security decision.

### Why track HTTP and agent outcomes separately?

HTTP describes transport. The agent contract describes useful completion. Streaming can commit a `200` status before a provider or tool fails, so HTTP success does not imply domain success. Separate metrics preserve the truth needed for reliability analysis.

### Why use an application factory for metrics?

Metric registration is mutable process-global state in many libraries. Tests or multiple app instances can collide and contaminate counts. Supplying a fresh registry makes ownership explicit, keeps tests isolated, and avoids order-dependent failures.

### Why avoid raw exception messages?

Exception text crosses trust boundaries and often embeds upstream request data, URLs, provider payloads, or secrets. A stable public error code plus exception class and safe code location offers actionable correlation while reducing disclosure risk.

### Does exposing `/metrics` make the application production-ready?

No. A production telemetry system also needs protected collection, retention, dashboards, alerts, ownership, runbooks, and service objectives validated against real traffic. Instrumentation is the foundation, not the operating model.

### What should determine the next observability investment?

The deployment architecture and concrete debugging questions should drive it. Cross-service causality suggests OpenTelemetry traces; model-quality investigations may justify a privacy-reviewed AI trace product; reliability management needs SLOs and alerts. Adding every tool first creates cost and data risk without guaranteed value.

## Transferable senior-engineering lessons

1. Define what telemetry must never contain before deciding what to collect.
2. Model transport completion and domain completion as separate lifecycles.
3. Cardinality is a correctness and reliability constraint, not just a billing concern.
4. Generate correlation identifiers at a trusted boundary.
5. Make finalization idempotent when cancellation and streaming create multiple exit paths.
6. Prefer domain metrics with reviewed meaning over a large volume of framework defaults.
7. Instrumentation does not become observability until people can collect, query, alert, and act on it.

## Deferred work

- Deployment-aware liveness and readiness probes.
- Prometheus scraping, retention, dashboards, alerts, and runbooks.
- OpenTelemetry trace propagation and export.
- Privacy-reviewed model invocation and token-cost traces.
- Authentication, authorization, rate limiting, and persistent conversations.
- Load, timeout, cancellation, and multi-worker resilience testing.
