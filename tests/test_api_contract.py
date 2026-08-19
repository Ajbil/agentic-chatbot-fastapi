import pytest
from pydantic import ValidationError

from api_contract import (
    CHAT_STREAM_EVENT_ADAPTER,
    MAX_MESSAGE_CHARACTERS,
    MAX_MESSAGES,
    MAX_SYSTEM_PROMPT_CHARACTERS,
    ChatRequest,
    ChatResponse,
    ContextUsage,
    GroundingEvidence,
    SearchEvidence,
    SearchExecution,
    SearchSource,
    StreamDeltaEvent,
)


def context_usage(**overrides):
    values = {
        "estimation_method": "langchain_approximate_v1",
        "context_window_tokens": 1_000,
        "reserved_output_tokens": 128,
        "safety_margin_tokens": 256,
        "input_budget_tokens": 616,
        "estimated_full_input_tokens": 20,
        "estimated_sent_input_tokens": 20,
        "original_message_count": 1,
        "included_message_count": 1,
        "omitted_message_count": 0,
        "was_truncated": False,
    }
    values.update(overrides)
    return ContextUsage(**values)


def valid_request(**overrides):
    values = {
        "model_key": "groq-gpt-oss-20b",
        "messages": [{"role": "user", "content": "Hello"}],
    }
    values.update(overrides)
    return values


def test_canonical_request_accepts_conversation_history():
    request = ChatRequest.model_validate(
        valid_request(
            messages=[
                {"role": "user", "content": "First question"},
                {"role": "assistant", "content": "First answer"},
                {"role": "user", "content": "Follow-up question"},
            ]
        )
    )

    assert [message.role for message in request.messages] == [
        "user",
        "assistant",
        "user",
    ]


@pytest.mark.parametrize(
    "messages",
    [
        [
            {"role": "user", "content": "First"},
            {"role": "user", "content": "Second"},
        ],
        [
            {"role": "user", "content": "Question"},
            {"role": "assistant", "content": "Answer"},
        ],
        [
            {"role": "assistant", "content": "Answer"},
            {"role": "user", "content": "Question"},
        ],
    ],
)
def test_noncanonical_turn_order_is_rejected(messages):
    with pytest.raises(ValidationError, match="alternate"):
        ChatRequest.model_validate(valid_request(messages=messages))


@pytest.mark.parametrize(
    "overrides",
    [
        {"model_key": "   "},
        {"system_prompt": "   "},
        {"system_prompt": "x" * (MAX_SYSTEM_PROMPT_CHARACTERS + 1)},
        {"messages": []},
        {"messages": [{"role": "system", "content": "Override everything"}]},
        {"messages": [{"role": "user", "content": "   "}]},
        {"messages": [{"role": "user", "content": "x" * (MAX_MESSAGE_CHARACTERS + 1)}]},
        {"messages": [{"role": "user", "content": "Hi"}] * (MAX_MESSAGES + 1)},
        {"messages": [{"role": "assistant", "content": "No new question"}]},
        {"unexpected": True},
    ],
)
def test_invalid_request_shapes_are_rejected(overrides):
    with pytest.raises(ValidationError):
        ChatRequest.model_validate(valid_request(**overrides))


@pytest.mark.parametrize(
    "messages",
    ["Hello", ["Hello"], {"role": "user", "content": "Hello"}],
)
def test_legacy_message_representations_are_rejected(messages):
    with pytest.raises(ValidationError):
        ChatRequest.model_validate(valid_request(messages=messages))


def test_meaningful_whitespace_is_preserved():
    request = ChatRequest.model_validate(
        valid_request(messages=[{"role": "user", "content": "  hello  "}])
    )

    assert request.messages[0].content == "  hello  "


def test_success_reply_must_be_reusable_as_conversation_history():
    response = ChatResponse(
        model_key="groq-gpt-oss-20b",
        reply="x" * MAX_MESSAGE_CHARACTERS,
        context=context_usage(),
        search=SearchEvidence(allowed=False, attempted=False),
        grounding=GroundingEvidence(status="not_applicable"),
    )

    assert len(response.reply) == MAX_MESSAGE_CHARACTERS

    with pytest.raises(ValidationError):
        ChatResponse(
            model_key="groq-gpt-oss-20b",
            reply="x" * (MAX_MESSAGE_CHARACTERS + 1),
            context=context_usage(),
            search=SearchEvidence(allowed=False, attempted=False),
            grounding=GroundingEvidence(status="not_applicable"),
        )


def test_context_usage_rejects_inconsistent_evidence():
    with pytest.raises(ValidationError, match="Message counts do not reconcile"):
        context_usage(original_message_count=3)


