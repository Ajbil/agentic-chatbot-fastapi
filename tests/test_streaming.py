import json

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, AIMessageChunk

import ai_agent
import backend
import frontend_chat
from ai_agent import AgentOutcome, AgentStreamEvent, PreparedAgentRun
from api_contract import (
    ChatRequest,
    GroundingEvidence,
    SearchEvidence,
    SearchExecution,
    StreamCompleteEvent,
    StreamDeltaEvent,
    StreamStartedEvent,
)
from frontend_chat import ChatClientError, stream_chat


def request_model():
    return ChatRequest(
        model_key="groq-gpt-oss-20b",
        messages=[{"role": "user", "content": "Hello"}],
    )


def response_payload(reply="Hello world"):
    return {
        "model_key": "groq-gpt-oss-20b",
        "reply": reply,
        "context": {
            "estimation_method": "langchain_approximate_v1",
            "context_window_tokens": 1000,
            "reserved_output_tokens": 128,
            "safety_margin_tokens": 256,
            "input_budget_tokens": 616,
            "estimated_full_input_tokens": 20,
            "estimated_sent_input_tokens": 20,
            "original_message_count": 1,
            "included_message_count": 1,
            "omitted_message_count": 0,
            "was_truncated": False,
        },
        "search": {"allowed": False, "attempted": False, "executions": []},
        "grounding": {
            "status": "not_applicable",
            "cited_source_ids": [],
            "repair_attempted": False,
        },
    }


def encode_events(events):
    return [json.dumps(event) for event in events]


class FakeStreamResponse:
    def __init__(self, status_code=200, lines=(), payload=None):
        self.status_code = status_code
        self.lines = lines
        self.payload = payload
        self.closed = False

    def iter_lines(self, decode_unicode=False):
        return iter(self.lines)

    def json(self):
        return self.payload

    def close(self):
        self.closed = True


def successful_events(reply="Hello world"):
    return [
        {
            "version": 1,
            "type": "started",
            "sequence": 1,
            "model_key": "groq-gpt-oss-20b",
        },
        {"version": 1, "type": "status", "sequence": 2, "stage": "model_running"},
        {"version": 1, "type": "delta", "sequence": 3, "text": "Hello "},
        {"version": 1, "type": "delta", "sequence": 4, "text": "world"},
        {
            "version": 1,
            "type": "complete",
            "sequence": 5,
            "response": response_payload(reply),
        },
    ]


def test_frontend_validates_stream_and_closes_response(monkeypatch):
    response = FakeStreamResponse(lines=encode_events(successful_events()))
    captured = {}

    def fake_post(url, json, stream, timeout):
        captured.update(url=url, body=json, stream=stream, timeout=timeout)
        return response

    monkeypatch.setattr(frontend_chat.requests, "post", fake_post)
    events = list(stream_chat("http://backend/chat/stream", 10, 120, request_model()))

    assert isinstance(events[0], StreamStartedEvent)
    assert [event.text for event in events if isinstance(event, StreamDeltaEvent)] == [
        "Hello ",
        "world",
    ]
    assert isinstance(events[-1], StreamCompleteEvent)
    assert captured["stream"] is True
    assert captured["timeout"] == (10, 120)
    assert response.closed is True


@pytest.mark.parametrize(
    ("events", "message"),
    [
        ([{**successful_events()[1], "sequence": 1}], "did not begin"),
        (
            [successful_events()[0], {**successful_events()[2], "sequence": 4}],
            "sequence",
        ),
        (successful_events()[:-1], "terminal"),
        (successful_events("different"), "did not match"),
        (
            successful_events()
            + [{"version": 1, "type": "status", "sequence": 6, "stage": "finalizing"}],
            "continued",
        ),
    ],
)
def test_frontend_rejects_broken_stream_protocol(monkeypatch, events, message):
    response = FakeStreamResponse(lines=encode_events(events))
    monkeypatch.setattr(
        frontend_chat.requests, "post", lambda *args, **kwargs: response
    )

    with pytest.raises(ChatClientError, match=message) as captured:
        list(stream_chat("http://backend/chat/stream", 10, 120, request_model()))

    assert captured.value.code == "invalid_stream_response"
    assert response.closed is True


def test_frontend_preserves_pre_stream_http_error(monkeypatch):
    response = FakeStreamResponse(
        status_code=503,
        payload={
            "error": {
                "code": "service_configuration_error",
                "message": "Missing key",
                "details": [],
            }
        },
    )
    monkeypatch.setattr(
        frontend_chat.requests, "post", lambda *args, **kwargs: response
    )

    with pytest.raises(ChatClientError) as captured:
        list(stream_chat("http://backend/chat/stream", 10, 120, request_model()))

    assert captured.value.code == "service_configuration_error"
    assert captured.value.status_code == 503


