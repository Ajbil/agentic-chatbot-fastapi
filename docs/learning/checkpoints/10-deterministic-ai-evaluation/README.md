# Checkpoint 10 - Deterministic AI Evaluation Baseline

| Field | Value |
|---|---|
| Status | In review |
| Date | 2026-08-14 |
| Branch | `codex/deterministic-ai-evaluation` |
| Pull request | [#16 - Add deterministic AI evaluation baseline](https://github.com/Ajbil/agentic-chatbot-fastapi/pull/16) |
| Implementation commit | [`3540b79`](https://github.com/Ajbil/agentic-chatbot-fastapi/commit/3540b79) |
| Documentation commit | [`43e1dbe`](https://github.com/Ajbil/agentic-chatbot-fastapi/commit/43e1dbe) |

## Objective

Create a reviewable AI-behavior baseline that detects regressions without calling paid providers in CI, while preserving a safe, explicit path for measuring real model behavior through the application's public API.

## Why this checkpoint came next

Checkpoint 09 made conventional software quality enforceable. Unit tests can prove that our orchestration, validation, and error paths behave as programmed, but they cannot answer whether representative assistant responses follow search policy, expose provenance, resist instruction conflicts, or contain expected concepts. Before adding more agent features, the project needs a stable way to describe and compare those expectations.

## Starting condition

- `main` had 135 passing offline tests and enforced formatting, lint, types, branch coverage, compilation, and security analysis.
- Chat responses already carried typed context and search evidence.
- Provider behavior was covered only with fakes and hand testing.
- There was no versioned prompt set, scoring rubric, replay artifact, live evaluation runner, or AI-specific CI signal.
- A raw live-model gate would have been nondeterministic, credential-dependent, slow, and potentially costly.

## Plan

1. Define typed, versioned dataset, candidate, result, summary, and target schemas.
2. Build explainable normalization and scoring for contract invariants, search behavior, provenance, forbidden markers, concept groups, and length.
3. Add 15 representative cases across seven behavior categories.
4. Commit typed replay responses and deterministic JSON and Markdown baseline reports.
5. Add a CLI for dataset validation, replay checking or deliberate baseline updates, and opt-in live runs.
6. Route live evaluation through `GET /models` and `POST /chat`, with explicit cost confirmation, bounded timeouts, sequential calls, no retries, sanitized failures, and durable local reports.
7. Test schemas, scoring, persistence, CLI exit codes, HTTP boundaries, and failure continuation without external calls.
8. Add an independent credential-free `evaluation` CI job and make it a required `main` check after observing its exact GitHub name.
9. Document usage, limitations, decision reasoning, and transferable lessons.

## Decisions and alternatives

### Separate unit tests from AI evaluations

- **Decision:** Keep pytest focused on deterministic program behavior and place response-level cases under a dedicated evaluation package.
- **Reason:** A unit test answers whether code honors a specification; an evaluation measures a candidate output against behavioral expectations. Mixing them obscures ownership and encourages brittle assertions.
- **Alternative:** Encode every expected phrase as a pytest assertion.
- **Tradeoff:** Contributors must understand two quality systems and when each should change.
- **Revisit when:** Shared fixtures or reporting justify a common internal library without combining their purposes.

### Gate hard invariants and report lexical proxies separately

- **Decision:** Fail on typed execution, model identity, search permission, required or forbidden search, successful search counts, source counts, and forbidden markers. Report minimum length, concept groups, and optional-search avoidance as advisory checks.
- **Reason:** Hard invariants are objectively controlled by the application. Lexical overlap is only a proxy: a correct answer can use synonyms, and a wrong answer can contain every expected word.
- **Alternatives:** Make all rubric checks blocking, or make the entire report informational.
- **Tradeoff:** Some meaningful answer regressions require human review rather than an automatic failure.
- **Revisit when:** A proxy demonstrates low false-positive and false-negative rates on real reviewed runs.

### Use deterministic custom scoring before an evaluation framework

- **Decision:** Implement the small required scorer with Pydantic models and the standard library.
- **Reason:** The project currently needs typed artifact validation, simple invariant checks, and stable JSON diffs. A larger framework would add concepts and dependencies without improving those needs.
- **Alternatives:** Adopt promptfoo, DeepEval, Ragas, or an experiment platform immediately.
- **Tradeoff:** We own schema evolution, reporting, and integrations.
- **Revisit when:** Dataset size, experiment comparison, statistical analysis, hosted collaboration, or many evaluators exceed this package's scope.

### Normalize text but do not snapshot exact prose

- **Decision:** Apply Unicode NFKC normalization, case folding, and whitespace collapsing before lexical checks; never require the full answer string to match.
- **Reason:** Exact natural-language snapshots punish harmless wording changes and provider variability. Normalization removes irrelevant representation differences while keeping checks reviewable.
- **Alternative:** Golden-text snapshots or semantic embeddings.
- **Tradeoff:** Normalized substring checks cannot judge meaning reliably.
- **Revisit when:** A semantic metric has an independently measured threshold and stable versioning policy.

### Replay in CI and run providers manually

- **Decision:** CI scores committed typed responses and compares the entire canonical report to a reviewed baseline. Live evaluation is explicit and local.
- **Reason:** Replay is fast, free, credentialless, and bit-for-bit reproducible. Live output is necessary evidence, but unsuitable as a mandatory per-commit signal.
- **Alternatives:** Call Groq, OpenAI, and Tavily in every pull request, or never automate real calls.
- **Tradeoff:** Replay proves scorer and expected-contract stability, not that today's provider still performs well.
- **Revisit when:** A scheduled, budgeted, statistically tolerant live evaluation service exists.

### Exercise the public API boundary in live mode

- **Decision:** Validate the selected application model through `GET /models` and submit canonical requests to `POST /chat`.
- **Reason:** Evaluating a provider SDK directly would bypass registry policy, request validation, context budgeting, agent orchestration, and provenance normalization—the product behavior we actually want to assess.
- **Alternative:** Import the agent function or provider client directly.
- **Tradeoff:** The backend must already be running, and transport failures become part of the result.
- **Revisit when:** A deployed evaluation target needs authentication or a job API.

### Require explicit live confirmation and avoid retries

- **Decision:** Require `--confirm-live`, run cases sequentially, cap timeouts, make no automatic retry, continue after a failed case, and redact low-level exception text.
- **Reason:** A command that can spend credits needs visible consent. Retries alter cost and sample semantics, while stopping at the first failure loses diagnostic coverage.
- **Alternative:** Parallel execution with transparent retries.
- **Tradeoff:** Live runs are slower and transient failures appear as failures rather than being hidden.
- **Revisit when:** Rate limits, retry policy, concurrency, and cost budgets become explicit experiment metadata.

### Avoid an LLM-as-judge gate

- **Decision:** Do not ask another model to score answers in this baseline.
- **Reason:** A judge adds cost, nondeterminism, model bias, prompt-injection surface, and a new versioned dependency. The current goal is an auditable foundation.
- **Alternatives:** Pairwise or rubric-based model judging.
- **Tradeoff:** Nuanced qualities such as helpfulness, factual synthesis, and tone remain human-reviewed.
- **Revisit when:** Judge agreement is calibrated against a labeled human set and reported with model, prompt, sampling, and threshold versions.

### Version inputs and commit reproducible evidence

- **Decision:** Store dataset `v1`, JSONL candidates, canonical JSON results, and a human-readable Markdown summary in Git. Ignore raw live-run directories.
- **Reason:** Review needs to show which input, expected behavior, and output changed. JSON is machine-comparable; Markdown is fast for humans; raw live artifacts may contain volatile or sensitive provider content.
- **Alternative:** Keep only console output or commit every live run.
- **Tradeoff:** Deliberate baseline updates create reviewed repository diffs and storage growth over time.
- **Revisit when:** Artifact volume requires object storage and retention policy.

## Implementation outcome

- Added typed evaluation schemas with cross-field validation that rejects duplicate cases, invalid conversation ordering, contradictory search rules, and unusable rubrics.
- Added deterministic scoring and aggregate metrics for hard passes, advisory checks, required search, optional-search avoidance, successful provenance, and execution failure.
- Added 15 cases spanning static knowledge, required search, optional search, uncertainty, instruction resilience, multi-turn context, and conflicting evidence.
- Added committed JSONL replay responses plus canonical JSON and readable Markdown baseline reports.
- Added CLI commands for validation, replay comparison, intentional baseline regeneration, and opt-in live execution.
- Added a live HTTP adapter that tests the actual FastAPI model catalog and chat contract while isolating individual failures.
- Expanded static typing from 10 to 16 production modules and added offline tests for evaluation logic and network boundaries.
- Added an independent `evaluation` CI job without secrets or external provider calls.

## Validation evidence

- Dataset validation: `v1` is valid with 15 cases.
- Deterministic replay: 15/15 hard case passes and 45/45 advisory check passes.
- Search metrics: 4/4 required-search attempts, 4/4 optional-search avoidance, and 4/4 successful provenance.
- `python -m pipenv run ruff check .`: no lint violations.
- `python -m pipenv run ruff format --check .`: all Python files are formatted.
- `python -m pipenv run mypy`: no issues in 16 production modules.
- Offline test suite: 166 passed. The sandbox run used a repository-local pytest temporary directory because Windows denied access to its shared temp parent; this was an environment constraint, not a test failure.
- Branch coverage: 90.90% total against the enforced 80% minimum.
- All 16 application and evaluation modules compile successfully with Python 3.12.
- [CI run `31871309089`](https://github.com/Ajbil/agentic-chatbot-fastapi/actions/runs/31871309089) passed the independent `quality`, `test`, and `evaluation` jobs on the draft pull request; evaluation replay completed in 15 seconds without credentials.
- [CodeQL run `31871309092`](https://github.com/Ajbil/agentic-chatbot-fastapi/actions/runs/31871309092) passed Python analysis, and the separate CodeQL status context passed.
- GitHub `main` protection now requires the observed `evaluation` context in addition to `quality`, `test`, `Analyze (python)`, and `CodeQL`; strict up-to-date branches, administrator enforcement, resolved conversations, and the existing force-push/deletion blocks remain unchanged.
- No live provider run was made during implementation, avoiding unapproved credit usage; the HTTP behavior is verified with fakes.

## Senior-engineering lessons

### Determinism belongs in the control plane

Model prose is probabilistic, but dataset identity, execution records, tool permissions, provenance shape, scoring rules, serialization, and exit codes can be deterministic. Reliable AI systems move enforceable behavior into those controlled layers.

### Measure properties, not preferred wording

A useful evaluation asks whether search was used when freshness required it, avoided when forbidden, and accompanied by valid evidence. Exact prose is rarely the correct contract for natural-language systems.

### A metric needs an interpretation contract

Every number should say what it measures and what it cannot prove. Calling lexical overlap “quality” would create false confidence; labeling it advisory preserves its diagnostic value.

### The evaluated boundary defines the claim

Testing a provider directly supports a claim about the provider call. Testing the public application API supports a broader claim about registry selection, validation, orchestration, budgeting, search evidence, and response serialization.

### Baseline updates are product decisions

Regenerating a golden artifact is not clerical cleanup. Reviewers must determine whether the dataset, rubric, implementation, or accepted behavior changed—and why that change is desirable.

### Live experiments need operational metadata

Model key, dataset version, commit, timestamp, failures, and artifacts make a live result interpretable. Without them, a score cannot be reproduced or compared responsibly.

### Evaluation failures should be diagnosable

Case-level results preserve every check and continue past execution errors. A single aggregate score would hide whether the failure came from transport, search policy, provenance, or response content.

## Applying this elsewhere

- Begin with business-relevant cases and explicit behavioral properties.
- Separate objective invariants from heuristic metrics and human judgment.
- Version dataset, rubric, model target, code revision, and result artifacts.
- Reuse the product boundary when the goal is to measure end-to-end behavior.
- Keep merge gates credentialless and deterministic; schedule or manually approve costly live experiments.
- Make baseline changes visible in normal code review.
- Preserve per-case failure evidence instead of only aggregate scores.
- Calibrate sophisticated judges against human labels before trusting their thresholds.

## Common mistakes

- Treating unit-test coverage as proof of answer quality.
- Snapshotting exact generated prose.
- Making unstable provider calls mandatory in every pull request.
- Using an LLM judge without versioning or human calibration.
- Combining hard invariants and weak proxies into one unexplained score.
- Updating a baseline automatically whenever it fails.
- Evaluating a provider SDK while claiming end-to-end product quality.
- Retrying live failures invisibly and comparing the result with non-retried runs.
- Committing credentials, private prompts, or sensitive raw responses.
- Reporting “grounded” merely because a search source exists.

## Explain-back questions

1. Why are conventional unit tests insufficient for an AI product, and what do they still prove well?
2. Which evaluation properties are safe to make merge-blocking in this checkpoint, and why?
3. Why are concept groups and minimum length advisory rather than hard gates?
4. Why is exact answer snapshotting especially brittle for generated text?
5. What does Unicode and whitespace normalization improve, and what semantic problem does it not solve?
6. What does deterministic replay prove, and what does it not prove about the current provider model?
7. Why should live evaluation use the public FastAPI boundary instead of the provider client?
8. Why does live mode require explicit confirmation, sequential execution, and no automatic retries?
9. Why should one failed live case not stop the rest of the run?
10. Why is an LLM judge deferred, and what evidence would be needed before adopting one?
11. What must a reviewer inspect before accepting a changed baseline report?
12. Why are dataset version, model key, commit, and timestamp essential experiment metadata?
13. How do search permission, search attempt, successful execution, and source provenance represent different claims?
14. Why can a 100% advisory lexical score still accompany a factually wrong answer?
15. How would you evolve this baseline when the dataset grows to hundreds of cases and multiple models?

## Deferred work

- Human-labeled factuality, usefulness, style, and claim-level grounding evaluation.
- Calibrated semantic or LLM judging with agreement and cost evidence.
- Scheduled live experiments, trend storage, regression thresholds, and model comparison.
- Dataset sampling from privacy-reviewed production traces.
- Authentication, persistent conversations, observability, deployment, service objectives, and load or resilience testing.
