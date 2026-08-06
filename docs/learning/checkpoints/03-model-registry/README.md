# Checkpoint 03 — Backend-Owned Model Registry

| Field | Value |
|---|---|
| Status | Complete |
| Date | 2026-08-05 |
| Branch | `agent/model-registry` |
| Pull request | [#3 — Centralize model catalog and frontend discovery](https://github.com/Ajbil/agentic-chatbot-fastapi/pull/3) |
| Implementation commit | [`0c95c43`](https://github.com/Ajbil/agentic-chatbot-fastapi/commit/0c95c43); merged as [`5bded57`](https://github.com/Ajbil/agentic-chatbot-fastapi/commit/5bded57) |

## Objective

Create one immutable, backend-owned catalog for supported models, validate provider/model compatibility through it, expose it at `GET /models`, and make Streamlit render model choices from that contract.

## Why this checkpoint came next

Checkpoint 01 made configuration deterministic, and Checkpoint 02 made its tests an enforced quality gate. The model catalog was the next shared boundary: model IDs existed independently in the backend and frontend, had already drifted, and allowed invalid provider/model pairs.

The API-contract redesign deliberately remains separate. First establishing a reliable model identity gives the next checkpoint a stable type around which to design request, response, and error contracts.

## Starting condition

- The backend and frontend maintained separate model lists.
- `mixtral-8x7b-32768` and `llama3-70b-8192` were already retired by Groq.
- `llama-3.3-70b-versatile` was approaching its free/developer-tier shutdown date.
- The API accepted provider and model as unrelated strings.
- An invalid model returned an error object with HTTP 200.
- Streamlit could display choices the backend rejected, and vice versa.
- The frontend configuration named one `/chat` URL, which could not naturally address a second endpoint.

## Plan

1. Replace duplicated lists with immutable model metadata and lookup functions.
2. Use a curated, cost-aware catalog containing Groq GPT-OSS 20B/120B and OpenAI GPT-4o mini.
3. Expose the catalog through a typed `GET /models` response.
4. Resolve the provider/model pair before invoking the agent.
5. Migrate frontend configuration from one endpoint URL to one backend base URL.
6. Make Streamlit fetch and validate the backend catalog without a hardcoded fallback.
7. Add offline registry, API, settings, and frontend-client tests.
8. Update CI compilation, documentation, and the learning journal.

## Decisions and alternatives

### Keep the registry curated and local

- **Decision:** Store reviewed model metadata in application code.
- **Reason:** Startup and tests remain independent of provider credentials, network access, rate limits, and provider-specific response formats.
- **Alternatives:** Query every provider at startup or maintain remote configuration immediately.
- **Tradeoff:** Availability changes require a code change and review.
- **Revisit when:** Catalog updates become frequent enough to justify a versioned configuration service with caching and failure policy.

### Use stable application keys

- **Decision:** Give each entry an application-owned key distinct from its provider-facing model ID.
- **Reason:** Provider IDs are operational identifiers and can contain provider namespaces such as `openai/gpt-oss-20b`. Application keys give clients a stable, readable identity and prepare for the next API-contract checkpoint.
- **Alternative:** Treat `(provider, model_id)` as the only identity everywhere.
- **Tradeoff:** Each model has one additional identifier whose uniqueness must be validated.

### Select a cost-aware three-model catalog

- **Decision:** Offer Groq GPT-OSS 20B and 120B plus OpenAI GPT-4o mini, with Groq GPT-OSS 20B as the default.
- **Reason:** Groq lists both GPT-OSS models as production models supporting tool use, and recommends them as replacements for the retiring Llama options. GPT-4o mini remains a low-cost OpenAI model with function calling.
- **Alternatives:** Keep obsolete IDs, move to preview models, or replace the affordable OpenAI option with the newest flagship.
- **Tradeoff:** The catalog optimizes this learning application's cost and compatibility rather than exposing every available or newest model.
- **Revisit when:** Evaluation evidence shows a quality gap or a supported model receives a deprecation notice.

### Store useful capability metadata only

- **Decision:** Expose display name, provider, model ID, context window, and tool-calling support.
- **Reason:** Every field drives validation, UI behavior, or near-term context work.
- **Alternatives:** Return only picker labels or also maintain price, rate limits, lifecycle dates, modalities, and every provider feature.
- **Tradeoff:** Clients cannot yet compare price or richer capabilities from this endpoint.
- **Revisit when:** Model comparison, multimodal input, cost reporting, or automated deprecation monitoring becomes a real feature.

### Keep model data separate from provider construction

- **Decision:** The registry describes models; the agent layer still constructs `ChatGroq` or `ChatOpenAI`.
- **Reason:** A data catalog should not create SDK clients, read credentials, or perform network side effects. Keeping those boundaries separate makes each independently testable.
- **Alternative:** Store client factories or initialized clients in registry entries.
- **Tradeoff:** Provider construction retains one explicit branch in the agent layer.
- **Revisit when:** A provider-adapter interface is justified by more providers or materially different construction behavior.

### Fetch the catalog over the API

- **Decision:** Streamlit calls `GET /models` instead of importing backend constants.
- **Reason:** The HTTP contract remains the source of truth even if frontend and backend are later deployed or versioned separately.
- **Alternatives:** Import the registry directly into Streamlit or keep synchronized constants.
- **Tradeoff:** Rendering the frontend now depends on backend availability.

### Fail closed when discovery fails

- **Decision:** Show a clear error and stop rendering model controls if the catalog cannot be fetched or validated.
- **Reason:** A hardcoded or stale fallback would recreate the drift this checkpoint removes and could submit unsupported models.
- **Alternative:** Retain a fallback list or stale cross-session cache.
- **Tradeoff:** The UI cannot prepare a request while the backend is unavailable.
- **Revisit when:** Availability requirements justify a bounded, version-aware cache with explicit staleness behavior.

### Migrate to a backend base URL

- **Decision:** Replace `BACKEND_API_URL` with `BACKEND_BASE_URL` and derive `/models` and `/chat` centrally.
- **Reason:** One authority should configure the backend host; endpoint paths are application-owned routing details.
- **Alternatives:** Configure two complete URLs or derive `/models` by rewriting the `/chat` string.
- **Tradeoff:** Existing custom `.env` files need a one-time rename and removal of the `/chat` suffix.

### Preserve the current chat error envelope

- **Decision:** Registry validation still returns the existing HTTP 200 error object during this checkpoint.
- **Reason:** Changing model discovery, request shapes, response models, and HTTP error semantics together would obscure which boundary caused a regression.
- **Alternative:** Introduce structured errors in the same pull request.
- **Tradeoff:** Incorrect HTTP semantics remain visible technical debt until Checkpoint 04.

### Test the public endpoint with Starlette's current client

- **Decision:** Add `httpx2` as a direct development dependency for FastAPI/Starlette `TestClient` tests.
- **Reason:** The installed Starlette version warns that plain `httpx` support is deprecated, while its current documentation names `httpx2` as the test-client transport.
- **Alternative:** Rely on the transitive legacy `httpx` installation.
- **Tradeoff:** The development dependency graph gains another directly managed package.

## Implementation outcome

- Added a frozen model definition and deterministic registry indexes.
- Added one validated default and centralized provider/model compatibility checks.
- Added a typed `GET /models` endpoint.
- Removed obsolete model constants from both client and server.
- Passed resolved model metadata into the agent rather than independent strings.
- Migrated frontend configuration to `BACKEND_BASE_URL`.
- Made Streamlit load, validate, group, and display backend-provided models.
- Extracted catalog transport from Streamlit rendering so it can be tested without running the UI.
- Updated CI compilation and declared the current test-client dependency directly.
- Regenerating the lock after adding `httpx2` also advanced packages allowed by existing `*` constraints, including Streamlit 1.60 to 1.61 and OpenAI 2.52 to 2.53; the complete suite and clean CI environment validated the resolved graph.

## Validation evidence

- `python -m pipenv verify` confirmed that `Pipfile.lock` matches `Pipfile`.
- Offline pytest suite: 35 tests passed locally.
- Syntax compilation passed for settings, registry, frontend catalog, agent, backend, and frontend modules.
- A clean `pipenv sync --dev` completed after stopping the project development server that held the Streamlit executable open on Windows.
- [GitHub Actions run `30980282883`](https://github.com/Ajbil/agentic-chatbot-fastapi/actions/runs/30980282883) completed successfully on the draft pull request using a clean Ubuntu/Python 3.12 environment.
- No test contacts Groq, OpenAI, or Tavily.

## Senior-engineering lessons

### Configuration becomes architecture when multiple consumers depend on it

A list duplicated in two files is not merely repetition. It creates two authorities that can disagree. The correct boundary is the service that validates and executes the selection, while clients discover its current contract.

### External identifiers should not be the only domain identity

Providers can rename, namespace, alias, or retire model IDs. A stable application key separates the product's concept of a model choice from the provider's current routing string.

### Make invalid combinations fail before side effects

Resolving provider and model together before reading credentials or constructing SDK clients makes failure deterministic and prevents partially initialized work.

### Capability flags should drive behavior

The frontend should not infer that every text model supports tools. Capability metadata allows controls to be enabled from declared behavior and prepares the design for heterogeneous models.

### Dynamic discovery is not automatically more mature

Runtime discovery can improve freshness, but also introduces authentication, latency, caching, partial provider failure, normalization, and trust questions. A reviewed static catalog is often the safer first operational model.

### Scope discipline is a senior skill

Leaving the known HTTP 200 error defect for the next bounded checkpoint is intentional. A smaller pull request produces clearer review, testing, rollback, and learning evidence.

### A lockfile is deterministic after resolution, not before it

The lock reproduces one exact dependency graph. If the manifest permits every version, adding one dependency can cause the resolver to select newer unrelated packages. Review lockfile diffs as code, test the whole graph, and introduce intentional compatibility ranges when dependency policy becomes its own checkpoint.

## Applying this elsewhere

- Find business choices duplicated between a service and its clients.
- Decide which component owns validation and execution; place authoritative data there.
- Distinguish internal stable keys from vendor-facing identifiers.
- Store only metadata that drives current behavior or an imminent feature.
- Validate references, uniqueness, and defaults when the catalog is constructed.
- Keep catalogs free of credentials, network calls, and SDK client instances.
- Design an explicit failure policy for client discovery.
- Treat vendor deprecations as planned operational work rather than surprise code failures.

## Common mistakes

- Querying provider model APIs during every application startup without a cache or failure policy.
- Copying the same model list into the frontend after adding a backend registry.
- Validating model ID without validating its provider.
- Using display labels as stable request identifiers.
- Adding metadata such as price without an ownership and refresh process.
- Keeping deprecated models available because they still work for one account tier.
- Hiding catalog failures behind a stale hardcoded fallback.
- Combining registry, canonical messages, structured errors, streaming, and provider adapters into one checkpoint.

## Explain-back questions

1. Why is a runtime provider model-list call less deterministic than a curated registry?
2. What is the difference between an application model key and a provider model ID?
3. Why should provider/model compatibility be checked before client construction?
4. When is failing closed preferable to using a cached catalog?
5. Which metadata fields belong in a registry, and how do you decide?
6. Why does the backend own the catalog even though Streamlit displays it?
7. What evidence would justify replacing the curated catalog with dynamic discovery?
8. Why is the incorrect HTTP 200 error behavior not fixed in this checkpoint?

## Deferred work

- Checkpoint 04 will define canonical chat messages, use the stable model key in requests, add typed success/error responses, and correct HTTP status semantics.
- Pricing, rate limits, lifecycle dates, and automatic provider synchronization need explicit freshness and ownership policies.
- Live provider smoke tests require separate credentials, budgets, triggers, and non-blocking failure policy.
- Provider adapters are deferred until additional providers or divergent SDK behavior create a real substitution need.
- Catalog caching, ETags, and offline frontend behavior are deferred until availability requirements justify them.
- Replacing wildcard dependency constraints with a deliberate version-update policy remains a separate packaging checkpoint.