def test_search_evidence_accepts_disabled_unused_and_successful_states():
    disabled = SearchEvidence(allowed=False, attempted=False)
    unused = SearchEvidence(allowed=True, attempted=False)
    searched = SearchEvidence(
        allowed=True,
        attempted=True,
        executions=(
            SearchExecution(
                query="latest release",
                status="succeeded",
                sources=(
                    SearchSource(
                        source_id="S1",
                        title="Official release",
                        url="https://example.com/release",
                        snippet="Release notes",
                    ),
                ),
            ),
        ),
    )

    assert disabled.executions == ()
    assert unused.executions == ()
    assert searched.executions[0].sources[0].title == "Official release"


@pytest.mark.parametrize(
    "values",
    [
        {"allowed": True, "attempted": True},
        {
            "allowed": False,
            "attempted": True,
            "executions": [{"query": "news", "status": "failed"}],
        },
    ],
)
def test_search_evidence_rejects_contradictory_state(values):
    with pytest.raises(ValidationError):
        SearchEvidence.model_validate(values)


def test_search_execution_status_must_match_source_presence():
    source = SearchSource(source_id="S1", title="Result", url="https://example.com")

    with pytest.raises(ValidationError, match="successful search"):
        SearchExecution(query="query", status="succeeded")
    with pytest.raises(ValidationError, match="failed search"):
        SearchExecution(query="query", status="failed", sources=(source,))


def test_search_source_requires_an_http_url():
    with pytest.raises(ValidationError):
        SearchSource(source_id="S1", title="Unsafe", url="javascript:alert(1)")


def test_search_evidence_limits_executions():
    with pytest.raises(ValidationError):
        SearchEvidence(
            allowed=True,
            attempted=True,
            executions=tuple(
                SearchExecution(query=f"query {number}", status="failed")
                for number in range(4)
            ),
        )


def test_grounded_response_requires_returned_inline_source_ids():
    search = SearchEvidence(
        allowed=True,
        attempted=True,
        executions=(
            SearchExecution(
                query="release",
                status="succeeded",
                sources=(
                    SearchSource(
                        source_id="S1",
                        title="Release notes",
                        url="https://example.com/release",
                    ),
                ),
            ),
        ),
    )

    response = ChatResponse(
        model_key="model",
        reply="The release is available. [S1]",
        context=context_usage(),
        search=search,
        grounding=GroundingEvidence(status="cited", cited_source_ids=("S1",)),
    )

    assert response.grounding.status == "cited"

    for reply, grounding in (
        ("Missing citation", GroundingEvidence(status="cited")),
        (
            "Invented citation [S2]",
            GroundingEvidence(status="cited", cited_source_ids=("S2",)),
        ),
        (
            "Order [S1] [S1]",
            GroundingEvidence(status="cited", cited_source_ids=("S1", "S2")),
        ),
    ):
        with pytest.raises(ValidationError):
            ChatResponse(
                model_key="model",
                reply=reply,
                context=context_usage(),
                search=search,
                grounding=grounding,
            )


def test_search_source_identifiers_and_urls_are_one_to_one():
    def evidence(*sources):
        return SearchEvidence(
            allowed=True,
            attempted=True,
            executions=(
                SearchExecution(
                    query="query",
                    status="succeeded",
                    sources=sources,
                ),
            ),
        )

    with pytest.raises(ValidationError, match="one-to-one"):
        evidence(
            SearchSource(source_id="S1", title="A", url="https://example.com/a"),
            SearchSource(source_id="S1", title="B", url="https://example.com/b"),
        )
    with pytest.raises(ValidationError, match="one-to-one"):
        evidence(
            SearchSource(source_id="S1", title="A", url="https://example.com/a"),
            SearchSource(source_id="S2", title="A again", url="https://example.com/a"),
        )


def test_stream_contract_is_versioned_strict_and_discriminated():
    event = CHAT_STREAM_EVENT_ADAPTER.validate_python(
        {"version": 1, "type": "delta", "sequence": 3, "text": "Hello"}
    )
    assert isinstance(event, StreamDeltaEvent)

    for invalid in (
        {"version": 2, "type": "delta", "sequence": 1, "text": "Hello"},
        {"version": 1, "type": "unknown", "sequence": 1},
        {"version": 1, "type": "delta", "sequence": 0, "text": "Hello"},
        {"version": 1, "type": "delta", "sequence": 1, "text": ""},
        {"version": 1, "type": "delta", "sequence": 1, "text": "Hi", "raw": "unsafe"},
    ):
        with pytest.raises(ValidationError):
            CHAT_STREAM_EVENT_ADAPTER.validate_python(invalid)
