from fastapi.testclient import TestClient

import backend
from ai_agent import (
    AgentOutcome,
    AgentToolLimitExceededError,
    InvalidAgentResponseError,
    MissingConfigurationError,
)
from api_contract import SearchEvidence
from model_registry import DEFAULT_MODEL_KEY, ModelSpec, Provider


client = TestClient(backend.app)


def valid_chat_payload(**overrides):
    payload = {
        "model_key": "groq-gpt-oss-20b",
        "system_prompt": "Be concise",
        "messages": [{"role": "user", "content": "Hello"}],
        "allow_search": False,
    }
    payload.update(overrides)
    return payload


def assert_error(response, status_code, code):
    assert response.status_code == status_code
    payload = response.json()
    assert payload["error"]["code"] == code
    assert isinstance(payload["error"]["message"], str)
    assert payload["error"]["details"] == []


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
        "max_output_tokens": 4096,
        "supports_tool_calling": True,
    }


def test_valid_chat_request_returns_typed_response(monkeypatch):
    captured = {}

    def fake_agent(model, messages, allow_search, system_prompt):
        captured.update(
            model=model,
            messages=messages,
            allow_search=allow_search,
            system_prompt=system_prompt,
        )
        return AgentOutcome(
            reply="fake reply",
            search=SearchEvidence(allowed=False, attempted=False),
        )

    monkeypatch.setattr(backend, "get_response_from_ai_agent", fake_agent)

    response = client.post("/chat", json=valid_chat_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["model_key"] == "groq-gpt-oss-20b"
    assert body["reply"] == "fake reply"
    assert body["context"]["was_truncated"] is False
    assert body["context"]["original_message_count"] == 1
    assert body["context"]["included_message_count"] == 1
    assert body["search"] == {
        "allowed": False,
        "attempted": False,
        "executions": [],
    }
    assert captured["model"].key == "groq-gpt-oss-20b"
    assert captured["messages"][0].role == "user"
    assert captured["messages"][0].content == "Hello"
    assert captured["allow_search"] is False
    assert captured["system_prompt"] == "Be concise"


def test_unknown_model_key_is_rejected_before_agent(monkeypatch):
    def unexpected_agent(*args, **kwargs):
        raise AssertionError("Agent must not run for an invalid model selection")

    monkeypatch.setattr(backend, "get_response_from_ai_agent", unexpected_agent)

    response = client.post(
        "/chat",
        json=valid_chat_payload(model_key="unknown-model"),
    )

    assert_error(response, 400, "unsupported_model")
    assert "unknown-model" in response.json()["error"]["message"]


def test_search_is_rejected_when_model_lacks_tool_calling(monkeypatch):
    model_without_tools = ModelSpec(
        key="future-model",
        provider=Provider.GROQ,
        model_id="future-model",
        display_name="Future model",
        context_window_tokens=1_000,
        max_output_tokens=128,
        supports_tool_calling=False,
    )
    monkeypatch.setattr(backend, "get_model_by_key", lambda model_key: model_without_tools)

    def unexpected_agent(*args, **kwargs):
        raise AssertionError("Agent must not run with unsupported search tools")

    monkeypatch.setattr(backend, "get_response_from_ai_agent", unexpected_agent)

    response = client.post(
        "/chat",
        json=valid_chat_payload(model_key="future-model", allow_search=True),
    )

    assert_error(response, 400, "unsupported_capability")


def test_backend_sends_only_the_planned_recent_window(monkeypatch):
    small_model = ModelSpec(
        key="small-model",
        provider=Provider.GROQ,
        model_id="small-model",
        display_name="Small model",
        context_window_tokens=1_000,
        max_output_tokens=128,
        supports_tool_calling=True,
    )
    monkeypatch.setattr(backend, "get_model_by_key", lambda model_key: small_model)
    captured = {}

    def fake_agent(model, messages, allow_search, system_prompt):
        captured["messages"] = messages
        return AgentOutcome(
            reply="recent reply",
            search=SearchEvidence(allowed=False, attempted=False),
        )

    monkeypatch.setattr(backend, "get_response_from_ai_agent", fake_agent)
    messages = [
        {"role": "user", "content": "a" * 500},
        {"role": "assistant", "content": "b" * 500},
        {"role": "user", "content": "c" * 500},
        {"role": "assistant", "content": "d" * 500},
        {"role": "user", "content": "e" * 500},
    ]

    response = client.post(
        "/chat",
        json=valid_chat_payload(model_key="small-model", messages=messages),
    )

    assert response.status_code == 200
    assert [item.content for item in captured["messages"]] == [
        "c" * 500,
        "d" * 500,
        "e" * 500,
    ]
    assert response.json()["context"]["omitted_message_count"] == 2


def test_oversized_latest_turn_is_rejected_before_agent(monkeypatch):
    small_model = ModelSpec(
        key="small-model",
        provider=Provider.GROQ,
        model_id="small-model",
        display_name="Small model",
        context_window_tokens=1_000,
        max_output_tokens=128,
        supports_tool_calling=True,
    )
    monkeypatch.setattr(backend, "get_model_by_key", lambda model_key: small_model)

    def unexpected_agent(*args, **kwargs):
        raise AssertionError("Agent must not run when the newest turn cannot fit")

    monkeypatch.setattr(backend, "get_response_from_ai_agent", unexpected_agent)

    response = client.post(
        "/chat",
        json=valid_chat_payload(
            model_key="small-model",
            messages=[{"role": "user", "content": "x" * 3_000}],
        ),
    )

    assert_error(response, 413, "context_window_exceeded")


def test_missing_server_configuration_returns_503(monkeypatch):
    def missing_configuration(*args, **kwargs):
        raise MissingConfigurationError("GROQ_API_KEY is required for this request.")

    monkeypatch.setattr(backend, "get_response_from_ai_agent", missing_configuration)

    response = client.post("/chat", json=valid_chat_payload())

    assert_error(response, 503, "service_configuration_error")


def test_invalid_agent_response_returns_502(monkeypatch):
    def invalid_response(*args, **kwargs):
        raise InvalidAgentResponseError("No usable assistant message was returned.")

    monkeypatch.setattr(backend, "get_response_from_ai_agent", invalid_response)

    response = client.post("/chat", json=valid_chat_payload())

    assert_error(response, 502, "invalid_upstream_response")


def test_agent_tool_limit_returns_safe_502(monkeypatch):
    def tool_limit(*args, **kwargs):
        raise AgentToolLimitExceededError("At most three searches are allowed.")

    monkeypatch.setattr(backend, "get_response_from_ai_agent", tool_limit)

    response = client.post(
        "/chat",
        json=valid_chat_payload(allow_search=True),
    )

    assert_error(response, 502, "agent_tool_limit_exceeded")


def test_validation_failure_returns_safe_structured_422():
    response = client.post(
        "/chat",
        json=valid_chat_payload(messages=[{"role": "user", "content": "   "}]),
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "request_validation_error"
    assert error["message"] == "The request body is invalid."
    assert error["details"][0]["location"] == ["body", "messages", 0, "content"]
    assert "input" not in error["details"][0]


def test_legacy_chat_payload_is_rejected():
    response = client.post(
        "/chat",
        json={
            "model_name": "openai/gpt-oss-20b",
            "model_provider": "groq",
            "messages": ["Hello"],
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "request_validation_error"


def test_unexpected_error_returns_sanitized_500(monkeypatch):
    def unexpected_failure(*args, **kwargs):
        raise RuntimeError("sensitive internal diagnostic")

    monkeypatch.setattr(backend, "get_response_from_ai_agent", unexpected_failure)
    non_raising_client = TestClient(backend.app, raise_server_exceptions=False)

    response = non_raising_client.post("/chat", json=valid_chat_payload())

    assert_error(response, 500, "internal_server_error")
    assert "sensitive" not in response.text


def test_openapi_documents_chat_contract_and_error_responses():
    operation = backend.app.openapi()["paths"]["/chat"]["post"]

    request_schema = operation["requestBody"]["content"]["application/json"]["schema"]
    assert request_schema["$ref"].endswith("/ChatRequest")
    assert operation["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/ChatResponse")
    assert set(operation["responses"]) == {
        "200",
        "400",
        "413",
        "422",
        "500",
        "502",
        "503",
    }
    for status_code in ("400", "413", "422", "500", "502", "503"):
        schema = operation["responses"][status_code]["content"]["application/json"][
            "schema"
        ]
        assert schema["$ref"].endswith("/ErrorResponse")
