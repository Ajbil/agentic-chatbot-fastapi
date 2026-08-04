# Checkpoint 01 — Deterministic, Testable Configuration

| Field | Value |
|---|---|
| Status | Complete |
| Date | 2026-08-03 |
| Branch | `agent/config-foundation` |
| Pull request | [#1 — Make configuration deterministic](https://github.com/Ajbil/agentic-chatbot-fastapi/pull/1) |
| Implementation commit | [`299664a`](https://github.com/Ajbil/agentic-chatbot-fastapi/commit/299664a) |
| Merge commit | [`aa46fff`](https://github.com/Ajbil/agentic-chatbot-fastapi/commit/aa46fff) |

## Objective

Create one predictable configuration boundary, validate credentials only when their provider or tool is requested, make dependency ownership explicit, and establish offline automated tests.

## Why this checkpoint came next

Chat history, streaming, retrieval, model comparison, and explicit LangGraph workflows would all depend on the same configuration and provider boundaries. Building those features first would multiply a fragile startup model across more code and make failures harder to isolate.

This checkpoint intentionally improves the foundation without redesigning the API or model registry at the same time.

## Starting condition

- Importing `ai_agent.py` immediately read three global environment variables and raised unless all were present.
- A Groq-only request still required an OpenAI key, and a non-search request still required Tavily.
- `.env` loading worked implicitly through `pipenv run`, coupling configuration behavior to the launch command.
- The frontend backend URL was hard-coded and HTTP requests had no timeout.
- `langchain`, `langchain-core`, and `requests` were imported directly but declared only transitively.
- `langchain-community` and `langgraph` were declared directly but not imported by the application.
- No automated tests protected configuration or provider selection.

## Plan

1. Correct dependency ownership and add pytest as a development dependency.
2. Introduce typed settings loaded explicitly from environment variables and `.env`.
3. Remove import-time credential validation.
4. Validate only the selected provider key and conditionally require Tavily.
5. Make frontend connection values configurable and add a request timeout.
6. Add fake-provider tests that never contact paid services.
7. Update documentation, validate the lockfile and code, then publish a draft PR.

## Decisions and alternatives

### Use `pydantic-settings`

- **Decision:** Introduce a `Settings` model as the single configuration boundary.
- **Reason:** The project already uses Pydantic. The settings package adds typed fields, defaults, validation, environment precedence, `.env` support, and easy constructor overrides for tests.
- **Alternatives:** Continue using `os.getenv()` directly or load values with `python-dotenv` into untyped globals.
- **Tradeoff:** It adds a direct dependency and a small abstraction that must be understood.
- **Revisit when:** Configuration comes from a remote secret manager or needs runtime reload; the settings sources can then be extended deliberately.

### Model credentials as optional settings

- **Decision:** Store provider keys as `SecretStr | None` and enforce requirements at the feature boundary.
- **Reason:** A credential is globally available configuration but only conditionally required behavior. Startup should not fail because an unused integration is unavailable.
- **Alternative:** Make every credential a required settings field and fail fast at process startup.
- **Tradeoff:** Some configuration errors move from startup to the first request using that integration.
- **Revisit when:** A deployed service has one fixed provider contract; in that case, validating that provider at deployment startup may be preferable.

### Validate before constructing clients

- **Decision:** Resolve the provider, validate all credentials needed by the request, and only then build model and search clients.
- **Reason:** Failure remains deterministic and avoids partially initialized work.
- **Alternative:** Construct each client first and allow its library to report missing credentials.
- **Tradeoff:** The application owns a small amount of provider-specific validation logic.

### Use `SecretStr`

- **Decision:** Represent keys using Pydantic's masked secret type.
- **Reason:** Normal representations show `**********`, reducing accidental leakage through debugging and logs.
- **Alternative:** Store keys as ordinary strings.
- **Tradeoff:** Libraries still require an explicit plain string at the final integration boundary; masking is defense in depth, not encryption.

### Inject settings into the agent function

- **Decision:** Accept an optional `Settings` instance while retaining a cached application default.
- **Reason:** Production callers remain simple, while tests can supply deterministic configuration without modifying the real `.env` or global process state.
- **Alternatives:** Patch module globals or reload modules after changing environment variables.
- **Tradeoff:** The internal function signature gains one parameter.

### Keep Pipenv for this checkpoint

- **Decision:** Use the existing Pipfile and lockfile through `python -m pipenv`.
- **Reason:** The environment and lock were already valid. Migrating to uv or `pyproject.toml` simultaneously would make it harder to separate packaging failures from configuration failures.
- **Alternatives:** Move to uv or use `venv` plus requirements files.
- **Tradeoff:** Pipenv is not the only modern choice, and its executable was not on this machine's `PATH`; using it as a Python module avoids that local issue.
- **Revisit when:** Packaging, build metadata, deployment, or tool speed becomes its own bounded checkpoint.

### Declare only owned direct dependencies

- **Decision:** Add packages imported by application code and remove unused direct declarations.
- **Reason:** A transitive package can disappear when its parent changes. Direct declarations communicate intentional contracts. Conversely, unused direct dependencies misrepresent the architecture and increase maintenance surface.
- **Tradeoff:** `langgraph` remains in the lockfile transitively because LangChain needs it, but the application will not claim direct ownership until it defines a graph explicitly.

### Test with pytest and fake providers

- **Decision:** Exercise settings and orchestration with injected fakes and no network calls.
- **Reason:** Credential selection and agent wiring are deterministic code. Tests should be fast, repeatable, free, and independent of provider availability or model randomness.
- **Alternatives:** Call real providers in unit tests or test only through manual UI runs.
- **Tradeoff:** Fakes do not prove that current provider SDKs accept every request at runtime; a small separate integration-test layer can cover that later.

## Implementation outcome

- Added centralized typed settings with explicit project `.env` loading.
- Added configurable `BACKEND_API_URL` and a validated request timeout between 0 and 300 seconds.
- Removed module-import credential failures.
- Added provider-aware and search-aware credential validation.
- Added a frontend HTTP timeout.
- Corrected direct and development dependencies and regenerated the lockfile through Pipenv.
- Added offline tests for defaults, overrides, secret masking, invalid timeouts, provider selection, search requirements, agent import behavior, and fake replies.
- Updated setup and configuration documentation.

## Validation evidence

- `python -m pipenv verify` confirmed that `Pipfile.lock` matches `Pipfile`.
- `python -m pipenv run python -m pytest -q` reported 13 passing tests.
- Python syntax compilation passed for the settings, agent, backend, and frontend modules.
- Git whitespace validation passed after removing two trailing blank lines found during staged review.
- `.env` was not staged.
- A staged-content scan found no common API-token patterns.
- No test contacted Groq, OpenAI, or Tavily.

## Senior-engineering lessons

### Configuration is an application boundary

Environment variables are untyped external input. Central settings convert them into validated application values once, making defaults, constraints, and supported names visible.

### Importing a module should not perform unrelated validation

Imports occur in servers, test discovery, scripts, documentation tools, and interactive shells. An import-time failure caused by an unused provider creates hidden coupling and prevents otherwise valid workflows.

### Fail fast means fail at the correct boundary

Failing early is useful only when the failure is relevant. A Groq request should immediately fail for a missing Groq key, but it should not fail because OpenAI is unconfigured. The correct boundary is the requested capability.

### Dependency manifests express intent; lockfiles express resolution

The manifest lists dependencies the project intentionally owns. The lockfile captures exact direct and transitive versions plus hashes. Generated lockfiles should be produced by the resolver rather than hand-edited.

### Test deterministic and nondeterministic behavior differently

Provider selection, configuration validation, payload construction, and tool wiring have deterministic expected results and belong in unit tests. Answer quality, groundedness, and model behavior require evaluations rather than exact string assertions against live models.

### Timeouts are part of correctness

An outbound request without a timeout can block indefinitely when a downstream service stalls. Making the timeout configurable allows different local and deployment budgets while retaining a safe default.

### Secret masking is not secret management

`SecretStr` reduces accidental display, but it does not encrypt values, rotate compromised credentials, or replace `.gitignore` and deployment secret stores. Security relies on multiple layers.

## Applying this elsewhere

- Identify configuration access scattered across modules and centralize it behind a typed boundary.
- Separate values that must exist at process startup from values required only by optional capabilities.
- Validate external configuration before constructing clients or performing side effects.
- Declare every package imported directly by application code.
- Inject configuration and external clients to make deterministic tests independent of networks and secrets.
- Add explicit timeouts at every network boundary.
- Keep unit tests free of paid or nondeterministic services; place live checks in a separate integration suite.

## Common mistakes

- Calling every environment variable “required” because it exists in `.env.example`.
- Loading and validating secrets in module-level globals.
- Relying on a transitive dependency because it happens to be installed today.
- Editing a generated lockfile manually.
- Treating masked secrets as encrypted secrets.
- Using live LLM calls as ordinary unit tests.
- Omitting timeouts because requests usually complete during local development.
- Combining configuration, API redesign, model registry, and packaging migration into one difficult-to-review change.

## Explain-back questions

1. Why can import-time credential validation break tests and tooling unrelated to that provider?
2. When should a credential be required at startup, and when should it be required at feature use?
3. What different information do `Pipfile` and `Pipfile.lock` preserve?
4. Why does dependency injection make the agent function easier to test?
5. What does `SecretStr` protect against, and what does it not protect against?
6. Why are fake-provider tests insufficient for evaluating answer quality?
7. Why is a network timeout part of application correctness rather than merely performance tuning?

## Deferred work

- Model/provider compatibility remains duplicated between backend and frontend; the next checkpoint should introduce a central model registry.
- Configuration exceptions still surface as generic server errors; the API-contract checkpoint should map them to structured HTTP responses.
- Broader endpoint tests, GitHub CI, dependency version policy, and live opt-in integration tests remain separate checkpoints.
- The project still uses LangGraph indirectly through LangChain; explicit graph design comes after chat, evidence, and retrieval foundations.
