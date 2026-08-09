# Checkpoint 06 - Context Budgeting and Transparent Recent-Window Trimming

| Field | Value |
|---|---|
| Status | In review |
| Date | 2026-08-09 |
| Branch | `codex/context-window-management` |
| Pull request | [#6 - Add transparent context-window management](https://github.com/Ajbil/agentic-chatbot-fastapi/pull/6) |
| Implementation commit | [`7688fea`](https://github.com/Ajbil/agentic-chatbot-fastapi/commit/7688fea) |

## Objective

Bound every model invocation to an application-owned input budget. Preserve the newest coherent conversation turns, reject a newest turn that cannot fit, and disclose exactly how much history was included or omitted while leaving the full browser transcript intact.

## Why this checkpoint came next

Checkpoint 05 gave the application real multi-turn history and intentionally resent every committed message. That is correct state ownership but incomplete model-input management: character and message-count limits do not prove that a request fits a provider context window.

Search evidence, explicit workflows, and production observability would all become harder to reason about if context loss remained implicit. A deterministic policy and typed evidence therefore come before adding more agent behavior.

## Starting condition

- The UI retained and resent up to 50 messages.
- The backend forwarded every validated message to the agent.
- Model metadata declared a context window but no output allocation.
- Providers could reject a large request or apply behavior outside the application's control.
- A user could not tell whether all visible history influenced an answer.
- The API required only that the final message was from the user; it did not enforce complete alternation.
- No request-level token or omission evidence existed.

## Plan

1. Add an application output reserve to each model definition.
2. Define a pure, provider-independent context-planning module.
3. Estimate the serialized system prompt and messages locally.
4. Retain the newest user message and newest complete turns within budget.
5. Reject an irreducible newest request with a stable HTTP `413` error.
6. Pass provider-specific output limits to Groq and OpenAI clients.
7. Return internally consistent context evidence in every successful response.
8. Preserve the complete UI transcript and display the latest usage and omission warning.
9. Strengthen the request contract to canonical alternating turns.
10. Add boundary, backend, provider, session, and Streamlit tests plus CI and documentation updates.

## Decisions and alternatives

### Make the backend the context-policy owner

- **Decision:** Plan the model window in the backend immediately after request and capability validation.
- **Reason:** Every client receives identical behavior, and an oversized request fails before credentials, network calls, or provider billing are involved.
- **Alternatives:** Trim only in Streamlit, rely on each provider, or put policy inside the agent adapter.
- **Tradeoff:** The backend needs model metadata and a token-estimation dependency.
- **Revisit when:** A workflow contains multiple model calls with different context needs; each workflow node may then need its own budget policy.

### Use a conservative provider-neutral estimate

- **Decision:** Use LangChain Core's `count_tokens_approximately` and label the method in the response.
- **Reason:** It is already a direct project dependency, works offline for every current provider, and keeps policy deterministic without downloading tokenizers or maintaining provider branches.
- **Alternatives:** Exact provider tokenizers, character limits, remote token-count endpoints, or a new direct `tiktoken` dependency.
- **Tradeoff:** The value is an estimate and is not suitable for billing or exact maximum packing.
- **Revisit when:** Production telemetry shows material under-utilization or overflow, exact cost accounting is required, or providers expose stable counting APIs.

### Reserve output and uncertainty before allocating input

- **Decision:** Subtract a 4,096-token model output reserve and a 10% safety margin (minimum 256) from each context window.
- **Reason:** Input and output share finite capacity, while provider serialization, tools, and approximation error add overhead not completely represented by message text.
- **Alternatives:** Fill the published context limit, use one fixed input cap, or choose a percentage-only output allocation.
- **Tradeoff:** Some usable context remains intentionally unallocated.
- **Revisit when:** Provider-specific measurements support smaller margins or product requirements need different response lengths.

### Preserve recency in complete turns

- **Decision:** Always keep the newest user message, then add the newest complete user/assistant pairs backward until the next pair does not fit.
- **Reason:** Recency is a clear baseline relevance heuristic, and pair integrity avoids an answer without its question or a question without its committed answer.
- **Alternatives:** Drop individual messages, retain the first system-adjacent turns, score semantic relevance, or summarize old history.
- **Tradeoff:** An important old fact can be omitted, and one large recent turn prevents including smaller older turns.
- **Revisit when:** The product adds explicit memory, importance markers, retrieval, or tested summarization.

### Stop at the first non-fitting recent turn

- **Decision:** Do not skip a large recent turn to include less-recent small turns.
- **Reason:** A contiguous recent window has simple, explainable semantics and avoids constructing a chronology with unexplained holes.
- **Alternative:** Greedily pack any older pair that fits.
- **Tradeoff:** The selected input may use less than the full budget.
- **Revisit when:** Relevance ranking provides explicit provenance and evaluation proves that non-contiguous context improves answers.

### Keep transcript retention separate from model-input retention

- **Decision:** Streamlit keeps all committed messages while storing the latest backend context evidence separately.
- **Reason:** Removing UI history would confuse visible conversation state with one invocation's bounded model input and hide information loss from the user.
- **Alternatives:** Delete omitted messages from session state or display only the model window.
- **Tradeoff:** A visible old message may no longer influence the latest answer.
- **Revisit when:** The UI can visualize per-message inclusion or conversations become server-owned.

### Make truncation part of the success contract

- **Decision:** Every successful response contains model capacity, reservations, estimates, counts, and a truncation flag with validated invariants.
- **Reason:** Operationally important information loss should be machine-readable and visible, not inferred from logs.
- **Alternatives:** A response header, backend logs only, or a warning string embedded in the reply.
- **Tradeoff:** The public API response becomes larger and clients must adopt the new required field.
- **Revisit when:** Versioned APIs require backward-compatible evolution or richer per-message provenance is added.

### Enforce output limits at provider construction

- **Decision:** Pass the catalog reserve as `max_tokens` for Groq and `max_completion_tokens` for OpenAI.
- **Reason:** Budget math and provider behavior should agree; metadata without enforcement gives a false guarantee.
- **Alternative:** Treat the reserve as documentation only.
- **Tradeoff:** Provider adapters retain a small amount of provider-specific configuration.
- **Revisit when:** SDK parameter names or model-specific output capabilities change.

## Implementation outcome

- Added immutable output-token limits to the model registry and exposed them through `GET /models`.
- Added a pure context planner with local approximate counting, safety allocation, recent complete-turn selection, and an irreducible-input exception.
- Strengthened the chat contract to user/assistant alternation beginning and ending with a user message.
- Added a validated `ContextUsage` success payload whose budgets, counts, estimates, and truncation flag must reconcile.
- Integrated planning before provider invocation and mapped irreducible input to `413 context_window_exceeded`.
- Configured both model-provider clients with the same output limit used by budget calculation.
- Updated Streamlit session state to commit the typed response and retain its context evidence.
- Added visible usage, reserve, margin, and omission reporting without deleting transcript messages.
- Added offline tests across policy, HTTP, provider configuration, contracts, session transitions, and browser-level Streamlit behavior.

## Validation evidence

- `python -m pipenv run python -m pytest -q`: 99 offline tests passed during implementation.
- Context-policy tests cover all-history fit, complete-turn trimming, contiguous recency, irreducible latest input, and reservation arithmetic.
- Backend tests prove only selected messages reach the agent and `413` occurs before agent execution.
- Provider tests prove Groq and OpenAI receive their respective output-limit parameters.
- Contract tests prove malformed turn order and inconsistent context evidence are rejected.
- Streamlit tests prove the full transcript remains visible while a truncation warning and usage estimate are shown.
- No test contacts Groq, OpenAI, or Tavily.
- [GitHub Actions run `31310334290`](https://github.com/Ajbil/agentic-chatbot-fastapi/actions/runs/31310334290) passed on the draft pull request in a clean Ubuntu/Python 3.12 environment.

## Senior-engineering lessons

### Published capacity is not an application budget

A model's context window is shared capacity, not a target for raw input. Output space and uncertainty must be allocated before accepting input. Capacity planning is about explicit reservations, not optimistic packing.

### Context policy belongs at a stable boundary

Putting the rule before provider construction makes behavior client-independent, testable, and cheap to reject. A boundary is valuable when it centralizes semantics as well as validation.

### Deterministic degradation beats silent degradation

When all history cannot fit, the system should apply a named rule and report the result. Invisible truncation produces answers whose evidence cannot be explained or debugged.

### Preserve semantic units, not arbitrary slices

Conversation messages have relationships. Treating a completed turn as the smallest removable unit preserves more meaning than treating every message or character as interchangeable capacity.

### Estimates require provenance and headroom

An approximate number becomes misleading if presented as exact. Label the method, retain a safety margin, and choose assertions based on invariants rather than pretending to know provider billing tokens.

### Metadata must affect execution

The registry's output reserve is used both in arithmetic and provider configuration. Architectural metadata that does not control behavior drifts into documentation rather than remaining a contract.

### User-visible state and execution state can differ

The full transcript is a product record; the selected model window is one execution input. Keeping both, and showing the difference, creates transparency without destructive UI behavior.

## Applying this elsewhere

- Identify every consumer of a finite shared resource.
- Reserve mandatory downstream capacity before allocating upstream input.
- Put cross-client policy at the server boundary.
- Select the smallest coherent unit that may be removed.
- Define whether retained context must be contiguous.
- Reject work that cannot fit even after permitted degradation.
- Label approximations and budget for uncertainty.
- Return evidence that lets clients explain degradation.
- Keep user-owned records separate from transient execution inputs.
- Test decisions at boundaries, not only helper functions.

## Common mistakes

- Treating a message-count or character-count limit as a token budget.
- Filling the entire advertised context window with input and leaving no output capacity.
- Depending on undocumented provider-side truncation.
- Removing one side of a completed conversation turn.
- Silently deleting transcript messages to match one model invocation.
- Reporting an estimated token count without identifying the estimator.
- Adding model capacity metadata without enforcing it in provider calls.
- Unit-testing trimming while failing to prove the trimmed list reaches the agent.
- Summarizing old context before defining evidence, quality checks, and failure behavior.

## Explain-back questions

1. Why is a model's published context window not the same as the application's input budget?
2. Why should output capacity be reserved before input messages are selected?
3. What uncertainty does the safety margin protect against, and what does it not guarantee?
4. Why does this checkpoint use an approximate tokenizer instead of claiming exact provider counts?
5. Why is the backend a better policy owner than the Streamlit client?
6. Why are completed user/assistant turns retained or omitted together?
7. Why does selection stop at the first recent pair that does not fit?
8. Under what condition does the API return `413 context_window_exceeded`?
9. Why does the UI retain messages that were omitted from the latest model input?
10. What makes `ContextUsage` operational evidence rather than decorative metadata?
11. Why must provider output parameters agree with registry budget metadata?
12. What measurements would justify adopting exact provider-specific tokenizers or a smaller safety margin?

## Deferred work

- Summarization needs a quality contract, provenance, failure behavior, and evaluation before replacing deterministic omission.
- Durable or cross-device memory still requires authentication, persistence, isolation, retention, and deletion policies.
- Provider-exact token accounting should be driven by measured overflow, utilization, or billing requirements.
- Tool schemas and tool-result budgets need explicit workflow-aware accounting when tool use becomes more complex.
- Per-message inclusion indicators can improve UI transparency in a later product checkpoint.
- Search activity and structured source evidence remain the next likely capability checkpoint.
- Streaming requires a separate event and partial-state contract.
