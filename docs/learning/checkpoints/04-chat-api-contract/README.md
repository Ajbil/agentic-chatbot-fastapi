# Checkpoint 04 - Canonical Chat API Contract

| Field | Value |
|---|---|
| Status | In review |
| Date | 2026-08-06 |
| Branch | `codex/chat-api-contract` |
| Pull request | [#4 - Define canonical chat API contract](https://github.com/Ajbil/agentic-chatbot-fastapi/pull/4) |
| Implementation commit | [`91f4d5b`](https://github.com/Ajbil/agentic-chatbot-fastapi/commit/91f4d5b) |

## Objective

Replace the prototype `POST /chat` boundary with one canonical request, a typed success response, a consistent error envelope, and truthful HTTP status codes. Make Streamlit consume that contract through a testable client while keeping all automated tests offline.

## Why this checkpoint came next

Checkpoint 03 established a backend-owned registry and stable application model keys. The remaining chat boundary still accepted provider and model as unrelated strings, allowed three message representations, returned application errors with HTTP 200, and declared no success response schema in OpenAPI.

Chat history, streaming, source citations, authentication, and observability all depend on a stable boundary. Adding those features first would multiply the number of clients and code paths that later needed migration.

## Starting condition

- `POST /chat` accepted a string, a list of strings, or a list of message objects.
- Messages defaulted silently to `"Hello"` when omitted.
- Clients sent provider names and provider-facing model IDs instead of the stable registry key.
- Unknown models and unsupported search returned `{"error": "..."}` with HTTP 200.
- Missing credentials and unexpected failures had no application-owned error contract.
- The success response was an untyped dictionary produced by the agent layer.
- Streamlit performed its HTTP request inside rendering code and inspected arbitrary dictionaries.
- OpenAPI showed an unspecified successful response body.

## Plan

1. Define canonical request, message, success, error, and validation-detail schemas.
2. Replace provider/model input with one registry-owned `model_key`.
3. Validate message roles, content, count, ordering, and extra fields.
4. Give handled failures accurate status codes and one safe error envelope.
5. Separate the agent result from the HTTP response representation.
6. Extract and test a typed Streamlit chat transport client.
7. Add offline schema, endpoint, agent, frontend-client, and OpenAPI tests.
8. Update CI compilation, README examples, and the learning journal.

## Decisions and alternatives

### Make a clean cutover on `POST /chat`

- **Decision:** Replace the old payload instead of supporting both formats or adding `/v1/chat`.
- **Reason:** The only known client is Streamlit in this repository, and it changes atomically in the same pull request. One contract makes obsolete usage fail visibly.
- **Alternatives:** Add a temporary translator or retain `/chat` while introducing `/v1/chat`.
- **Tradeoff:** Any undocumented external caller must update immediately.
- **Revisit when:** Independent clients exist and the project adopts an explicit compatibility and deprecation policy.

### Use the application model key at the boundary

- **Decision:** Accept `model_key` and resolve provider metadata only inside the backend.
- **Reason:** Clients choose a product capability, not a vendor routing implementation. This also makes invalid provider/model combinations impossible to express.
- **Alternative:** Continue accepting `model_provider` and `model_name` together.
- **Tradeoff:** Clients must fetch or otherwise know the application catalog.
- **Revisit when:** A future routing feature intentionally allows the backend to choose among several provider deployments for one logical model.

### Accept one structured message representation

- **Decision:** Require a non-empty list of `{role, content}` objects, allow only `user` and `assistant`, and require the final role to be `user`.
- **Reason:** One representation has one interpretation and prepares for real history. `system_prompt` remains the single authority for system instructions.
- **Alternatives:** Keep convenience unions, allow client system messages, or accept any sequence of roles.
- **Tradeoff:** Simple clients must construct a message object instead of sending a bare string.
- **Revisit when:** Tool messages, multimodal content, or a different system-instruction policy becomes a real product requirement.

### Add transport-safety limits without claiming token accuracy

- **Decision:** Limit a request to 50 messages, each message to 20,000 characters, and the system prompt to 4,000 characters.
- **Reason:** A public boundary needs bounded inputs even before model-specific token budgeting exists.
- **Alternative:** Leave inputs unbounded or pretend character counts equal model tokens.
- **Tradeoff:** The initial limits are operational guardrails rather than evidence-based context allocation.
- **Revisit when:** The context-window checkpoint adds tokenizer-aware budgeting and measured conversation requirements.

### Preserve meaningful whitespace but reject blank text

- **Decision:** Use trimmed text only to detect blank values; retain the submitted content otherwise.
- **Reason:** Validation should reject meaningless input without silently rewriting user data, code indentation, or formatting.
- **Alternative:** Strip every string automatically.
- **Tradeoff:** Clients receive exactly the whitespace they submitted.
- **Revisit when:** A product-level normalization policy is defined.

### Give the application its own error envelope

- **Decision:** Return `error.code`, `error.message`, and a stable `error.details` list for handled failures.
- **Reason:** Clients need a machine-readable code and a safe human message. Validation details omit submitted values so prompts cannot be echoed into logs or UI accidentally.
- **Alternatives:** Return ad hoc dictionaries or use FastAPI's default `detail` representation for some failures.
- **Tradeoff:** Custom handlers and schemas add code that must remain consistent with OpenAPI.
- **Revisit when:** The project adopts a broader standard such as RFC 9457 Problem Details across multiple services.

### Distinguish client, dependency, and server failures

- **Decision:** Use 400 for unsupported choices, 422 for structural validation, 502 for an unusable agent result, 503 for missing server configuration, and a sanitized 500 for unexpected defects.
- **Reason:** Status codes communicate which failure domain owns recovery. A missing server API key is not a client authentication failure, so 401 would be misleading.
- **Alternative:** Return 200 for every outcome or classify every failure as 400/500.
- **Tradeoff:** Provider-specific timeout and rate-limit statuses remain incomplete.
- **Revisit when:** Provider adapters normalize Groq, OpenAI, and Tavily exceptions reliably enough to promise 429, 502, and 504 behavior.

### Keep HTTP representation out of the agent layer

- **Decision:** The agent returns generated text; FastAPI constructs `ChatResponse`.
- **Reason:** AI orchestration should not know whether its result is transported through HTTP, a CLI, a queue, or another interface.
- **Alternative:** Keep returning `{"reply": ...}` from the agent function.
- **Tradeoff:** The endpoint performs one explicit mapping step.
- **Revisit when:** A richer domain response contains tool activity, sources, usage, or finish reasons.

### Extract a typed frontend transport client

- **Decision:** Move chat HTTP behavior out of Streamlit rendering and validate both success and error bodies.
- **Reason:** Network failures and malformed server responses can be tested without running the UI, and rendering code stays focused on presentation.
- **Alternative:** Continue calling `requests.post` directly inside the button handler.
- **Tradeoff:** The frontend gains a small additional module and exception type.
- **Revisit when:** Generated clients or a shared client package becomes justified by multiple consumers.

## Implementation outcome

- Added shared Pydantic models for the canonical message, request, success, validation-detail, and error contracts.
- Replaced provider/model request fields with the stable registry `model_key`.
- Removed raw-string, string-list, system-message, implicit-Hello, and silently ignored message paths.
- Added explicit request limits, blank checks, final-user validation, and rejection of unknown fields.
- Added structured 400, 422, 502, 503, and sanitized 500 responses.
- Made OpenAPI declare the success model and every handled chat error model.
- Changed the agent boundary to return text and reject empty or non-text AI results.
- Added a typed frontend chat client that handles network, JSON, success-schema, and error-schema failures.
- Updated Streamlit to send the application model key and render the typed reply.
- Kept the dependency manifest and lock file unchanged.

## Validation evidence

- `python -m pipenv run python -m pytest -q`: 66 offline tests passed after the implementation.
- Contract tests cover valid history, field limits, blank values, extra fields, unsupported roles, final-message rules, and obsolete formats.
- Endpoint tests prove that invalid choices do not invoke the agent and that every handled failure has the expected status and envelope.
- The unexpected-error test proves internal diagnostic text is not returned to the client.
- Frontend-client tests cover timeouts, connection failures, malformed JSON, invalid success bodies, invalid error bodies, and structured backend errors.
- The OpenAPI test proves the request, success, and error schemas are published as part of the service contract.
- No automated test contacts Groq, OpenAI, or Tavily.

## Senior-engineering lessons

### Flexibility at a boundary creates complexity behind it

Accepting three equivalent message shapes makes every downstream function understand three shapes, multiplies test cases, and leaves ambiguous semantics. Canonical boundaries move convenience transformations to clients and keep the service deterministic.

### HTTP status is part of the contract

A JSON body saying `error` does not make an HTTP 200 request a failure to load balancers, retry policies, monitoring, or generic clients. The transport status and response body must communicate the same outcome.

### Error classification starts with ownership

A malformed request belongs to the caller. A missing server credential belongs to service operation. An invalid provider result belongs to an upstream boundary. An unexpected defect belongs to the application. Correct classification tells clients whether changing the request, retrying, or alerting an operator is appropriate.

### Stable internal identity prevents vendor leakage

Provider IDs change for reasons outside the application. A stable model key lets clients depend on the product contract while the backend owns provider routing and compatibility.

### Schemas are executable architecture

The Pydantic models now drive runtime validation, serialization, tests, frontend parsing, and OpenAPI. A contract is stronger when documentation and enforcement come from the same definition.

### Do not promise distinctions the system cannot detect reliably

Returning 504 for every exception that looks slow or 429 for guessed provider errors would create false semantics. Provider-specific normalization should be introduced with adapters, representative exceptions, tests, and an explicit retry policy.

### Sanitization is an API responsibility

Unexpected errors need detailed server logs, but clients should receive stable, safe messages. Validation responses should identify the failing location without echoing complete submitted prompts or credentials.

## Applying this elsewhere

- Inventory every accepted input representation and select one canonical form.
- Separate application-owned identifiers from vendor identifiers.
- Make request fields required when a meaningful default does not exist.
- Assign status codes by failure ownership and likely recovery action.
- Give errors stable machine codes; do not make clients parse prose.
- Validate successful responses as carefully as error responses.
- Keep domain or orchestration functions independent of HTTP dictionaries.
- Test the generated API description, not only runtime examples.
- Add compatibility machinery only for consumers that actually exist.

## Common mistakes

- Treating permissive input unions as free convenience.
- Returning HTTP 200 with an error field.
- Using 401 for a credential missing from the server's own environment.
- Returning raw exception messages or submitted values to clients.
- Allowing both a system-message role and a separate system-prompt field without precedence rules.
- Keeping provider and model as independent strings after introducing a registry key.
- Trusting a 200 response without validating its schema.
- Mapping all provider failures to precise statuses before the integration layer can distinguish them.
- Adding API versioning before there is a compatibility commitment or independent consumer.

## Explain-back questions

1. Why is one canonical request representation safer than accepting several convenient forms?
2. Why should the client send an application model key instead of a provider and provider model ID?
3. What is the practical difference between a 400 response and a 422 response in this API?
4. Why is a missing server-side provider credential represented as 503 rather than 401?
5. Why should validation details omit the submitted input value?
6. Why does the agent return text while FastAPI constructs the response object?
7. What does `extra="forbid"` protect against during an API migration?
8. Why is an empty AI message treated as 502 rather than a successful empty reply?
9. When would maintaining an old endpoint or introducing `/v1` become justified?
10. What evidence and architecture are needed before promising provider-specific 429 and 504 responses?

## Deferred work

- Checkpoint 05 should add real Streamlit session history and send the accumulated canonical messages.
- Token-aware context budgeting and truncation remain a separate context-window checkpoint.
- Provider adapters should normalize authentication, rate-limit, timeout, and upstream failures before adding reliable 429/502/504 mappings.
- Streaming will require a separate event contract rather than changing this JSON response implicitly.
- Request IDs, structured logs, metrics, and tracing belong to an observability checkpoint.
- Authentication, authorization, rate limiting, and API version policy require real deployment and consumer requirements.
- Tool calls, source evidence, usage metadata, and finish reasons require a richer domain response before expanding `ChatResponse`.
