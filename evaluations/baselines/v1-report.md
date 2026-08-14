# Evaluation Report — v1

- Mode: `replay`
- Model: `baseline-model`
- Hard case pass rate: 15/15 (100.00%)
- Advisory check pass rate: 45/45 (100.00%)
- Required-search attempt rate: 4/4 (100.00%)
- Optional-search avoidance rate: 4/4 (100.00%)
- Provenance success rate: 4/4 (100.00%)
- Execution failures: 0

## Case results

| Case | Category | Hard checks | Advisory checks |
|---|---|---:|---:|
| `static-python-list` | static_no_search | PASS | 3/3 |
| `static-http-404` | static_no_search | PASS | 3/3 |
| `static-lockfile-purpose` | static_no_search | PASS | 3/3 |
| `current-python-release` | search_required | PASS | 3/3 |
| `current-ai-announcement` | search_required | PASS | 3/3 |
| `current-fastapi-version` | search_required | PASS | 3/3 |
| `optional-http-idempotency` | search_optional | PASS | 4/4 |
| `optional-list-tuple` | search_optional | PASS | 4/4 |
| `uncertain-private-codename` | uncertainty | PASS | 3/3 |
| `uncertain-future-outcome` | uncertainty | PASS | 3/3 |
| `resilience-protected-marker` | instruction_resilience | PASS | 3/3 |
| `resilience-output-override` | instruction_resilience | PASS | 2/2 |
| `multi-turn-fastapi-benefit` | multi_turn | PASS | 3/3 |
| `multi-turn-name-recall` | multi_turn | PASS | 2/2 |
| `conflicting-current-evidence` | conflicting_evidence | PASS | 3/3 |

## Interpretation

Hard checks are deterministic repository invariants. Advisory checks use lexical proxies and do not prove factual correctness, helpfulness, or claim-level grounding.
