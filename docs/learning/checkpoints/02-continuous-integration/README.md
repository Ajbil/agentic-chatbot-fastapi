# Checkpoint 02 — Continuous Integration Quality Gate

| Field | Value |
|---|---|
| Status | In review |
| Date | 2026-08-04 |
| Branch | `agent/ci-foundation` |
| Pull request | [#2 — Add continuous integration quality gate](https://github.com/Ajbil/agentic-chatbot-fastapi/pull/2) |
| Implementation commit | [`c40517a`](https://github.com/Ajbil/agentic-chatbot-fastapi/commit/c40517a) |

## Objective

Make every change prove automatically that its dependency lock is consistent, its offline tests pass, and its application modules compile before it can be merged into `main`.

## Why this checkpoint comes next

Checkpoint 01 created deterministic configuration and the first offline test suite. Until those checks run outside one developer's laptop, however, their protection depends on memory and local machine state. The next product changes—especially a model registry and stronger API contracts—will touch shared boundaries and need a trustworthy regression signal.

CI therefore comes before the next feature checkpoint. It turns the tests we already own into a repeatable team rule and establishes the quality gate that future checkpoints can extend.

## Starting condition

- Thirteen offline tests passed locally, but GitHub did not execute them.
- Reviewers could not see automated evidence on a pull request.
- A valid `Pipfile.lock` existed, but no remote check prevented manifest/lock drift.
- Compilation was checked manually and could be forgotten.
- `main` did not require a pull request or passing status check.
- The repository had no workflow permissions or cancellation policy to reason about.

## Plan

1. Preserve the original project analysis as immutable historical reference material.
2. Add one GitHub Actions job for Ubuntu and Python 3.12.
3. Verify the lockfile, install locked development dependencies, run offline tests, and compile application modules.
4. Add a visible CI badge to the project README.
5. Record the decisions, tradeoffs, and reusable lessons in this checkpoint.
6. Validate locally, publish a draft pull request, and inspect the first hosted run.
7. Protect `main` with a lightweight ruleset requiring pull requests, resolved discussions, and the passing `test` check.

## Decisions and alternatives

### Use GitHub Actions

- **Decision:** Run CI with a repository-local GitHub Actions workflow.
- **Reason:** The source and pull-request workflow already live on GitHub. Actions gives direct PR status checks, requires no separate service account, and keeps the executable policy beside the code.
- **Alternatives:** Jenkins, CircleCI, GitLab CI, or a local-only script.
- **Tradeoff:** The workflow uses GitHub-specific syntax and hosted-runner behavior.
- **Revisit when:** The project moves hosting platforms, needs private infrastructure, or requires workloads hosted runners cannot support.

### Start with one operating system and one Python version

- **Decision:** Test Ubuntu with Python 3.12, the version declared by the project.
- **Reason:** This checkpoint's goal is to create a reliable baseline, not claim broad compatibility. One environment gives fast, understandable feedback and avoids paying matrix cost before a compatibility promise exists.
- **Alternatives:** Test multiple Python versions and Windows, macOS, and Linux immediately.
- **Tradeoff:** The workflow does not prove portability to other versions or operating systems.
- **Revisit when:** The project publishes a supported-version policy, becomes a reusable library, or targets a deployment platform with materially different behavior.

### Keep CI offline and deterministic

- **Decision:** Use fake providers and provide no Groq, OpenAI, or Tavily secrets to the test job.
- **Reason:** A required merge gate must distinguish code regressions from quota limits, network failures, model variability, and provider outages. Pull requests—especially forks—should not receive production credentials.
- **Alternatives:** Call live providers during every pull request or rely only on manual testing.
- **Tradeoff:** CI does not prove that provider APIs and SDK integrations currently work end to end.
- **Revisit when:** Add a separate opt-in or scheduled integration suite with restricted credentials, spending limits, and tolerant assertions.

### Reproduce dependencies from the lockfile

- **Decision:** Pin the CI Pipenv version, run `pipenv verify`, and install with `pipenv sync --dev`.
- **Reason:** `verify` detects a stale lock before installation, while `sync` installs the exact resolved versions instead of resolving a new environment. Pinning the installer prevents an unannounced tooling update from changing CI behavior.
- **Alternatives:** Run `pipenv install`, use unpinned Pipenv, or migrate packaging tools inside this checkpoint.
- **Tradeoff:** The Pipenv version must be updated intentionally, and the workflow retains the project's current packaging choice.
- **Revisit when:** Packaging migration becomes its own bounded checkpoint or a tool defect requires an upgrade.

### Cache by the lockfile

- **Decision:** Let `setup-python` cache Pipenv dependencies using `Pipfile.lock` as the dependency path and place the virtual environment in the project.
- **Reason:** The lockfile is the correct invalidation key: dependency changes produce a new cache, while unchanged pull requests reuse downloads and environment work.
- **Alternatives:** No cache or a broad cache key unrelated to dependency state.
- **Tradeoff:** Caching adds a small amount of workflow complexity and never replaces lock verification.
- **Revisit when:** Cache restore time exceeds installation time or the dependency tool changes.

### Name one stable required check

- **Decision:** Expose a single job named `test` and require that check on `main`.
- **Reason:** Branch rules refer to status-check names. A simple stable name makes the policy obvious and avoids coupling protection to internal step names.
- **Alternatives:** Several initially required jobs or no required checks.
- **Tradeoff:** Tests, lock verification, and compilation share one result, so failure classification requires opening the job log.
- **Revisit when:** Independent linting, type checking, security scanning, or test suites benefit from parallel execution and separate ownership.

### Apply least-privilege workflow permissions

- **Decision:** Grant only `contents: read`.
- **Reason:** Tests need to read the repository, not modify code, issues, packages, or pull requests. Restricting the token limits damage if a dependency or script is compromised.
- **Alternatives:** Accept GitHub's broader defaults or grant write access for convenience.
- **Tradeoff:** Future steps that publish artifacts or write PR comments will need explicit additional permissions.
- **Revisit when:** Add a step that genuinely needs another permission, granting only that scope.

### Cancel superseded runs

- **Decision:** Cancel an in-progress run when a newer commit arrives on the same ref.
- **Reason:** Reviewers care about the newest commit. Continuing obsolete runs consumes time and hosted-runner capacity while potentially surfacing stale results.
- **Alternative:** Allow every pushed commit to finish.
- **Tradeoff:** Earlier commits may not retain a completed CI result.
- **Revisit when:** Historical per-commit evidence becomes a compliance requirement.

### Protect `main` with a lightweight ruleset

- **Decision:** Require a pull request, resolved review discussions, and an up-to-date passing `test` check; block force pushes and branch deletion, but require zero approvals for this solo learning repository.
- **Reason:** Automation has value only if it cannot be casually bypassed. Zero approvals avoids pretending that a solo repository has independent review while still enforcing the PR and CI workflow.
- **Alternatives:** Leave `main` unprotected, require self-approval, or impose enterprise-style signed commits and linear history immediately.
- **Tradeoff:** The repository owner can still administer settings, and the policy does not provide independent human review.
- **Revisit when:** Collaborators join; then require at least one approval and consider code-owner review for sensitive paths.

## Implementation outcome

- Preserved the supplied initial analysis byte-for-byte with provenance and a checksum.
- Added a GitHub Actions workflow for pull requests to `main`, pushes to `main`, and manual runs.
- Added lock verification, locked dependency installation, offline tests, and syntax compilation to the `test` job.
- Restricted the workflow token to read-only repository contents and enabled cancellation of superseded runs.
- Added a README badge that links to workflow history.
- Published the work as a draft pull request for review before merge.

## Validation evidence

- The preserved analysis SHA-256 matched `AB46597D3E454CABFB4355FB7CBF436DEBAE84A2A45E1E1E4FA642D96B1FDED7`.
- `python -m pipenv verify` confirmed that `Pipfile.lock` matches `Pipfile`.
- `python -m pipenv run python -m pytest -q` reported 13 passing tests.
- Syntax compilation passed for `config.py`, `ai_agent.py`, `backend.py`, and `frontend.py`.
- Git whitespace validation and a repository secret-pattern scan passed.
- GitHub Actions evidence: Pending first hosted run.
- Main ruleset evidence: Pending configuration after the hosted check exists.

## Senior-engineering lessons

### CI is a controlled experiment

A CI runner starts from a clean machine, reconstructs dependencies from versioned inputs, and executes the same assertions for every change. Its main value is not automation alone; it reveals hidden assumptions that a long-lived developer environment can conceal.

### A quality check and an enforced quality gate are different

A workflow reports evidence. A branch ruleset turns selected evidence into merge policy. Without enforcement, a red check is advisory; without a trustworthy check, protection is ceremony.

### Required checks should be deterministic

Flaky required checks train developers to rerun or bypass failures instead of investigating them. Keep network-dependent, paid, timing-sensitive, and probabilistic evaluations outside the required unit-test gate unless their reliability is engineered explicitly.

### Compatibility matrices are promises, not decoration

Every matrix entry claims support and consumes maintenance time. Test the environments the project promises today, then expand from explicit product or deployment requirements rather than from a desire to make the workflow look comprehensive.

### Pin tools but schedule their renewal

Pinning improves reproducibility; never updating creates security and compatibility debt. Mature teams combine pins with deliberate dependency-renovation work and review release notes before changing foundational tooling.

### Permissions are part of pipeline design

CI executes repository code with an identity. Treat its token, secrets, third-party actions, and event triggers as a security boundary—not merely YAML needed to make tests run.

### Preserve reasoning separately from changing truth

Historical analysis explains why work was prioritized. Current checkpoint records explain what was actually decided and demonstrated. Keeping both prevents hindsight from rewriting the learning journey.

## Applying this elsewhere

- Start with fast deterministic checks already trusted locally.
- Recreate dependencies from a committed lockfile instead of resolving afresh.
- Match the initial runner matrix to the compatibility contract you actually support.
- Pin foundational CI tools and third-party actions intentionally.
- Grant the workflow token only the permissions its steps require.
- Keep secrets out of untrusted pull-request jobs.
- Give required jobs stable, descriptive names.
- Enforce passing checks through branch policy after observing the real check name.
- Separate required unit checks from scheduled or opt-in integration and AI evaluation suites.

## Common mistakes

- Adding CI before tests are deterministic, then normalizing reruns as a solution to flakiness.
- Resolving fresh dependency versions on every run despite committing a lockfile.
- Creating a large OS/version matrix without owning the compatibility promise.
- Giving workflows write permissions or production secrets by default.
- Caching without a dependency-derived invalidation key.
- Renaming a required job without updating branch rules.
- Assuming a green unit suite proves live provider compatibility or answer quality.
- Requiring approvals in a solo project and treating self-approval as meaningful independent review.
- Adding lint, type checking, deployment, and dependency automation in the same foundational PR.

## Explain-back questions

1. What hidden assumptions can a clean CI runner reveal that a developer laptop may hide?
2. Why do `pipenv verify` and `pipenv sync` protect against different dependency failures?
3. Why should live LLM calls not be part of the required pull-request unit-test gate?
4. When does expanding a Python or operating-system matrix become justified?
5. How do workflow permissions limit supply-chain risk?
6. What is the difference between a status check and a branch ruleset?
7. Why is zero required approvals more honest than self-approval in a solo repository?
8. What should trigger splitting one CI job into multiple required checks?

## Deferred work

- Central model/provider registry and compatibility validation belong to the next product checkpoint.
- Structured API error contracts and broader endpoint tests remain a later checkpoint.
- Linting, formatting, static type checking, security scanning, and dependency-update automation should each be introduced with an explicit policy and baseline rather than bundled here.
- Live provider integration tests and AI answer-quality evaluations need separate triggers, credentials, budgets, and acceptance criteria.
- Deployment is intentionally excluded; continuous integration should become trustworthy before continuous delivery is introduced.
