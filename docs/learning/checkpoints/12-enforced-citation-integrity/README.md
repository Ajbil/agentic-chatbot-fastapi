# Checkpoint 12 - Enforced Citation Integrity and Grounded Answer Contract

| Field | Value |
|---|---|
| Status | In progress |
| Date | 2026-08-16 |
| Branch | `codex/grounded-citation-contract` |
| Pull request | Pending |

## Objective

Turn retrieved web sources from passive provenance into an enforceable response contract. Every grounded answer must use stable inline source identifiers that map to evidence returned in the same request. Invalid drafts receive one bounded repair attempt and never reach the user as trusted streamed output.

## Why this checkpoint came next

Checkpoint 11 made model, tool, and validation transitions explicit application code. That created the correct insertion points for evidence normalization and final-answer validation. Adding citation rules before owning the graph would have hidden critical behavior inside framework middleware or response post-processing.

The provenance checkpoint answered, “What did search return?” This checkpoint answers a narrower additional question: “Do references in the answer identify sources this request actually retrieved?” It deliberately does not claim that a source semantically proves every nearby sentence.

## Starting condition

- Search executions returned bounded titles, URLs, and snippets but no stable IDs.
- A model could omit citations or invent citation-like text without a deterministic check.
- Search answers streamed before any grounding check could complete.
- Evaluation v1 checked search use and source counts, not response-to-source integrity.

## Plan

1. Assign deterministic request-scoped IDs to normalized sources and reuse IDs for repeated URLs.
2. Add typed grounding evidence to every successful response.
3. Normalize provider output before it re-enters model context.
4. Validate final inline markers against normalized request state.
5. Permit one no-tool citation repair, then fail safely.
6. Buffer search-grounded drafts until validation succeeds.
7. Add evaluation schema and baseline v2 while preserving v1 history.
8. Cover success, repair, rejection, deduplication, streaming, API, UI, and evaluation behavior with offline tests.

## Decisions and alternatives

### Use request-scoped IDs `S1` through `S6`

- **Decision:** Assign IDs in first-seen order after URL validation and reuse an ID when the normalized URL repeats.
- **Reason:** Three searches with at most two exposed sources each create a six-source domain. Short IDs are easy for models and people, while request scope avoids pretending ephemeral evidence is globally durable.
- **Alternatives:** Cite raw URLs, use array indexes, hash URLs, or persist global source identities.
- **Tradeoff:** `S1` means something only inside one response.
- **Revisit when:** Conversations and evidence become durable stored records.

### Normalize tool output before the second model call

- **Decision:** Replace raw Tavily result messages with application-owned `SearchExecution` JSON before another model invocation.
- **Reason:** Generator, validator, API, and UI must share one source vocabulary. Early normalization also keeps private provider metadata behind the trust boundary.
- **Alternatives:** Keep raw output and construct a second prompt, normalize only at HTTP serialization, or make the provider adapter emit the public contract.
- **Tradeoff:** Orchestration owns a provider-to-domain mapping that must evolve when provider output changes.
- **Revisit when:** Multiple search providers justify dedicated adapters behind a common port.

### Validate exact markers mechanically

- **Decision:** A grounded answer needs at least one `[S<n>]` marker and every distinct marker must exist in request state.
- **Reason:** Set membership is deterministic, cheap, explainable, and CI-friendly. It stops missing and invented references without another probabilistic model.
- **Alternatives:** Trust prompting, parse arbitrary URLs and footnotes, or use an LLM judge.
- **Tradeoff:** This proves reference integrity, not semantic entailment.
- **Revisit when:** A labeled grounding dataset can support a measured semantic verifier.

### Allow exactly one repair without tools

- **Decision:** Give the model one private correction instruction. Reject repair-time tool calls and fail if the second draft is invalid.
- **Reason:** One rewrite recovers formatting omissions while bounding latency, cost, and graph cycles. Searching again would mutate evidence during validation.
- **Alternatives:** Fail immediately, rewrite strings in application code, allow unlimited retries, or allow more searches.
- **Tradeoff:** A useful answer may fail when a model ignores the correction, but failure is explicit rather than silently ungrounded.
- **Revisit when:** Production telemetry measures repair frequency, success, latency, and cost.

### Buffer grounded drafts but preserve ordinary streaming

- **Decision:** Hold chunks when successful search evidence exists and release only the validated draft. Preserve progressive streaming otherwise.
- **Reason:** Displayed streaming bytes cannot be recalled. Releasing an invalid draft before correcting it would violate the guarantee.
- **Alternatives:** Disable all streaming, label provisional drafts, or validate token by token.
- **Tradeoff:** Grounded answers have higher time-to-first-answer, though status events still show progress.
- **Revisit when:** The protocol gains product-approved provisional-content semantics.

### Version evaluation instead of rewriting history

