import pytest
import requests

import frontend_chat
from api_contract import ChatRequest
from frontend_chat import ChatClientError, send_chat


def context_payload(**overrides):
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
    return values


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self.payload = payload

    def json(self):
        return self.payload


def make_request():
    return ChatRequest(
        model_key="groq-gpt-oss-20b",
        messages=[{"role": "user", "content": "Hello"}],
    )


def test_frontend_sends_and_validates_canonical_contract(monkeypatch):
    captured = {}

    def fake_post(url, json, timeout):
        captured.update(url=url, json=json, timeout=timeout)
        return FakeResponse(
            200,
            {
                "model_key": "groq-gpt-oss-20b",
                "reply": "Typed reply",
                "context": context_payload(),
            },
        )

    monkeypatch.setattr(frontend_chat.requests, "post", fake_post)

    response = send_chat("http://backend/chat", 12.5, make_request())

    assert response.reply == "Typed reply"
    assert response.context.was_truncated is False
    assert captured["url"] == "http://backend/chat"
    assert captured["timeout"] == 12.5
    assert captured["json"] == {
        "model_key": "groq-gpt-oss-20b",
        "system_prompt": "Act as a helpful AI Assistant",
        "messages": [{"role": "user", "content": "Hello"}],
        "allow_search": False,
    }


@pytest.mark.parametrize(
    "error",
    [requests.ConnectionError("offline"), requests.Timeout("slow backend")],
)
def test_frontend_converts_network_failures_to_client_error(monkeypatch, error):
    monkeypatch.setattr(
        frontend_chat.requests,
        "post",
        lambda url, json, timeout: (_ for _ in ()).throw(error),
    )

    with pytest.raises(ChatClientError, match="backend chat request failed"):
        send_chat("http://backend/chat", 30, make_request())


def test_frontend_preserves_structured_backend_error(monkeypatch):
    monkeypatch.setattr(
        frontend_chat.requests,
        "post",
        lambda url, json, timeout: FakeResponse(
            400,
            {
                "error": {
                    "code": "unsupported_model",
                    "message": "The model is not supported.",
                    "details": [],
                }
            },
        ),
    )

    with pytest.raises(ChatClientError) as captured:
        send_chat("http://backend/chat", 30, make_request())

    assert captured.value.code == "unsupported_model"
    assert captured.value.status_code == 400
    assert str(captured.value) == "The model is not supported."


@pytest.mark.parametrize(
    ("status_code", "payload", "expected_message"),
    [
        (200, {"reply": "missing model key"}, "invalid success response"),
        (500, {"detail": "wrong envelope"}, "invalid error response"),
    ],
)
def test_frontend_rejects_invalid_response_contracts(
    monkeypatch,
    status_code,
    payload,
    expected_message,
):
    monkeypatch.setattr(
        frontend_chat.requests,
        "post",
        lambda url, json, timeout: FakeResponse(status_code, payload),
    )

    with pytest.raises(ChatClientError, match=expected_message):
        send_chat("http://backend/chat", 30, make_request())


def test_frontend_rejects_malformed_json(monkeypatch):
    class MalformedJsonResponse(FakeResponse):
        def json(self):
            raise ValueError("not JSON")

    monkeypatch.setattr(
        frontend_chat.requests,
        "post",
        lambda url, json, timeout: MalformedJsonResponse(502, None),
    )

    with pytest.raises(ChatClientError, match="malformed JSON"):
        send_chat("http://backend/chat", 30, make_request())
