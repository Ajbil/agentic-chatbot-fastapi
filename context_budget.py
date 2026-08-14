from dataclasses import dataclass
from math import ceil
from typing import Literal

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.messages.utils import count_tokens_approximately

from api_contract import ChatMessage, ContextUsage
from model_registry import ModelSpec

ESTIMATION_METHOD: Literal["langchain_approximate_v1"] = "langchain_approximate_v1"
SAFETY_MARGIN_RATIO = 0.10
MINIMUM_SAFETY_MARGIN_TOKENS = 256


class ContextWindowExceededError(ValueError):
    """Raised when the system prompt and newest user message cannot fit."""


@dataclass(frozen=True)
class ContextPlan:
    """The recent messages selected for one model invocation and its evidence."""

    messages: tuple[ChatMessage, ...]
    usage: ContextUsage


def plan_context(
    model: ModelSpec,
    system_prompt: str,
    messages: list[ChatMessage],
) -> ContextPlan:
    """Retain the newest complete turns that fit a conservative input budget."""

    safety_margin_tokens = max(
        MINIMUM_SAFETY_MARGIN_TOKENS,
        ceil(model.context_window_tokens * SAFETY_MARGIN_RATIO),
    )
    input_budget_tokens = (
        model.context_window_tokens - model.max_output_tokens - safety_margin_tokens
    )
    if input_budget_tokens <= 0:
        raise RuntimeError(
            f"Model '{model.key}' does not have a positive application input budget."
        )

    full_estimate = estimate_input_tokens(system_prompt, messages)
    if full_estimate <= input_budget_tokens:
        selected_messages = tuple(messages)
        sent_estimate = full_estimate
    else:
        selected_messages = _select_recent_complete_turns(
            system_prompt,
            messages,
            input_budget_tokens,
        )
        sent_estimate = estimate_input_tokens(system_prompt, selected_messages)

    omitted_message_count = len(messages) - len(selected_messages)
    usage = ContextUsage(
        estimation_method=ESTIMATION_METHOD,
        context_window_tokens=model.context_window_tokens,
        reserved_output_tokens=model.max_output_tokens,
        safety_margin_tokens=safety_margin_tokens,
        input_budget_tokens=input_budget_tokens,
        estimated_full_input_tokens=full_estimate,
        estimated_sent_input_tokens=sent_estimate,
        original_message_count=len(messages),
        included_message_count=len(selected_messages),
        omitted_message_count=omitted_message_count,
        was_truncated=omitted_message_count > 0,
    )
    return ContextPlan(messages=selected_messages, usage=usage)


def estimate_input_tokens(
    system_prompt: str,
    messages: list[ChatMessage] | tuple[ChatMessage, ...],
) -> int:
    """Estimate serialized system and chat-message tokens without network calls."""

    langchain_messages: list[BaseMessage] = [SystemMessage(content=system_prompt)]
    for message in messages:
        if message.role == "user":
            langchain_messages.append(HumanMessage(content=message.content))
        else:
            langchain_messages.append(AIMessage(content=message.content))
    return count_tokens_approximately(langchain_messages)


def _select_recent_complete_turns(
    system_prompt: str,
    messages: list[ChatMessage],
    input_budget_tokens: int,
) -> tuple[ChatMessage, ...]:
    newest_user_message = messages[-1]
    selected_messages: tuple[ChatMessage, ...] = (newest_user_message,)

    if estimate_input_tokens(system_prompt, selected_messages) > input_budget_tokens:
        raise ContextWindowExceededError(
            "The system prompt and newest user message exceed the selected "
            "model's input budget. Shorten them or start a new chat."
        )

    completed_history = messages[:-1]
    completed_turns = [
        (completed_history[index], completed_history[index + 1])
        for index in range(0, len(completed_history), 2)
    ]
    for completed_turn in reversed(completed_turns):
        candidate = (*completed_turn, *selected_messages)
        if estimate_input_tokens(system_prompt, candidate) > input_budget_tokens:
            break
        selected_messages = candidate

    return selected_messages
