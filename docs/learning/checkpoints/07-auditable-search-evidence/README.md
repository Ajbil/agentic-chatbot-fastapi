# Checkpoint 07 - Auditable Web Search and Source Provenance

| Field | Value |
|---|---|
| Status | In review |
| Date | 2026-08-13 |
| Branch | `codex/auditable-search-evidence` |
| Pull request | [#7 - Add auditable web search evidence](https://github.com/Ajbil/agentic-chatbot-fastapi/pull/7) |
| Implementation commit | [`a4be4ad`](https://github.com/Ajbil/agentic-chatbot-fastapi/commit/a4be4ad) |

## Objective

Make optional web search observable and bounded. Every successful answer must distinguish permission from actual tool use and preserve safe, normalized retrieval evidence with the assistant turn that produced it.

## Why this checkpoint came next

The application previously exposed only final prose. Checking “Allow Web Search” gave an external tool to an autonomous agent, but users and tests could not prove whether the agent called it, what it searched for, whether it failed, or which pages it received.

Streaming was the other logical roadmap candidate. Search provenance comes first because streaming needs stable operational concepts to emit as events. Defining search execution and evidence now prevents a later streaming protocol from being based on ambiguous tool behavior.

## Starting condition

- `allow_search` represented permission, not proof of execution.
- Tavily returned structured results, but the agent boundary discarded all tool messages.
- `ChatResponse` contained reply and context evidence only.
- Search configuration depended partly on library defaults.
- One agent run had no explicit search-call ceiling.
- Provider output and errors were not normalized into a public evidence model.
- Frontend history was a flat message list, so answer-specific metadata had no durable owner.
- The UI displayed no sources or search status.

## Plan

1. Add strict source, execution, and search-evidence response models.
2. Configure Tavily for bounded basic retrieval with a query-only input schema.
3. Limit each agent run to three search attempts.
4. Parse agent tool calls and tool results into normalized evidence.
5. Keep provider errors and unapproved fields behind the backend boundary.
6. Return search evidence from `POST /chat` and normalize tool-limit failures.
7. Store successful conversation history as evidence-bearing committed turns.
8. Render unused, successful, partial, and failed search states safely in Streamlit.
9. Add deterministic contract, agent, API, session, and UI tests.
10. Update project documentation and record hosted CI evidence.

## Decisions and alternatives

### Model permission and execution separately

- **Decision:** Return `allowed`, `attempted`, and ordered executions.
- **Reason:** Permission is a request policy; execution is runtime evidence. Combining them makes “tool available but not selected” indistinguishable from “tool ran.”
- **Alternative:** Return only a sources list or a `used_search` boolean.
- **Tradeoff:** The response contains several fields whose invariants must be validated.
- **Revisit when:** A generic tool-event contract replaces search-specific evidence.

### Call these retrieved sources, not citations

- **Decision:** Expose what Tavily returned without claiming that sources support individual answer statements.
- **Reason:** Retrieval provenance proves tool output, while citation correctness requires claim mapping and groundedness evaluation.
- **Alternative:** Ask the model to write links into prose and label them citations.
- **Tradeoff:** The UI does not yet show inline citation markers.
- **Revisit when:** An evidence validator can test claim-to-source entailment and broken or fabricated references.

### Normalize at the backend trust boundary

- **Decision:** Allow-list title, HTTP(S) URL, and bounded snippet; discard all other Tavily fields.
- **Reason:** Third-party response shapes can grow, contain large raw content, or expose metadata the public API never intended to support.
- **Alternative:** Pass through the complete Tavily result dictionary.
- **Tradeoff:** Relevance scores, publication dates, and provider diagnostics are unavailable to clients.
- **Revisit when:** A product requirement defines stable semantics and tests for another field.

### Use a search-specific public contract

- **Decision:** Introduce `SearchEvidence` rather than an abstract list of generic tool events.
- **Reason:** Search is currently the only tool. A generic abstraction would guess at commonality before a second real use case exists.
- **Alternative:** Design provider-neutral tool-call, tool-result, and artifact schemas now.
- **Tradeoff:** Adding different tools later may require a new general contract.
- **Revisit when:** The explicit LangGraph workflow introduces retrieval, validation, or side-effect tools with shared event needs.

### Bound agent autonomy and cost

- **Decision:** Permit at most three basic Tavily searches per request and two sources per execution.
- **Reason:** Agent loops multiply latency and cost. A hard per-run ceiling creates a reviewable operational budget.
- **Alternatives:** Unlimited calls, one forced search, or an application-written fixed search pipeline.
- **Tradeoff:** Complex research questions may exhaust the allowance.
- **Revisit when:** Evaluation data demonstrates that another limit produces materially better quality per unit of cost.

### Fail the request when the agent exceeds its tool budget

- **Decision:** Convert a fourth requested search into `502 agent_tool_limit_exceeded`.
- **Reason:** Returning an apparently ordinary answer after blocking a tool would hide incomplete execution. The failed turn remains safely retryable under existing session semantics.
- **Alternative:** Tell the model that the tool was blocked and allow it to improvise a final answer.
- **Tradeoff:** Work from earlier searches in that run is not returned to the user.
- **Revisit when:** The product has an explicit partial-answer contract.

### Preserve individual failed executions inside successful answers

- **Decision:** A handled Tavily failure becomes a failed execution with no sources; the agent may still produce an answer and other searches may succeed.
- **Reason:** Search is one step inside the agent run. Partial success is useful evidence and should not be collapsed into total request failure.
- **Alternative:** Fail `POST /chat` whenever any search fails.
- **Tradeoff:** Clients must render mixed execution states.
- **Revisit when:** Research mode requires a minimum evidence threshold before any answer is acceptable.

### Make a committed turn the evidence owner

- **Decision:** Store user message, assistant message, context usage, and search evidence in one `CommittedTurn`; derive flat API messages from turns.
- **Reason:** Parallel lists and “latest evidence” fields drift as history grows. Metadata belongs to the answer produced in the same atomic operation.
- **Alternative:** Keep flat messages plus separate arrays indexed by turn number.
- **Tradeoff:** The frontend state model changes even though the API history remains flat.
- **Revisit when:** Conversations move to durable backend-owned entities.

### Render web data outside Markdown

- **Decision:** Use validated link controls and plain text snippets inside a collapsed source panel.
- **Reason:** Search titles and snippets are untrusted content. Rendering them as generated Markdown or HTML broadens the presentation trust boundary.
- **Alternative:** Interpolate results into one Markdown block.
- **Tradeoff:** Source presentation is deliberately simple.
- **Revisit when:** A shared sanitization and rich-source component is introduced.

## Implementation outcome

- Added immutable source, search-execution, and search-evidence API models with cross-field validation.
- Configured Tavily explicitly for basic, query-only, two-result searches without raw content, images, or generated provider answers.
- Applied a strict three-search limit to each agent invocation.
- Replaced the string-only agent result with a typed outcome containing reply and evidence.
- Correlated model tool-call IDs with tool results and preserved ordered query/execution relationships.
- Deduplicated URLs per execution, bounded display text, and discarded fields outside the allow-list.
- Represented empty, malformed, provider-error, and tool-error results as safe failed executions.
- Rejected incomplete or unmatched tool traces as invalid upstream responses.
- Added `agent_tool_limit_exceeded` as a stable handled `502` error.
- Refactored frontend state to evidence-bearing committed turns while preserving flat canonical request history.
- Added per-answer source panels and explicit unused, partial-failure, and total-failure messages.

## Validation evidence

- `python -m pytest -q`: 119 offline tests pass using fake model, tool, transport, and Streamlit boundaries.
- Contract tests cover valid and contradictory evidence, execution limits, status/source invariants, and unsafe URL rejection.
- Agent tests cover constrained Tavily construction, successful extraction, deduplication, field allow-listing, handled failures, malformed results, unmatched traces, and tool-limit normalization.
- Backend tests cover the new success payload and safe tool-limit error mapping.
- Session tests prove evidence ownership across multiple turns, derived message history, retry safety, reset, and permission matching.
- Streamlit tests cover historical source display, unused search, and partial failure.
- No automated test calls Groq, OpenAI, or Tavily.
- Hosted GitHub Actions evidence will be added after the draft pull request opens.

## Senior-engineering lessons

### Capability is not evidence

Granting an agent a tool says what it may do, not what it did. Runtime behavior needs its own observable contract.

### Provenance and groundedness are different guarantees

Provenance records which evidence entered the system. Groundedness asks whether output claims are supported by it. Conflating them produces impressive-looking links without a quality guarantee.

### Normalize third-party data before publishing it

A public API should expose application semantics, not inherit a vendor's complete response. Allow-listing reduces accidental coupling, payload growth, and sensitive error leakage.

### Autonomous work needs explicit budgets

An agent can repeat a paid or slow operation. Tool-call ceilings turn autonomy into a bounded resource policy that can be tested and reviewed.

### Partial failure deserves a domain model

One failed search does not necessarily invalidate an entire answer. Representing executions individually preserves useful success while making degradation visible.

### Metadata should live with the entity it describes

Sources describe one assistant answer, not the whole session or merely the latest request. Aligning storage with ownership prevents temporal bugs.

### Untrusted content remains untrusted after retrieval

A search provider improving relevance does not make web text safe instructions or safe presentation markup. Tool results are data, not policy.

## Applying this elsewhere

- Separate permission, attempt, success, and evidence.
- Define cross-field invariants in the schema rather than client convention.
- Publish only stable, necessary vendor fields.
- Bound autonomous calls by count, latency, or cost.
- Decide whether partial dependency failure permits partial success.
- Attach metadata atomically to its owning record.
- Treat external titles, snippets, and documents as untrusted input.
- Name guarantees precisely; do not call retrieval a citation system.
- Test complete trace correlation, not only happy-path parsing.

## Common mistakes

- Treating a checked search box as proof that search ran.
- Letting the model invent Markdown links instead of capturing tool results.
- Passing complete vendor responses directly through the API.
- Exposing raw provider exception strings to clients.
- Leaving agent tool loops unbounded.
- Hiding a blocked or failed search behind a normal-looking answer.
- Storing all sources as one session-level list.
- Rendering web snippets as trusted HTML or Markdown.
- Calling retrieved URLs “citations” without claim-level validation.
- Building a generic tool abstraction before a second tool establishes real common behavior.

## Explain-back questions

1. Why does `allow_search=true` not prove that search was used?
2. What different facts are represented by `allowed`, `attempted`, execution status, and sources?
3. Why are retrieved sources not yet claim-level citations?
4. Why should Tavily results be normalized instead of passed through unchanged?
5. Which fields cross the search-provider trust boundary, and why only those?
6. Why does one request have both a search-call limit and a per-search result limit?
7. Why is exceeding the tool budget a request failure rather than a hidden warning to the model?
8. When can a failed search execution coexist with a successful chat response?
9. Why must tool-call IDs be correlated with tool results?
10. Why is `CommittedTurn` a safer evidence owner than a session-level sources list?
11. Why are source snippets rendered as plain text rather than Markdown?
12. What additional system would be needed to claim that an answer is grounded?

## Deferred work

- Claim-level citation mapping, source entailment, authority evaluation, and fabricated-link detection belong to a grounding checkpoint.
- Mandatory-search research mode needs minimum-source and freshness policies.
- Search topic, date, domain, and depth controls need a reviewed product and cost contract.
- Streaming needs operational events, cancellation, backpressure, and disconnect behavior.
- Full-page fetch and extraction need content-size, timeout, security, and context-budget policies.
- Generic tool events should wait until multiple tool types reveal useful common semantics.
- Persistent traces and LangSmith integration remain observability work.
- Prompt-injection resistance needs adversarial evaluation, not only schema validation.