def test_frontend_preserves_partial_reply_on_terminal_error(monkeypatch):
    events = successful_events()[:3] + [
        {
            "version": 1,
            "type": "error",
            "sequence": 4,
            "error": {
                "code": "upstream_stream_failed",
                "message": "Stream failed",
                "details": [],
            },
        }
    ]
    monkeypatch.setattr(
        frontend_chat.requests,
        "post",
        lambda *args, **kwargs: FakeStreamResponse(lines=encode_events(events)),
    )

    with pytest.raises(ChatClientError) as captured:
        list(stream_chat("http://backend/chat/stream", 10, 120, request_model()))

    assert captured.value.code == "upstream_stream_failed"
    assert captured.value.partial_reply == "Hello "


def test_agent_stream_buffers_tool_decision_text_and_emits_final_answer():
    class FakeAgent:
        def stream(self, state, stream_mode, version):
            yield {
                "type": "messages",
                "ns": (),
                "data": (AIMessageChunk(content="I will search"), {}),
            }
            yield {
                "type": "updates",
                "ns": (),
                "data": {
                    "model": {
                        "messages": [
                            AIMessage(
                                content="I will search",
                                tool_calls=[
                                    {
                                        "name": "tavily_search",
                                        "args": {"query": "news"},
                                        "id": "s1",
                                        "type": "tool_call",
                                    }
                                ],
                            )
                        ]
                    }
                },
            }
            from langchain_core.messages import ToolMessage

            yield {
                "type": "updates",
                "ns": (),
                "data": {
                    "normalize_search_results": {
                        "messages": [
                            ToolMessage(
                                name="tavily_search",
                                tool_call_id="s1",
                                content=json.dumps(
                                    {
                                        "results": [
                                            {
                                                "title": "News",
                                                "url": "https://example.com",
                                                "content": "Evidence",
                                            }
                                        ]
                                    }
                                ),
                            )
                        ],
                        "search_executions": (
                            SearchExecution(query="news", status="failed"),
                        ),
                    }
                },
            }
            yield {
                "type": "messages",
                "ns": (),
                "data": (AIMessageChunk(content="Final "), {}),
            }
            yield {
                "type": "messages",
                "ns": (),
                "data": (AIMessageChunk(content="answer"), {}),
            }
            yield {
                "type": "updates",
                "ns": (),
                "data": {"model": {"messages": [AIMessage(content="Final answer")]}},
            }

    events = list(
        ai_agent.stream_prepared_agent(
            PreparedAgentRun(FakeAgent(), ai_agent._initial_graph_state([]), True)
        )
    )

    assert [event.value for event in events if event.type == "delta"] == [
        "Final ",
        "answer",
    ]
    assert "I will search" not in [event.value for event in events]
    assert [event.value for event in events if event.type == "status"] == [
        "model_running",
        "search_running",
        "search_results_received",
        "model_running",
        "finalizing",
    ]
    assert events[-1].value.reply == "Final answer"
    assert events[-1].value.search.executions[0].query == "news"


def test_backend_stream_is_contiguous_and_terminal(monkeypatch):
    prepared = PreparedAgentRun(object(), {}, False)
    monkeypatch.setattr(backend, "prepare_agent_run", lambda *args, **kwargs: prepared)
    monkeypatch.setattr(
        backend,
        "stream_prepared_agent",
        lambda value: iter(
            [
                AgentStreamEvent("status", "model_running"),
                AgentStreamEvent("delta", "Hello "),
                AgentStreamEvent("delta", "world"),
                AgentStreamEvent(
                    "complete",
                    AgentOutcome(
                        "Hello world",
                        SearchEvidence(allowed=False, attempted=False),
                        GroundingEvidence(status="not_applicable"),
                    ),
                ),
            ]
        ),
    )
    response = TestClient(backend.app).post(
        "/chat/stream", json=request_model().model_dump(mode="json")
    )
    events = [json.loads(line) for line in response.text.splitlines()]

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))
    assert events[0]["type"] == "started"
    assert events[-1]["type"] == "complete"


def test_backend_converts_midstream_exception_to_safe_terminal_event(monkeypatch):
    monkeypatch.setattr(
        backend,
        "prepare_agent_run",
        lambda *args, **kwargs: PreparedAgentRun(object(), {}, False),
    )

    def failed_stream(value):
        yield AgentStreamEvent("delta", "Partial")
        raise RuntimeError("secret provider diagnostic")

    monkeypatch.setattr(backend, "stream_prepared_agent", failed_stream)
    response = TestClient(backend.app).post(
        "/chat/stream", json=request_model().model_dump(mode="json")
    )
    events = [json.loads(line) for line in response.text.splitlines()]

    assert events[-1]["type"] == "error"
    assert events[-1]["error"]["code"] == "upstream_stream_failed"
    assert "secret" not in response.text
