# Engineering Learning Journal

This journal records how the project evolves and, more importantly, why each change is made. It is intended to remain useful when revisiting this repository or making similar decisions in another project.

The journal is not a raw development transcript. Each checkpoint is a curated engineering record containing the problem, plan, tradeoffs, evidence, and reusable lessons.

## Checkpoints

| Checkpoint | Topic | Status | References |
|---|---|---|---|
| [00](checkpoints/00-repository-foundation/README.md) | Repository and GitHub foundation | Complete | [Commit `1085458`](https://github.com/Ajbil/agentic-chatbot-fastapi/commit/1085458) |
| [01](checkpoints/01-configuration-foundation/README.md) | Deterministic, testable configuration | Complete | [PR #1](https://github.com/Ajbil/agentic-chatbot-fastapi/pull/1), [merge commit `aa46fff`](https://github.com/Ajbil/agentic-chatbot-fastapi/commit/aa46fff) |
| [02](checkpoints/02-continuous-integration/README.md) | Continuous integration quality gate | In review | Draft PR pending |

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
