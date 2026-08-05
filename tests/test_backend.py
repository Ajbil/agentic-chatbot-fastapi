from fastapi.testclient import TestClient

import backend
from model_registry import DEFAULT_MODEL_KEY, ModelSpec, Provider


client = TestClient(backend.app)


def test_models_endpoint_returns_backend_owned_catalog():
    response = client.get("/models")

    assert response.status_code == 200
    payload = response.json()
    assert payload["default_model_key"] == DEFAULT_MODEL_KEY
    assert [model["key"] for model in payload["models"]] == [
        "groq-gpt-oss-20b",
        "groq-gpt-oss-120b",
        "openai-gpt-4o-mini",
    ]
    assert payload["models"][0] == {
        "key": "groq-gpt-oss-20b",
        "provider": "groq",
        "model_id": "openai/gpt-oss-20b",
        "display_name": "GPT-OSS 20B",
        "context_window_tokens": 131072,
        "supports_tool_calling": True,
    }


def test_valid_chat_selection_delegates_with_resolved_model(monkeypatch):
    captured = {}

    def fake_agent(model, query, allow_search, system_prompt):
        captured.update(
            model=model,
            query=query,
            allow_search=allow_search,
            system_prompt=system_prompt,
        )
        return {"reply": "fake reply"}

    monkeypatch.setattr(backend, "get_response_from_ai_agent", fake_agent)

    response = client.post(
        "/chat",
        json={
            "model_name": "openai/gpt-oss-20b",
            "model_provider": "GrOq",
            "system_prompt": "Be concise",
            "messages": ["Hello"],
            "allow_search": False,
        },
    )

    assert response.status_code == 200
    assert response.json() == {"reply": "fake reply"}
    assert captured["model"].key == "groq-gpt-oss-20b"
    assert captured["query"] == ["Hello"]
    assert captured["allow_search"] is False
    assert captured["system_prompt"] == "Be concise"


def test_mismatched_provider_and_model_is_rejected_before_agent(monkeypatch):
    def unexpected_agent(*args, **kwargs):
        raise AssertionError("Agent must not run for an invalid model selection")

    monkeypatch.setattr(backend, "get_response_from_ai_agent", unexpected_agent)

    response = client.post(
        "/chat",
        json={
            "model_name": "gpt-4o-mini",
            "model_provider": "groq",
            "messages": "Hello",
        },
    )

    assert response.status_code == 200
    assert "not supported by provider 'groq'" in response.json()["error"]


def test_obsolete_model_is_rejected():
    response = client.post(
        "/chat",
        json={
            "model_name": "mixtral-8x7b-32768",
            "model_provider": "groq",
            "messages": "Hello",
        },
    )

    assert response.status_code == 200
    assert "mixtral-8x7b-32768" in response.json()["error"]


def test_search_is_rejected_when_model_lacks_tool_calling(monkeypatch):
    model_without_tools = ModelSpec(
        key="future-model",
        provider=Provider.GROQ,
        model_id="future-model",
        display_name="Future model",
        context_window_tokens=1_000,
        supports_tool_calling=False,
    )
    monkeypatch.setattr(backend, "resolve_model", lambda provider, model_id: model_without_tools)

    def unexpected_agent(*args, **kwargs):
        raise AssertionError("Agent must not run with unsupported search tools")

    monkeypatch.setattr(backend, "get_response_from_ai_agent", unexpected_agent)

    response = client.post(
        "/chat",
        json={
            "model_name": "future-model",
            "model_provider": "groq",
            "messages": "Hello",
            "allow_search": True,
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "error": "Model 'future-model' does not support search tools."
    }
