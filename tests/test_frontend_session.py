import pytest
from pydantic import ValidationError

from api_contract import MAX_MESSAGE_CHARACTERS, ChatMessage
from frontend_session import (
    ConversationSettings,
    ConversationState,
    ConversationStateError,
)


def settings(**overrides):
    values = {
        "model_key": "groq-gpt-oss-20b",
        "system_prompt": "Be helpful",
        "allow_search": False,
    }
    values.update(overrides)
    return ConversationSettings(**values)


def committed_exchange(number):
    return [
        ChatMessage(role="user", content=f"Question {number}"),
        ChatMessage(role="assistant", content=f"Answer {number}"),
    ]


def test_first_turn_locks_settings_and_builds_canonical_request():
    state = ConversationState()
    conversation_settings = settings(allow_search=True)

    attempt = state.begin_turn("Hello", conversation_settings)

    assert state.settings == conversation_settings
    assert state.settings_locked is True
    assert state.messages == []
    assert attempt.request.model_key == "groq-gpt-oss-20b"
    assert attempt.request.allow_search is True
    assert [message.content for message in attempt.request.messages] == ["Hello"]


def test_successful_turn_is_committed_as_an_atomic_pair():
    state = ConversationState()
    attempt = state.begin_turn("Question", settings())

    state.commit_turn(attempt, "Answer")

    assert [(message.role, message.content) for message in state.messages] == [
        ("user", "Question"),
        ("assistant", "Answer"),
    ]
    assert state.failed_turn is None


def test_follow_up_request_contains_complete_committed_history():
    state = ConversationState()
    first_attempt = state.begin_turn("First question", settings())
    state.commit_turn(first_attempt, "First answer")

    second_attempt = state.begin_turn("Follow-up", settings())

    assert [(message.role, message.content) for message in second_attempt.request.messages] == [
        ("user", "First question"),
        ("assistant", "First answer"),
        ("user", "Follow-up"),
    ]


def test_settings_cannot_change_after_first_attempt():
    state = ConversationState()
    state.begin_turn("Hello", settings())

    with pytest.raises(ConversationStateError, match="cannot change"):
        state.begin_turn("Another message", settings(model_key="openai-gpt-4o-mini"))


def test_invalid_first_request_does_not_lock_settings():
    state = ConversationState()

    with pytest.raises(ValidationError):
        state.begin_turn("Hello", settings(system_prompt="   "))

    assert state.settings is None


def test_failed_turn_is_retryable_but_not_committed():
    state = ConversationState()
    attempt = state.begin_turn("Please retry me", settings())

    state.record_failure(
        attempt,
        code="chat_request_failed",
        message="Backend timed out",
    )
    retry = state.retry_turn()

    assert state.messages == []
    assert state.can_start_turn is False
    assert retry.user_message == attempt.user_message
    assert retry.request == attempt.request
    assert state.failed_turn.code == "chat_request_failed"


def test_repeated_failure_replaces_error_without_duplicating_message():
    state = ConversationState()
    attempt = state.begin_turn("Please retry me", settings())
    state.record_failure(attempt, code="timeout", message="First failure")

    retry = state.retry_turn()
    state.record_failure(
        retry,
        code="service_unavailable",
        message="Second failure",
        status_code=503,
    )

    assert state.messages == []
    assert state.failed_turn.user_message.content == "Please retry me"
    assert state.failed_turn.code == "service_unavailable"
    assert state.failed_turn.status_code == 503


def test_successful_retry_commits_exactly_one_exchange():
    state = ConversationState()
    attempt = state.begin_turn("Please retry me", settings())
    state.record_failure(attempt, code="timeout", message="Try again")

    retry = state.retry_turn()
    state.commit_turn(retry, "Recovered answer")

    assert [message.content for message in state.messages] == [
        "Please retry me",
        "Recovered answer",
    ]
    assert state.failed_turn is None


def test_new_message_is_blocked_while_failure_is_pending():
    state = ConversationState()
    attempt = state.begin_turn("Failed question", settings())
    state.record_failure(attempt, code="timeout", message="Try again")

    with pytest.raises(ConversationStateError, match="Retry or start"):
        state.begin_turn("Branching question", settings())


def test_last_exchange_is_allowed_at_48_messages_then_limit_is_reached():
    history = []
    for number in range(24):
        history.extend(committed_exchange(number))
    state = ConversationState(messages=history, settings=settings())

    assert len(state.messages) == 48
    assert state.can_start_turn is True

    final_attempt = state.begin_turn("Final question", settings())
    state.commit_turn(final_attempt, "Final answer")

    assert len(state.messages) == 50
    assert state.message_limit_reached is True
    assert state.can_start_turn is False
    with pytest.raises(ConversationStateError, match="50-message limit"):
        state.begin_turn("One too many", settings())


def test_oversized_assistant_reply_cannot_corrupt_history():
    state = ConversationState()
    attempt = state.begin_turn("Question", settings())

    with pytest.raises(ValidationError):
        state.commit_turn(attempt, "x" * (MAX_MESSAGE_CHARACTERS + 1))

    assert state.messages == []


def test_reset_clears_only_conversation_state():
    state = ConversationState()
    attempt = state.begin_turn("Question", settings())
    state.record_failure(attempt, code="timeout", message="Try again")

    state.reset()

    assert state.messages == []
    assert state.settings is None
    assert state.failed_turn is None


def test_two_sessions_do_not_share_message_lists():
    first = ConversationState()
    second = ConversationState()
    attempt = first.begin_turn("Private question", settings())
    first.commit_turn(attempt, "Private answer")

    assert second.messages == []
    assert second.settings is None
