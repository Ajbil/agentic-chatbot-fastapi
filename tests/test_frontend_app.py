from pathlib import Path

import requests
from streamlit.testing.v1 import AppTest

import frontend_catalog
import frontend_chat


FRONTEND_PATH = Path(__file__).resolve().parents[1] / "frontend.py"


VALID_CATALOG = {
    "default_model_key": "groq-gpt-oss-20b",
    "models": [
        {
            "key": "groq-gpt-oss-20b",
            "provider": "groq",
            "model_id": "openai/gpt-oss-20b",
            "display_name": "GPT-OSS 20B",
            "context_window_tokens": 131072,
            "max_output_tokens": 4096,
            "supports_tool_calling": True,
        },
        {
            "key": "openai-gpt-4o-mini",
            "provider": "openai",
            "model_id": "gpt-4o-mini",
            "display_name": "GPT-4o mini",
            "context_window_tokens": 128000,
            "max_output_tokens": 4096,
            "supports_tool_calling": True,
        },
    ],
}


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self.payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError(f"Unexpected catalog status: {self.status_code}")

    def json(self):
        return self.payload

    def iter_lines(self, decode_unicode=False):
        events = [
            {"version": 1, "type": "started", "sequence": 1, "model_key": self.payload["model_key"]},
            {"version": 1, "type": "status", "sequence": 2, "stage": "model_running"},
            {"version": 1, "type": "delta", "sequence": 3, "text": self.payload["reply"]},
            {"version": 1, "type": "complete", "sequence": 4, "response": self.payload},
        ]
        import json
        return iter(json.dumps(event) for event in events)

    def close(self):
        pass


def chat_success(request, reply, *, truncated=False, search=None):
    message_count = len(request["messages"])
    omitted_count = 2 if truncated else 0
    included_count = message_count - omitted_count
    return {
        "model_key": request["model_key"],
        "reply": reply,
        "context": {
            "estimation_method": "langchain_approximate_v1",
            "context_window_tokens": 131072,
            "reserved_output_tokens": 4096,
            "safety_margin_tokens": 13108,
            "input_budget_tokens": 113868,
            "estimated_full_input_tokens": 100,
            "estimated_sent_input_tokens": 80 if truncated else 100,
            "original_message_count": message_count,
            "included_message_count": included_count,
            "omitted_message_count": omitted_count,
            "was_truncated": truncated,
        },
        "search": search
        or {
            "allowed": request["allow_search"],
            "attempted": False,
            "executions": [],
        },
    }


def test_streamlit_chat_commits_history_and_locks_settings(monkeypatch):
    captured_requests = []

    monkeypatch.setattr(
        frontend_catalog.requests,
        "get",
        lambda url, timeout: FakeResponse(200, VALID_CATALOG),
    )

    def fake_post(url, json, timeout, stream):
        captured_requests.append(json)
        return FakeResponse(
            200,
            chat_success(json, f"Answer {len(captured_requests)}"),
        )

    monkeypatch.setattr(frontend_chat.requests, "post", fake_post)

    app = AppTest.from_file(FRONTEND_PATH, default_timeout=10).run()
    assert len(app.chat_input) == 1

    app.chat_input[0].set_value("First question").run()

    assert len(app.chat_message) == 2
    assert [message.markdown[0].value for message in app.chat_message] == [
        "First question",
        "Answer 1",
    ]
    assert app.radio[0].disabled is True
    assert app.selectbox[0].disabled is True
    assert app.text_area[0].disabled is True
    assert app.checkbox[0].disabled is True

    app.chat_input[0].set_value("Follow-up").run()

    assert len(app.chat_message) == 4
    assert [message["content"] for message in captured_requests[1]["messages"]] == [
        "First question",
        "Answer 1",
        "Follow-up",
    ]


def test_streamlit_preserves_full_transcript_and_discloses_backend_trimming(
    monkeypatch,
):
    captured_requests = []
    monkeypatch.setattr(
        frontend_catalog.requests,
        "get",
        lambda url, timeout: FakeResponse(200, VALID_CATALOG),
    )

    def fake_post(url, json, timeout, stream):
        captured_requests.append(json)
        return FakeResponse(
            200,
            chat_success(
                json,
                f"Answer {len(captured_requests)}",
                truncated=len(captured_requests) == 2,
            ),
        )

    monkeypatch.setattr(frontend_chat.requests, "post", fake_post)

    app = AppTest.from_file(FRONTEND_PATH, default_timeout=10).run()
    app.chat_input[0].set_value("First question").run()
    app.chat_input[0].set_value("Follow-up").run()

    assert [message.markdown[0].value for message in app.chat_message] == [
        "First question",
        "Answer 1",
        "Follow-up",
        "Answer 2",
    ]
    assert any(
        "omitted 2 older message(s)" in warning.value for warning in app.warning
    )
    assert any("80 / 113,868 tokens" in caption.value for caption in app.caption)


def test_streamlit_keeps_web_sources_with_their_answer(monkeypatch):
    captured_requests = []
    monkeypatch.setattr(
        frontend_catalog.requests,
        "get",
        lambda url, timeout: FakeResponse(200, VALID_CATALOG),
    )

    def fake_post(url, json, timeout, stream):
        captured_requests.append(json)
        if len(captured_requests) == 1:
            search = {
                "allowed": True,
                "attempted": True,
                "executions": [
                    {
                        "query": "latest release",
                        "status": "succeeded",
                        "sources": [
                            {
                                "title": "Official release",
                                "url": "https://example.com/release",
                                "snippet": "Release evidence",
                            }
                        ],
                    },
                    {
                        "query": "secondary query",
                        "status": "failed",
                        "sources": [],
                    },
                ],
            }
        else:
            search = {"allowed": True, "attempted": False, "executions": []}
        return FakeResponse(
            200,
            chat_success(json, f"Answer {len(captured_requests)}", search=search),
        )

    monkeypatch.setattr(frontend_chat.requests, "post", fake_post)

    app = AppTest.from_file(FRONTEND_PATH, default_timeout=10).run()
    app.checkbox[0].check().run()
    app.chat_input[0].set_value("Current question").run()
    app.chat_input[0].set_value("Follow-up").run()

    assert [item.label for item in app.expander] == ["Web sources"]
    assert app.text[0].value == "Release evidence"
    assert any("latest release" in caption.value for caption in app.caption)
    assert any("additional web search" in warning.value for warning in app.warning)
    assert any("available but not used" in caption.value for caption in app.caption)


