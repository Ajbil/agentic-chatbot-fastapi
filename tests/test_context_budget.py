import pytest

from api_contract import ChatMessage
from context_budget import (
    ContextWindowExceededError,
    estimate_input_tokens,
    plan_context,
)
from model_registry import ModelSpec, Provider


def model(**overrides):
    values = {
        "key": "small-test-model",
        "provider": Provider.GROQ,
        "model_id": "small-test-model",
        "display_name": "Small test model",
        "context_window_tokens": 1_000,
        "max_output_tokens": 128,
        "supports_tool_calling": True,
    }
    values.update(overrides)
    return ModelSpec(**values)


def message(role, content):
    return ChatMessage(role=role, content=content)


def test_all_messages_are_retained_when_they_fit():
    messages = [
        message("user", "First question"),
        message("assistant", "First answer"),
        message("user", "Follow-up"),
    ]

    plan = plan_context(model(), "Be helpful", messages)

    assert plan.messages == tuple(messages)
    assert plan.usage.was_truncated is False
    assert plan.usage.omitted_message_count == 0
    assert plan.usage.estimated_sent_input_tokens == estimate_input_tokens(
        "Be helpful", messages
    )
    assert messages[-1].content == "Follow-up"


def test_newest_complete_turns_are_retained_without_partial_pairs():
    messages = [
        message("user", "a" * 500),
        message("assistant", "b" * 500),
        message("user", "c" * 500),
        message("assistant", "d" * 500),
        message("user", "e" * 500),
    ]

    plan = plan_context(model(), "Be helpful", messages)

    assert plan.messages == tuple(messages[-3:])
    assert [item.role for item in plan.messages] == ["user", "assistant", "user"]
    assert plan.usage.original_message_count == 5
    assert plan.usage.included_message_count == 3
    assert plan.usage.omitted_message_count == 2
    assert plan.usage.was_truncated is True
    assert plan.usage.estimated_sent_input_tokens <= plan.usage.input_budget_tokens


def test_selection_stops_at_first_recent_turn_that_does_not_fit():
    messages = [
        message("user", "old small question"),
        message("assistant", "old small answer"),
        message("user", "x" * 1_200),
        message("assistant", "y" * 1_200),
        message("user", "latest small question"),
    ]

    plan = plan_context(model(), "Be helpful", messages)

    assert plan.messages == (messages[-1],)
    assert plan.usage.omitted_message_count == 4


def test_system_prompt_and_newest_user_message_must_fit_together():
    messages = [message("user", "x" * 3_000)]

    with pytest.raises(ContextWindowExceededError, match="Shorten them"):
        plan_context(model(), "Be helpful", messages)


def test_budget_reserves_output_and_a_conservative_safety_margin():
    plan = plan_context(model(), "Be helpful", [message("user", "Hello")])

    assert plan.usage.reserved_output_tokens == 128
    assert plan.usage.safety_margin_tokens == 256
    assert plan.usage.input_budget_tokens == 616
    assert (
        plan.usage.input_budget_tokens
        + plan.usage.reserved_output_tokens
        + plan.usage.safety_margin_tokens
        == plan.usage.context_window_tokens
    )
