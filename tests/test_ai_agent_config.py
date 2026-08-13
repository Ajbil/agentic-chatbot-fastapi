import os
import json
import subprocess
import sys

import pytest
from langchain_core.messages import AIMessage, ToolMessage

import ai_agent
from ai_agent import (
    InvalidAgentResponseError,
    MissingConfigurationError,
    get_response_from_ai_agent,
)
from api_contract import MAX_MESSAGE_CHARACTERS, ChatMessage
from config import Settings
from model_registry import ModelSpec, Provider


def make_settings(**overrides):
    values = {
        "groq_api_key": None,
        "openai_api_key": None,
        "tavily_api_key": None,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def make_model(provider=Provider.GROQ):
    return ModelSpec(
        key="test-model",
        provider=provider,
        model_id="test-model",
        display_name="Test model",
        context_window_tokens=1_000,
        max_output_tokens=128,
        supports_tool_calling=True,
    )


def call_agent(settings, provider=Provider.GROQ, allow_search=False):
    return get_response_from_ai_agent(
        model=make_model(provider),
        messages=[ChatMessage(role="user", content="Hello")],
        allow_search=allow_search,
        system_prompt="Be helpful",
        settings=settings,
    )


def test_agent_module_imports_without_credentials():
    environment = os.environ.copy()
    for variable_name in ("GROQ_API_KEY", "OPENAI_API_KEY", "TAVILY_API_KEY"):
        environment.pop(variable_name, None)

    result = subprocess.run(
        [sys.executable, "-c", "import ai_agent"],
        capture_output=True,
        check=False,
        env=environment,
        text=True,
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("provider", "missing_variable"),
    [(Provider.GROQ, "GROQ_API_KEY"), (Provider.OPENAI, "OPENAI_API_KEY")],
)
def test_selected_provider_requires_only_its_credential(provider, missing_variable):
    with pytest.raises(MissingConfigurationError, match=missing_variable):
        call_agent(make_settings(), provider=provider)


def test_search_requires_tavily_credential():
    settings = make_settings(groq_api_key="groq-test-key")

    with pytest.raises(MissingConfigurationError, match="TAVILY_API_KEY"):
        call_agent(settings, allow_search=True)


def test_groq_request_does_not_require_other_credentials(monkeypatch):
    captured = {}

    def fake_groq(**kwargs):
        captured.update(kwargs)
        return object()

    class FakeAgent:
        def invoke(self, state):
            captured["messages"] = state["messages"]
            return {"messages": [AIMessage(content="fake reply")]}

    monkeypatch.setattr(ai_agent, "ChatGroq", fake_groq)
    monkeypatch.setattr(ai_agent, "create_agent", lambda **kwargs: FakeAgent())

    response = call_agent(make_settings(groq_api_key="groq-test-key"))

    assert response.reply == "fake reply"
    assert response.search.allowed is False
    assert captured["model"] == "test-model"
    assert captured["groq_api_key"] == "groq-test-key"
    assert captured["max_tokens"] == 128


def test_openai_request_does_not_require_other_credentials(monkeypatch):
    captured = {}

    def fake_openai(**kwargs):
        captured.update(kwargs)
        return object()

    class FakeAgent:
        def invoke(self, state):
            return {"messages": [AIMessage(content="openai reply")]}

    monkeypatch.setattr(ai_agent, "ChatOpenAI", fake_openai)
    monkeypatch.setattr(ai_agent, "create_agent", lambda **kwargs: FakeAgent())

    response = call_agent(
        make_settings(openai_api_key="openai-test-key"),
        provider=Provider.OPENAI,
    )

    assert response.reply == "openai reply"
    assert captured["model"] == "test-model"
    assert captured["api_key"] == "openai-test-key"
    assert captured["max_completion_tokens"] == 128


def test_search_builds_tavily_tool_with_its_own_credential(monkeypatch):
    captured = {}
    agent_configuration = {}

    monkeypatch.setattr(ai_agent, "ChatGroq", lambda **kwargs: object())

    def fake_tavily(**kwargs):
        captured.update(kwargs)
        return object()

    class FakeAgent:
        def invoke(self, state):
            return {"messages": [AIMessage(content="searched reply")]}

    monkeypatch.setattr(ai_agent, "TavilySearch", fake_tavily)

    def fake_create_agent(**kwargs):
        agent_configuration.update(kwargs)
        return FakeAgent()

    monkeypatch.setattr(ai_agent, "create_agent", fake_create_agent)

    response = call_agent(
        make_settings(groq_api_key="groq-test-key", tavily_api_key="tavily-test-key"),
        allow_search=True,
    )

    assert response.reply == "searched reply"
    assert response.search.allowed is True
    assert response.search.attempted is False
    assert captured["max_results"] == 2
    assert captured["search_depth"] == "basic"
    assert captured["topic"] == "general"
    assert captured["auto_parameters"] is False
    assert captured["include_answer"] is False
    assert captured["include_raw_content"] is False
    assert captured["include_images"] is False
    assert (
        captured["api_wrapper"].tavily_api_key.get_secret_value()
        == "tavily-test-key"
    )
    limiter = agent_configuration["middleware"][0]
    assert limiter.tool_name == "tavily_search"
    assert limiter.run_limit == 3
    assert limiter.exit_behavior == "error"


def test_real_tavily_tool_constructs_with_explicit_credential():
    tool = ai_agent.TavilySearch(
        max_results=2,
        args_schema=ai_agent.SearchInput,
        api_wrapper=ai_agent.TavilySearchAPIWrapper(
            tavily_api_key="test-tavily-key",
        ),
    )

    assert tool.max_results == 2
    assert (
        tool.api_wrapper.tavily_api_key.get_secret_value() == "test-tavily-key"
    )


def test_agent_converts_canonical_history(monkeypatch):
    captured = {}

    monkeypatch.setattr(ai_agent, "ChatGroq", lambda **kwargs: object())

    class FakeAgent:
        def invoke(self, state):
            captured["messages"] = state["messages"]
            return {"messages": [AIMessage(content="follow-up reply")]}

    monkeypatch.setattr(ai_agent, "create_agent", lambda **kwargs: FakeAgent())

    response = get_response_from_ai_agent(
        model=make_model(),
        messages=[
            ChatMessage(role="user", content="Question"),
            ChatMessage(role="assistant", content="Answer"),
            ChatMessage(role="user", content="Follow-up"),
        ],
        allow_search=False,
        system_prompt="Be helpful",
        settings=make_settings(groq_api_key="groq-test-key"),
    )

    assert response.reply == "follow-up reply"
    assert [message.type for message in captured["messages"]] == [
        "human",
        "ai",
        "human",
    ]


@pytest.mark.parametrize(
    "content",
    [
        "",
        "   ",
        [{"type": "text", "text": "Hi"}],
        "x" * (MAX_MESSAGE_CHARACTERS + 1),
    ],
)
def test_agent_rejects_unusable_ai_response(monkeypatch, content):
    monkeypatch.setattr(ai_agent, "ChatGroq", lambda **kwargs: object())

    class FakeAgent:
        def invoke(self, state):
            return {"messages": [AIMessage(content=content)]}

    monkeypatch.setattr(ai_agent, "create_agent", lambda **kwargs: FakeAgent())

    with pytest.raises(InvalidAgentResponseError):
        call_agent(make_settings(groq_api_key="groq-test-key"))


def test_agent_extracts_and_normalizes_search_provenance(monkeypatch):
    monkeypatch.setattr(ai_agent, "ChatGroq", lambda **kwargs: object())
    monkeypatch.setattr(ai_agent, "TavilySearch", lambda **kwargs: object())

    class FakeAgent:
        def invoke(self, state):
            return {
                "messages": [
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "tavily_search",
                                "args": {"query": "latest Python release"},
                                "id": "search-1",
                                "type": "tool_call",
                            }
                        ],
                    ),
                    ToolMessage(
                        name="tavily_search",
                        tool_call_id="search-1",
                        content=json.dumps(
                            {
                                "results": [
                                    {
                                        "title": " Python releases ",
                                        "url": "https://python.org/downloads/",
                                        "content": "Official downloads",
                                        "score": 0.99,
                                        "raw_content": "must not cross boundary",
                                    },
                                    {
                                        "title": "Duplicate",
                                        "url": "https://python.org/downloads/",
                                        "content": "duplicate",
                                    },
                                    {
                                        "title": "Release article",
                                        "url": "https://example.com/python",
                                        "content": "An article",
                                    },
                                ]
                            }
                        ),
                    ),
                    AIMessage(content="Python was released."),
                ]
            }

    monkeypatch.setattr(ai_agent, "create_agent", lambda **kwargs: FakeAgent())

    outcome = call_agent(
        make_settings(groq_api_key="groq", tavily_api_key="tavily"),
        allow_search=True,
    )

    execution = outcome.search.executions[0]
    assert outcome.reply == "Python was released."
    assert execution.query == "latest Python release"
    assert execution.status == "succeeded"
    assert [source.title for source in execution.sources] == [
        "Python releases",
        "Release article",
    ]
    assert execution.sources[0].snippet == "Official downloads"