def test_streamlit_discloses_total_search_failure(monkeypatch):
    monkeypatch.setattr(
        frontend_catalog.requests,
        "get",
        lambda url, timeout: FakeResponse(200, VALID_CATALOG),
    )
    monkeypatch.setattr(
        frontend_chat.requests,
        "post",
        lambda url, json, timeout, stream: FakeResponse(
            200,
            chat_success(
                json,
                "Unverified answer",
                search={
                    "allowed": True,
                    "attempted": True,
                    "executions": [
                        {
                            "query": "unavailable information",
                            "status": "failed",
                            "sources": [],
                        }
                    ],
                },
            ),
        ),
    )

    app = AppTest.from_file(FRONTEND_PATH, default_timeout=10).run()
    app.checkbox[0].check().run()
    app.chat_input[0].set_value("Question").run()

    assert any(
        "returned no usable evidence" in warning.value for warning in app.warning
    )
    assert len(app.expander) == 0


def test_provider_change_selects_a_valid_model_before_locking(monkeypatch):
    captured_requests = []

    monkeypatch.setattr(
        frontend_catalog.requests,
        "get",
        lambda url, timeout: FakeResponse(200, VALID_CATALOG),
    )

    def fake_post(url, json, timeout, stream):
        captured_requests.append(json)
        return FakeResponse(
            200,
            chat_success(json, "OpenAI answer"),
        )

    monkeypatch.setattr(frontend_chat.requests, "post", fake_post)

    app = AppTest.from_file(FRONTEND_PATH, default_timeout=10).run()
    app.radio[0].set_value("openai").run()

    assert app.selectbox[0].value == "openai-gpt-4o-mini"

    app.chat_input[0].set_value("Use the selected provider").run()

    assert captured_requests[0]["model_key"] == "openai-gpt-4o-mini"
    assert app.radio[0].disabled is True


def test_streamlit_failure_is_retryable_and_not_committed(monkeypatch):
    attempts = 0

    monkeypatch.setattr(
        frontend_catalog.requests,
        "get",
        lambda url, timeout: FakeResponse(200, VALID_CATALOG),
    )

    def fake_post(url, json, timeout, stream):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return FakeResponse(
                503,
                {
                    "error": {
                        "code": "service_configuration_error",
                        "message": "Provider configuration is unavailable.",
                        "details": [],
                    }
                },
            )
        return FakeResponse(
            200,
            chat_success(json, "Recovered answer"),
        )

    monkeypatch.setattr(frontend_chat.requests, "post", fake_post)

    app = AppTest.from_file(FRONTEND_PATH, default_timeout=10).run()
    app.chat_input[0].set_value("Retry this question").run()

    assert len(app.chat_message) == 1
    assert app.chat_input[0].disabled is True
    assert "Not added to conversation history" in app.chat_message[0].caption[0].value
    assert app.error[0].value == "Provider configuration is unavailable."

    retry_button = next(button for button in app.button if button.label == "Retry")
    retry_button.click().run()

    assert len(app.chat_message) == 2
    assert [message.markdown[0].value for message in app.chat_message] == [
        "Retry this question",
        "Recovered answer",
    ]
    assert attempts == 2


def test_new_chat_clears_history_and_unlocks_settings(monkeypatch):
    monkeypatch.setattr(
        frontend_catalog.requests,
        "get",
        lambda url, timeout: FakeResponse(200, VALID_CATALOG),
    )
    monkeypatch.setattr(
        frontend_chat.requests,
        "post",
        lambda url, json, timeout, stream: FakeResponse(
            200,
            chat_success(json, "Answer"),
        ),
    )

    app = AppTest.from_file(FRONTEND_PATH, default_timeout=10).run()
    app.chat_input[0].set_value("Question").run()
    assert len(app.chat_message) == 2

    new_chat_button = next(button for button in app.button if button.label == "New chat")
    new_chat_button.click().run()

    assert len(app.chat_message) == 0
    assert app.radio[0].disabled is False
    assert app.selectbox[0].disabled is False
    assert app.text_area[0].disabled is False
    assert app.checkbox[0].disabled is False


def test_history_remains_visible_when_catalog_later_fails(monkeypatch):
    catalog_available = True

    def fake_get(url, timeout):
        if not catalog_available:
            raise requests.ConnectionError("backend offline")
        return FakeResponse(200, VALID_CATALOG)

    monkeypatch.setattr(frontend_catalog.requests, "get", fake_get)
    monkeypatch.setattr(
        frontend_chat.requests,
        "post",
        lambda url, json, timeout, stream: FakeResponse(
            200,
            chat_success(json, "Saved answer"),
        ),
    )

    app = AppTest.from_file(FRONTEND_PATH, default_timeout=10).run()
    app.chat_input[0].set_value("Saved question").run()
    catalog_available = False
    app.run()

    assert [message.markdown[0].value for message in app.chat_message] == [
        "Saved question",
        "Saved answer",
    ]
    assert app.chat_input[0].disabled is True
    assert any(
        "Could not load supported models" in error.value for error in app.error
    )
