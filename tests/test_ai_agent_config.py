import os
import subprocess
import sys

import pytest
from langchain_core.messages import AIMessage

import ai_agent
from ai_agent import MissingConfigurationError, get_response_from_ai_agent
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
        supports_tool_calling=True,
    )


def call_agent(settings, provider=Provider.GROQ, allow_search=False):
    return get_response_from_ai_agent(
        model=make_model(provider),
        query="Hello",
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
        captured["model"] = kwargs["model"]
        captured["api_key"] = kwargs["groq_api_key"]
        return object()

    class FakeAgent:
        def invoke(self, state):
            captured["messages"] = state["messages"]
            return {"messages": [AIMessage(content="fake reply")]}

    monkeypatch.setattr(ai_agent, "ChatGroq", fake_groq)
    monkeypatch.setattr(ai_agent, "create_agent", lambda **kwargs: FakeAgent())

    response = call_agent(make_settings(groq_api_key="groq-test-key"))

    assert response == {"reply": "fake reply"}
    assert captured["model"] == "test-model"
    assert captured["api_key"] == "groq-test-key"


def test_openai_request_does_not_require_other_credentials(monkeypatch):
    captured = {}

    def fake_openai(**kwargs):
        captured["model"] = kwargs["model"]
        captured["api_key"] = kwargs["api_key"]
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

    assert response == {"reply": "openai reply"}
    assert captured["model"] == "test-model"
    assert captured["api_key"] == "openai-test-key"


def test_search_builds_tavily_tool_with_its_own_credential(monkeypatch):
    captured = {}

    monkeypatch.setattr(ai_agent, "ChatGroq", lambda **kwargs: object())

    def fake_tavily(**kwargs):
        captured.update(kwargs)
        return object()

    class FakeAgent:
        def invoke(self, state):
            return {"messages": [AIMessage(content="searched reply")]}

    monkeypatch.setattr(ai_agent, "TavilySearch", fake_tavily)
    monkeypatch.setattr(ai_agent, "create_agent", lambda **kwargs: FakeAgent())

    response = call_agent(
        make_settings(groq_api_key="groq-test-key", tavily_api_key="tavily-test-key"),
        allow_search=True,
    )

    assert response == {"reply": "searched reply"}
    assert captured == {"max_results": 2, "api_key": "tavily-test-key"}
