# Engineering Learning Journal

This journal records how the project evolves and, more importantly, why each change is made. It is intended to remain useful when revisiting this repository or making similar decisions in another project.

The journal is not a raw development transcript. Each checkpoint is a curated engineering record containing the problem, plan, tradeoffs, evidence, and reusable lessons.

## Checkpoints

| Checkpoint | Topic | Status | References |
|---|---|---|---|
| [00](checkpoints/00-repository-foundation/README.md) | Repository and GitHub foundation | Complete | [Commit `1085458`](https://github.com/Ajbil/agentic-chatbot-fastapi/commit/1085458) |
| [01](checkpoints/01-configuration-foundation/README.md) | Deterministic, testable configuration | Complete | [PR #1](https://github.com/Ajbil/agentic-chatbot-fastapi/pull/1), [merge commit `aa46fff`](https://github.com/Ajbil/agentic-chatbot-fastapi/commit/aa46fff) |
| [02](checkpoints/02-continuous-integration/README.md) | Continuous integration quality gate | Complete | [PR #2](https://github.com/Ajbil/agentic-chatbot-fastapi/pull/2), [merge commit `63ec2d2`](https://github.com/Ajbil/agentic-chatbot-fastapi/commit/63ec2d2) |
| [03](checkpoints/03-model-registry/README.md) | Backend-owned model registry | Complete | [PR #3](https://github.com/Ajbil/agentic-chatbot-fastapi/pull/3), [merge commit `5bded57`](https://github.com/Ajbil/agentic-chatbot-fastapi/commit/5bded57) |
| [04](checkpoints/04-chat-api-contract/README.md) | Canonical chat API contract | Complete | [PR #4](https://github.com/Ajbil/agentic-chatbot-fastapi/pull/4), [merge commit `6bb67e9`](https://github.com/Ajbil/agentic-chatbot-fastapi/commit/6bb67e9) |
| [05](checkpoints/05-session-chat-history/README.md) | Session-owned chat history | Complete | [PR #5](https://github.com/Ajbil/agentic-chatbot-fastapi/pull/5), [merge commit `5567d2f`](https://github.com/Ajbil/agentic-chatbot-fastapi/commit/5567d2f) |
| [06](checkpoints/06-context-window-management/README.md) | Context budgeting and transparent recent-window trimming | In progress | Pull request pending |

## Reference material

The [reference archive](reference/README.md) preserves the original project analysis and roadmap that informed the checkpoint sequence. It is kept as historical input; checkpoint records describe the decisions and outcomes that followed.

## Checkpoint workflow

Every checkpoint follows the same learning loop:

```text
Understand the current system
  -> define one bounded problem
  -> compare meaningful alternatives
  -> agree on a plan
  -> implement on a branch
  -> test and inspect evidence
  -> document transferable lessons
  -> review the pull request
  -> merge
```

This prevents two common failure modes: accumulating features without understanding them and accumulating documentation that no longer matches the code.

## Documentation rules

- Create a checkpoint from [the template](checkpoint-template.md) when planning begins.
- Update its outcome and evidence before the pull request is merged.
- Record rejected alternatives and the context behind the decision; a decision without context is difficult to reuse correctly.
- Link commits and pull requests instead of duplicating large code diffs.
- Never include API keys, tokens, private URLs, or copied `.env` values.
- Prefer principles and evidence over claims such as “best practice” without an explanation.
- Treat completed records as historical documents. Correct factual errors, but do not silently rewrite the original context after the architecture changes.

## Plans versus architectural decision records

These checkpoint records are deliberately lightweight. They are suitable for changes local to this learning project. If a future decision has long-lived system-wide consequences—such as selecting a database, authentication architecture, deployment platform, or event model—it should also receive a dedicated Architecture Decision Record under a future `docs/decisions/` directory.
