# Checkpoint 11 - Application-Owned LangGraph Workflow

| Field | Value |
|---|---|
| Status | In review |
| Date | 2026-08-16 |
| Branch | `codex/explicit-langgraph-workflow` |
| Pull request | [#17 - Add application-owned LangGraph workflow](https://github.com/Ajbil/agentic-chatbot-fastapi/pull/17) |
| Implementation commit | [`a9d9d67`](https://github.com/Ajbil/agentic-chatbot-fastapi/commit/a9d9d67) |
| Test commit | [`ebb7dac`](https://github.com/Ajbil/agentic-chatbot-fastapi/commit/ebb7dac) |
| Documentation commit | [`a80e4c9`](https://github.com/Ajbil/agentic-chatbot-fastapi/commit/a80e4c9) |

## Objective

Replace the framework-generated agent loop with a typed, application-owned LangGraph `StateGraph` whose nodes, edges, safety checks, and termination rules are explicit, while preserving the existing HTTP, streaming, context, search-evidence, and evaluation contracts.

## Why this checkpoint came next

Checkpoint 10 established a deterministic behavioral baseline before the orchestration changed. That ordering gives this refactor a regression oracle: public behavior can remain stable while internal control flow becomes visible and independently testable. The explicit graph also creates named boundaries where later grounding, approval, observability, persistence, and recovery features can be added without hiding them inside a high-level agent factory.

## Starting condition

- The application delegated its model/tool loop to LangChain's `create_agent` factory.
- Search was optional and model-directed, with framework middleware limiting Tavily to three calls.
- The public API already returned typed context and search evidence through synchronous and streaming endpoints.
- Unit tests covered the surrounding adapter but did not execute and inspect the real compiled graph topology.
- The 15-case deterministic evaluation baseline was already versioned and merge-blocking.
- The goal was architectural ownership, not a change to model-selection or search-answer quality.

## Plan

1. Declare LangGraph as a direct dependency because production code imports it directly.
2. Define request-scoped typed graph state with reducer-owned message accumulation.
3. Build explicit model, validation, and tool nodes with visible routing and termination.
4. Move the three-search invariant into application code and validate the entire pending batch before external execution.
5. Preserve synchronous responses, typed streaming progress, safe tool failures, and normalized provenance.
6. Test the real compiled workflow with scripted models and fake tools, including topology and adversarial tool-call cases.
7. Prove unchanged behavior with all repository gates and deterministic evaluation replay.
8. Document decisions, trade-offs, and deliberately deferred production concerns.

## Decisions and alternatives

### Own the graph instead of wrapping `create_agent`

- **Decision:** Construct a `StateGraph` with named `model`, `validate_tool_calls`, and `tools` nodes.
- **Reason:** Reviewers can see which state crosses boundaries, when external effects are allowed, where the loop terminates, and which invariants the application enforces.
- **Alternatives:** Retain `create_agent`, subclass its middleware, or replace LangGraph with a handwritten loop.
- **Tradeoff:** The application owns more orchestration code and must follow relevant LangGraph API changes.
- **Revisit when:** The workflow becomes trivial enough to remove LangGraph or complex enough to justify reusable graph modules.

### Preserve model-directed optional search

- **Decision:** The model still chooses whether to emit a Tavily tool call when search permission is enabled.
- **Reason:** This checkpoint is a behavior-preserving control-flow refactor. Forcing search based on prompt classification would be a product-policy change requiring its own evaluation and user contract.
- **Alternatives:** Always search when permission is enabled, use a deterministic freshness classifier, or add a router model.
- **Tradeoff:** Different models can still make different search decisions or synthesize retrieved evidence differently.
- **Revisit when:** Product requirements define mandatory research categories and evaluation demonstrates a reliable routing policy.

### Validate before external execution

- **Decision:** Route every proposed tool batch through application validation before `ToolNode` executes it.
- **Reason:** Unsupported tools, invalid arguments, inconsistent identifiers, and over-limit batches must fail before producing cost, latency, or side effects.
- **Alternatives:** Let the tool implementation reject inputs, validate calls individually during execution, or rely only on provider schema adherence.
- **Tradeoff:** The validation node knows the search input contract and therefore couples orchestration to application tool policy.
- **Revisit when:** Multiple heterogeneous tools justify a registry of per-tool validators and policies.

### Count cumulative calls and reject invalid batches atomically

- **Decision:** Count all assistant tool calls accumulated in request state and reject when the total exceeds three. A four-call parallel batch executes zero searches.
- **Reason:** A limit is only a safety boundary if concurrency cannot partially cross it. Cumulative counting also prevents a model from avoiding the cap across repeated model/tool cycles.
- **Alternatives:** Limit each model turn, stop after three tool results, or depend on framework middleware.
- **Tradeoff:** A request with three successful calls cannot use a fourth recovery query, even if one earlier result was poor.
- **Revisit when:** Search budgets become cost-weighted or retry policy distinguishes attempts from successful executions.

### Use request-scoped typed message state

- **Decision:** Use a `TypedDict` with LangGraph's `add_messages` reducer and compile a fresh graph for each prepared request.
- **Reason:** The state contract is statically visible, reducer semantics are explicit, and request data cannot leak between users through shared mutable workflow state.
- **Alternatives:** Plain dictionaries, a custom state class, a singleton compiled graph with runtime configuration, or a persisted checkpointer.
- **Tradeoff:** Per-request compilation has small overhead and durable pause/resume is not available.
- **Revisit when:** Profiling shows compilation matters or identity-backed persistence has defined ownership and retention rules.

### Inject the system prompt at the model boundary

- **Decision:** Prepend a trusted `SystemMessage` for every model invocation without appending it to returned graph history.
- **Reason:** The policy remains present on every loop while staying separate from user-visible and provenance-processing messages.
- **Alternatives:** Store it in reducer state or concatenate it with user content.
- **Tradeoff:** Each model node must consistently apply the injection rule.
- **Revisit when:** Graph state gains an explicit immutable configuration channel.

### Use `ToolNode` but retain application policy

- **Decision:** Reuse LangGraph's `ToolNode` for dispatch and parallel execution, with a fixed safe error message, while keeping authorization and limits in the preceding node.
- **Reason:** Tool dispatch is commodity framework behavior; permission, budget, validation, and error disclosure are product policy and belong to the application.
- **Alternatives:** Handwrite tool execution or let `ToolNode` receive unvalidated calls.
- **Tradeoff:** The application depends on `ToolNode` event/message conventions used by streaming and provenance normalization.
- **Revisit when:** Tools need transactions, per-tool timeouts, cancellation, or different concurrency policies.

### Keep LangGraph as a direct dependency

- **Decision:** Add `langgraph` to `Pipfile` even though another package already installed it transitively.
- **Reason:** Direct imports are a direct dependency contract. Depending on an incidental transitive installation makes upgrades and removals fragile.
- **Alternative:** Rely on LangChain to continue pulling LangGraph.
- **Tradeoff:** The repository must intentionally maintain another declared dependency.
- **Revisit when:** Production code no longer imports LangGraph.

## Implementation outcome

- Replaced `create_agent` and its tool-limit middleware with an explicit compiled `StateGraph`.
- Added typed request state and a narrow protocol for the compiled graph surface consumed by the application.
- Added a model node that binds only enabled tools, injects the trusted system prompt, and rejects non-assistant provider responses.
- Added conditional routing that ends on a final assistant response and permits tool execution only when search was enabled.
- Added pre-execution validation for supported tool names, search arguments, non-empty unique identifiers, and the cumulative three-call cap.
- Added safe `ToolNode` execution followed by an explicit loop back to the model.
- Preserved existing public response, streaming, search-provenance, provider-configuration, and context-budget behavior.
- Added real-graph tests using deterministic scripted models and fake local tools; no provider or Tavily calls are made.

## Validation evidence

- `python -m pipenv verify`: the lock file matches the direct dependency declaration.
- `python -m pipenv run ruff check .`: no lint violations.
- `python -m pipenv run ruff format --check .`: all 49 Python files are formatted.
- `python -m pipenv run mypy`: no issues in 16 production modules.
- Offline suite: 177 tests passed, including 12 tests of the real compiled graph.
- Dataset validation: version `v1` remains valid with 15 cases.
- Deterministic replay remains byte-for-byte unchanged: 15/15 hard passes and 45/45 advisory passes.
- Branch coverage: 91.51% total against the enforced 80% minimum.
- [CI run `31933415969`](https://github.com/Ajbil/agentic-chatbot-fastapi/actions/runs/31933415969) passed the `quality`, `test`, and credential-free `evaluation` jobs on draft PR #17.
- [CodeQL run `31933415984`](https://github.com/Ajbil/agentic-chatbot-fastapi/actions/runs/31933415984) passed `Analyze (python)`, and the separate required `CodeQL` context also passed.
- No live provider calls were made; this checkpoint changes orchestration control flow, not the approved cost boundary.

## Senior-engineering lessons

### Abstractions do not remove ownership

A high-level agent helper reduces code, but the application still owns its side effects, limits, and failure semantics. When those behaviors matter to safety or review, make them explicit at the boundary the team controls.

### Graph nodes should represent policy boundaries

Named nodes are valuable when each one has a distinct responsibility: generation proposes an action, validation authorizes it, and tool execution performs the effect. Splitting code into nodes without separating responsibility would only create diagram-shaped complexity.

### Validate a batch before starting a batch

Concurrent work makes naive limits porous. If four calls are proposed and three start before the fourth is rejected, the claimed maximum has already failed. Atomic preflight validation is a reusable pattern for APIs, jobs, payments, and bulk writes.

### Deterministic control can surround probabilistic decisions

The model may decide whether to search, but supported operations, input schemas, total budget, state transitions, error disclosure, and termination remain deterministic application rules.

### Preserve contracts during architectural refactors

Changing orchestration and changing product behavior simultaneously makes regressions hard to attribute. Stable API, stream, evidence, and evaluation contracts let reviewers focus on whether the new structure is equivalent and safer.

### Persistence is an architectural commitment

Adding a LangGraph checkpointer is not a convenience toggle. It raises questions about user identity, thread ownership, authorization, deletion, encryption, retention, schema migration, and resumability. Deferring it until those contracts exist is disciplined scope control.

## Applying this elsewhere

- Identify which framework defaults currently implement business or safety policy.
- Put authorization and validation before cost, latency, or irreversible side effects.
- Model workflow state explicitly and keep request state isolated.
- Test real control flow with deterministic adapters, not only mocked factory calls.
- Preserve public contracts when refactoring internals.
- Treat parallel batches atomically when enforcing quotas.
- Declare every package imported by production code as a direct dependency.
- Add persistence only after ownership and lifecycle rules are defined.

## Common mistakes

- Drawing a graph diagram while still hiding the real loop in a factory.
- Treating a model-emitted tool name or arguments as trusted input.
- Enforcing a call limit after external requests have already started.
- Counting calls per cycle instead of cumulatively across the request.
- Mixing the trusted system prompt into returned user conversation history.
- Sharing mutable graph state between unrelated requests.
- Adding a checkpointer without identity, authorization, retention, and deletion policy.
- Changing search policy during a supposedly behavior-preserving refactor.
- Testing only node functions without executing the compiled graph and its edges.
- Relying on an undeclared transitive dependency.

## Explain-back questions

1. What control did the application gain by replacing `create_agent` with an explicit `StateGraph`?
2. Why is a graph useful here beyond producing an architecture diagram?
3. Which decisions remain probabilistic, and which rules are deterministic?
4. Why must tool calls be validated before `ToolNode` executes them?
5. Why is rejecting a four-call parallel batch atomically stronger than stopping after three executions?
6. Why does the limit count calls across multiple model/tool cycles?
7. What does the `add_messages` reducer guarantee about node updates?
8. Why is request-scoped state safer than shared mutable workflow state?
9. Why is the system prompt injected at the model boundary instead of stored in returned history?
10. Why reuse `ToolNode` while keeping authorization and limits outside it?
11. What public behaviors had to remain unchanged for this to be a controlled refactor?
12. Why do scripted model and fake-tool tests provide stronger evidence than mocking the graph builder?
13. Why is LangGraph declared directly even if it was already installed transitively?
14. What production decisions must precede adding a LangGraph checkpointer?
15. When would a deterministic search router deserve a separate checkpoint?

## Deferred work

- Forced-search or freshness-classification policy and model-routing experiments.
- Claim-level citation binding and grounded-answer evaluation.
- Durable graph checkpoints, user identity, authorization, retention, and deletion.
- Distributed tracing, metrics, structured logs, and service-level objectives.
- Per-node timeouts, retries, cancellation, circuit breakers, and cost budgets.
- Deployment infrastructure, rate limiting, load testing, and resilience exercises.