def test_search_executions_preserve_tool_result_order():
    messages = [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "tavily_search",
                    "args": {"query": "first query"},
                    "id": "search-1",
                    "type": "tool_call",
                },
                {
                    "name": "tavily_search",
                    "args": {"query": "second query"},
                    "id": "search-2",
                    "type": "tool_call",
                },
            ],
        ),
        ToolMessage(
            name="tavily_search",
            tool_call_id="search-2",
            content=json.dumps(
                {
                    "results": [
                        {
                            "title": "Second",
                            "url": "https://example.com/second",
                            "content": "Second result",
                        }
                    ]
                }
            ),
        ),
        ToolMessage(
            name="tavily_search",
            tool_call_id="search-1",
            content=json.dumps(
                {
                    "results": [
                        {
                            "title": "First",
                            "url": "https://example.com/first",
                            "content": "First result",
                        }
                    ]
                }
            ),
        ),
    ]

    evidence = ai_agent._extract_search_evidence(messages, allowed=True)

    assert [execution.query for execution in evidence.executions] == [
        "second query",
        "first query",
    ]


@pytest.mark.parametrize(
    ("status", "content"),
    [
        ("error", "provider unavailable"),
        ("success", "not-json"),
        ("success", json.dumps({"results": []})),
        ("success", json.dumps({"error": "provider unavailable"})),
    ],
)
def test_agent_records_failed_search_without_leaking_provider_error(
    monkeypatch,
    status,
    content,
):
    monkeypatch.setattr(ai_agent, "ChatGroq", lambda **kwargs: object())
    monkeypatch.setattr(ai_agent, "TavilySearch", lambda **kwargs: object())

    class FakeAgent:
        def invoke(self, state):
            return {
                "messages": [
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "tavily_search",
                                "args": {"query": "current news"},
                                "id": "search-1",
                                "type": "tool_call",
                            }
                        ],
                    ),
                    ToolMessage(
                        name="tavily_search",
                        tool_call_id="search-1",
                        status=status,
                        content=content,
                    ),
                    AIMessage(content="I could not verify the news."),
                ]
            }

    monkeypatch.setattr(ai_agent, "create_agent", lambda **kwargs: FakeAgent())
    outcome = call_agent(
        make_settings(groq_api_key="groq", tavily_api_key="tavily"),
        allow_search=True,
    )

    execution = outcome.search.executions[0]
    assert execution.status == "failed"
    assert execution.sources == ()
    assert "provider unavailable" not in execution.model_dump_json()


