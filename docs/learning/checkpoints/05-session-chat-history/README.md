# Checkpoint 05 - Session-Owned Chat History

| Field | Value |
|---|---|
| Status | Complete |
| Date | 2026-08-08 |
| Branch | `codex/session-chat-history` |
| Pull request | [#5 - Add session-owned chat history](https://github.com/Ajbil/agentic-chatbot-fastapi/pull/5) |
| Implementation commit | [`8cd17f0`](https://github.com/Ajbil/agentic-chatbot-fastapi/commit/8cd17f0) |
| Merge commit | [`5567d2f`](https://github.com/Ajbil/agentic-chatbot-fastapi/commit/5567d2f) |

## Objective

Turn the single-question Streamlit form into a real multi-turn chat interface. Keep temporary history in the browser's Streamlit session, resend the complete committed history through the canonical API, lock settings per conversation, and make failed turns safely retryable.

## Why this checkpoint came next

Checkpoint 04 made history representable: `POST /chat` accepts ordered user and assistant messages and returns one typed assistant reply. The frontend still discarded that capability by sending only the newest question.

Context management, persistence, streaming, and source evidence all depend on first deciding who owns conversation state and what constitutes a committed turn. Establishing those semantics now prevents later features from building on ambiguous history.

## Starting condition

- Every button click created a fresh model conversation.
- Streamlit rendered one text area and one response rather than chronological chat messages.
- No component owned prior user or assistant messages.
- Model, system prompt, and search permission could change independently for every request.
- A failed request removed the submitted prompt from the UI.
- The API accepted at most 50 messages, but the frontend had no boundary behavior.
- A successful reply had no maximum length even though it needed to become a bounded message on the next turn.
- A later catalog failure prevented the locally available history from being shown.

## Plan

1. Add a pure conversation state machine independent of Streamlit widgets and HTTP transport.
2. Store committed history, locked settings, and an optional failed turn in `st.session_state`.
3. Replace the form with `st.chat_message` and `st.chat_input`.
4. Commit user and assistant messages atomically after a successful response.
5. Keep failed user turns outside model history and provide exact retry behavior.
6. Block new turns at the 50-message limit without removing context.
7. Keep history visible and sending disabled when catalog discovery fails.
8. Add pure state tests, Streamlit `AppTest` coverage, documentation, and CI compilation.

## Decisions and alternatives

### Keep memory in the Streamlit session

- **Decision:** Each Streamlit browser session owns its conversation state and resends complete history.
- **Reason:** The API is already stateless and accepts canonical messages. Session ownership is transparent, requires no identity system, and makes data flow visible for learning.
- **Alternatives:** LangGraph checkpointer, backend session store, browser persistence, or database-owned conversations.
- **Tradeoff:** History is ephemeral, not shared across tabs or devices, and may disappear when the browser session or Streamlit process ends.
- **Revisit when:** Users need durable history, cross-device access, server-side workflows, or authenticated multi-user isolation.

### Model conversation changes as explicit state transitions

- **Decision:** Put begin, commit, fail, retry, reset, and capacity rules in a pure frontend session module.
- **Reason:** Streamlit reruns the script after interactions. Scattered mutations make it difficult to prove whether a message is committed once, duplicated, or lost.
- **Alternative:** Manipulate several `st.session_state` lists and flags directly inside widget branches.
- **Tradeoff:** The project gains a small state abstraction before it has database persistence.
- **Revisit when:** Server-owned conversation commands replace UI-owned transitions.

### Commit an exchange atomically

- **Decision:** Add the user and assistant messages to committed history only after a valid success response.
- **Reason:** Model history must never imply that an unanswered turn was completed. Each committed exchange remains structurally valid for the next request.
- **Alternatives:** Append the user immediately or delete all evidence of a failed submission.
- **Tradeoff:** Failed user text needs a separate pending representation.
- **Revisit when:** Streaming introduces partial assistant messages with an explicit incomplete status.

### Preserve a failed turn as retryable state

- **Decision:** Display the exact user text and safe error data, exclude it from model context, and prevent branching until Retry or New chat.
- **Reason:** Users do not need to retype work, while the next model request cannot accidentally treat a failed turn as successful history.
- **Alternative:** Remove the turn, commit it without an answer, or allow additional messages after it.
- **Tradeoff:** Only one pending failed turn is supported.
- **Revisit when:** The product supports editable retry, branching, queued messages, or conversation forks.

### Lock settings on the first attempt

- **Decision:** Model key, system prompt, and search permission remain fixed until New chat, including when the first request fails.
- **Reason:** These values define conversation semantics. Silent mid-history changes make behavior and debugging difficult to explain.
- **Alternatives:** Allow changes mid-chat or automatically clear history when a control changes.
- **Tradeoff:** Trying another model requires an explicit new conversation.
- **Revisit when:** Model comparison or intentional handoff becomes a named product feature with visible provenance.

### Fail explicitly at the history limit

- **Decision:** Reserve two message slots for every exchange, allow the final exchange at 48 committed messages, and stop at 50.
- **Reason:** Silent deletion would introduce a context-retention policy before token-aware context work has been designed.
- **Alternatives:** Drop oldest messages, summarize automatically, or clear the chat.
- **Tradeoff:** Long conversations must start over for now.
- **Revisit when:** The context-management checkpoint introduces token measurement, retention priorities, and summarization evidence.

### Guarantee response-to-history round trips

- **Decision:** Apply the same 20,000-character limit to `ChatResponse.reply` and reject oversized provider output as `502 invalid_upstream_response`.
- **Reason:** Every successful reply must be valid when represented as an assistant message in the next request.
- **Alternative:** Accept an oversized response and fail only when the user sends the next message.
- **Tradeoff:** Extremely long otherwise valid provider output becomes a handled upstream failure.
- **Revisit when:** Structured content, attachments, or server-side summarization changes the message representation.

### Keep local history visible during catalog failure

- **Decision:** Render committed and failed turns even when `GET /models` fails, while disabling sends and retries.
- **Reason:** Backend availability should control new work, not erase already-held UI state or imply data loss.
- **Alternative:** Stop the entire page before rendering history.
- **Tradeoff:** The UI contains a degraded read-only state.
- **Revisit when:** A versioned catalog cache provides a safe bounded offline mode.

## Implementation outcome

- Added explicit conversation settings, attempt, failed-turn, and state models.
- Added deterministic transitions for starting, committing, failing, retrying, resetting, and enforcing capacity.
- Replaced the question text area and button with Streamlit chat components.
- Added chronological rendering of committed history and complete-history request construction.
- Locked sidebar settings after the first submission.
- Added New chat behavior that resets only application-owned session and widget keys.
- Added a retry UI that preserves safe error code/status information without committing failed text.
- Disabled new messages while a failure is pending, the catalog is unavailable, the locked model disappears, or the message limit is reached.
- Preserved local history when catalog discovery later fails.
- Made successful reply length compatible with the next request's message constraints.
- Added pure state-machine tests and Streamlit `AppTest` scenarios with fake HTTP responses.

## Validation evidence

- `python -m pipenv run python -m pytest -q`: 86 offline tests passed after implementation.
- State tests cover settings locking, atomic commits, complete-history requests, retries, repeated failures, reset, isolation, and the 48/50-message boundary.
- Contract and agent tests prove oversized replies cannot become successful unrepeatable history.
- Streamlit tests exercise successful multi-turn chat, locked controls, retry recovery, New chat, and degraded catalog behavior.
- [GitHub Actions run `31256374847`](https://github.com/Ajbil/agentic-chatbot-fastapi/actions/runs/31256374847) passed on the draft pull request in a clean Ubuntu/Python 3.12 environment.
- No test contacts Groq, OpenAI, or Tavily.

## Senior-engineering lessons

### State ownership is an architectural decision

The message list is simple; its ownership is not. UI-owned state is appropriate for an ephemeral learning application, while durable or server-controlled workflows require identifiers, storage, isolation, cleanup, and concurrency rules.

### A conversation is a state machine, not just an array

The system must distinguish editable settings, in-flight work, committed exchanges, failed attempts, retry, capacity exhaustion, and reset. Naming those transitions prevents impossible or misleading histories.

### Commit related state atomically

A user question and its assistant response form one completed exchange. Committing them together prevents downstream code from treating transport failure as conversation history.

### Retry semantics require stable inputs

A meaningful retry repeats the same operation. Locking settings and retaining the exact user message makes retry behavior explainable instead of quietly changing the model or tool permissions.

### Round-trip closure is a contract property

If an output is intended to become future input, every successful output must satisfy the future input constraints. Discovering incompatibility one request later moves the failure away from its cause.

### Degraded modes should preserve trustworthy local state

Losing backend connectivity should disable actions that require the backend, but it should not hide already committed information owned by the frontend.

### Message count is not context management

A 50-message cap bounds structure but says little about tokens, cost, or relevance. Silent truncation would hide information loss rather than solve context allocation.

## Applying this elsewhere

- Identify the authoritative owner for every piece of state.
- Write down valid transitions before wiring UI events.
- Separate committed data from pending or failed operations.
- Define retry as an exact or intentionally modified operation.
- Keep configuration stable for the lifetime of the state it governs.
- Reserve capacity for the complete atomic operation, not only its first step.
- Ensure values passed between stages satisfy both output and future-input contracts.
- Preserve local read-only state during dependency outages.
- Test independent sessions to detect shared mutable defaults.

## Common mistakes

- Calling a list in session state “memory” without defining its lifetime or owner.
- Appending a user message before knowing whether the operation completed.
- Resending a failed turn as if the model had acknowledged it.
- Allowing model or system-prompt changes without marking a conversation boundary.
- Retrying with current widget values instead of the original operation inputs.
- Silently dropping old messages at a structural limit.
- Clearing visible history when a backend dependency is temporarily unavailable.
- Accepting successful output that cannot be represented in the next request.
- Testing state only by clicking manually through Streamlit.

## Explain-back questions

1. Why is `st.session_state` an ownership decision rather than merely a UI convenience?
2. What is the lifetime and isolation boundary of this conversation history?
3. Why are user and assistant messages committed as one atomic exchange?
4. Why is a failed user turn displayed but excluded from model history?
5. What must remain stable for a retry to represent the same operation?
6. Why are model, system prompt, and search permission locked per conversation?
7. Why does the application reserve two slots before accepting a new turn?
8. Why is silently dropping the oldest message not context-window management?
9. What does it mean for the success response to be round-trip compatible?
10. What new requirements would justify moving state to a LangGraph checkpointer or database?

## Deferred work

- Token-aware context measurement, trimming, summarization, and important-fact retention belong to the next context-management checkpoint.
- Durable history requires authentication, conversation identifiers, persistence, privacy policy, and cleanup rules.
- LangGraph checkpointers should be evaluated when backend-owned workflow state is required.
- Streaming needs partial-message states, cancellation, and an event contract.
- Provider timeout, rate-limit, and retry normalization remains a resilience checkpoint.
- Tool activity and structured sources remain necessary before the UI can prove that search occurred or an answer is grounded.
- Editing, branching, renaming, exporting, and comparing conversations remain product features rather than implicit session behavior.