- **Decision:** Add v2 dataset, responses, and reports as active defaults while retaining v1.
- **Reason:** Evaluation is evidence only when its rubric is reproducible. Mutating v1 would erase what Checkpoint 10 measured.
- **Alternatives:** Change v1 in place, rely on unit tests, or run live providers in CI.
- **Tradeoff:** Multiple baseline artifacts need an eventual retention policy.
- **Revisit when:** Old versions no longer help explain architectural evolution.

## Implementation walkthrough

### Contract layer

`SearchSource` requires a bounded source ID. `SearchEvidence` enforces a one-to-one relationship between IDs and normalized URLs. `GroundingEvidence` records `not_applicable`, `unavailable`, or `cited`, the cited IDs, and whether repair ran. `ChatResponse` cross-validates reply markers, grounding, and retrieved sources so no success path can construct contradictory evidence.

### Workflow layer

```text
tools -> normalize_search_results -> model -> validate_citations
                                            |          |
                                            | valid    | invalid once
                                            v          v
                                           END        model
```

Normalization validates URLs, bounds fields, removes duplicates, assigns IDs, and stores typed executions. The model receives a trusted policy listing only available IDs. Validation accepts exact known markers, initiates one repair for invalid output, and rejects tools during repair.

### Streaming and UI

Grounded chunks remain private until validation marks the final draft valid. A rejected first draft is discarded. The terminal response carries grounding evidence, and Streamlit renders matching source-ID links plus a repair indicator. The UI calls this reference integrity rather than factual proof.

### Evaluation layer

Evaluation v2 adds minimum cited-source expectations and a hard grounding-consistency check. Its baseline contains typed grounding metadata and its report includes citation-integrity totals. Replay remains deterministic; live evaluation remains opt-in because providers change and may cost money.

## Verification strategy

- Contract tests reject missing, invented, and contradictory references.
- Real graph tests cover valid output, successful and failed repair, forbidden repair tools, and repeated-URL ID reuse.
- Streaming tests prove the invalid first draft is absent from deltas.
- API, session, and Streamlit tests follow grounding metadata end to end.
- Evaluation replay checks all required-search cases meet the citation rule.
- Dependency, lint, format, type, test, branch-coverage, compilation, and replay gates run before publication.

Exact final results and commit links will be recorded after publication.

## What this checkpoint does not prove

- A valid citation can still sit beside an unsupported claim.
- Retrieved pages can be wrong, stale, malicious, or conflicting.
- The marker grammar does not model ranges or academic citation styles.
- Source identity lasts for one response, not across conversations.
- Offline fake-provider tests do not prove live-provider answer quality.

Semantic claim verification needs its own dataset, precision/recall targets, failure policy, and product decision.

## Explain-back questions and expected senior-level answers

### Why is prompt instruction insufficient?

Prompts influence behavior but do not enforce invariants. Models can omit, mistype, or invent references, and behavior varies across providers. A senior engineer enforces correctness at a deterministic application boundary and treats prompting as one layer, not the control itself.

### Why normalize before calling the model again?

Generator and validator need one canonical evidence representation. If the model sees raw provider data while validation checks a different projection, their vocabulary can diverge and private metadata can leak. Early normalization shrinks the trusted surface.

### Why not stream a grounded draft immediately?

Streaming is irreversible from the user's perspective. If validation rejects the answer, shown text may already be trusted, copied, or stored. Buffering is a deliberate latency-for-integrity tradeoff; safe status updates still communicate progress.

### Citation integrity versus semantic grounding?

Citation integrity asks whether references map to evidence retrieved for this request. Semantic grounding asks whether each claim is actually supported. The first is deterministic set validation; the second requires claim extraction, evidence comparison, calibrated evaluation, and explicit false-acceptance and false-rejection tolerances.

### Why preserve evaluation v1?

A baseline is a historical measurement contract. Overwriting it prevents reproduction and hides why metrics changed. Versioning preserves auditability while letting the active gate evolve.

### What telemetry should precede repair tuning?

Measure search-use, validation-failure, repair-attempt, repair-success, added latency and token cost, and terminal grounding failures by model/provider. Keep labels bounded and avoid prompts or URLs to control privacy and cardinality. Without measurement, retry changes are guesswork.

## Transferable senior-engineering lessons

1. Put probabilistic generation behind deterministic domain invariants.
2. Normalize untrusted external data once, early, into an application-owned type.
3. A retry policy is also a latency and cost policy; bound and observe it.
4. Do not claim semantic correctness from syntactic validation.
5. Streaming changes safety design because emitted output cannot be withdrawn.
6. Version evaluation rubrics as carefully as API contracts.
7. Expose honest failure metadata instead of silently degrading guarantees.

## Deferred work

- Semantic claim-to-source entailment evaluation.
- Production tracing and grounding metrics.
- Durable conversations and persistent sources.
- Authentication, rate limiting, deployment, and SLOs.
- Load, timeout, cancellation, and resilience tests against real infrastructure.