def test_agent_rejects_unmatched_search_result(monkeypatch):
    monkeypatch.setattr(ai_agent, "ChatGroq", lambda **kwargs: object())
    monkeypatch.setattr(ai_agent, "TavilySearch", lambda **kwargs: object())

    class FakeAgent:
        def invoke(self, state):
            return {
                "messages": [
                    ToolMessage(
                        name="tavily_search",
                        tool_call_id="missing-call",
                        content=json.dumps({"results": []}),
                    ),
                    AIMessage(content="Answer"),
                ]
            }

    monkeypatch.setattr(ai_agent, "create_agent", lambda **kwargs: FakeAgent())

    with pytest.raises(InvalidAgentResponseError, match="unmatched"):
        call_agent(
            make_settings(groq_api_key="groq", tavily_api_key="tavily"),
            allow_search=True,
        )


def test_agent_normalizes_tool_call_limit(monkeypatch):
    monkeypatch.setattr(ai_agent, "ChatGroq", lambda **kwargs: object())
    monkeypatch.setattr(ai_agent, "TavilySearch", lambda **kwargs: object())

    class FakeAgent:
        def invoke(self, state):
            raise ai_agent.ToolCallLimitExceededError(
                thread_count=0,
                run_count=4,
                thread_limit=None,
                run_limit=3,
                tool_name="tavily_search",
            )

    monkeypatch.setattr(ai_agent, "create_agent", lambda **kwargs: FakeAgent())

    with pytest.raises(ai_agent.AgentToolLimitExceededError, match="three"):
        call_agent(
            make_settings(groq_api_key="groq", tavily_api_key="tavily"),
            allow_search=True,
        )
