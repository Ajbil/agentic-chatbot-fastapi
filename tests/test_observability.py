import json
import logging
import re
from asyncio import run
from concurrent.futures import ThreadPoolExecutor
from io import StringIO
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from prometheus_client import CollectorRegistry

import backend
from ai_agent import AgentOutcome, AgentStreamEvent, PreparedAgentRun
from api_contract import (
    ChatResponse,
    ContextUsage,
    GroundingEvidence,
    SearchEvidence,
    SearchExecution,
    SearchSource,
)
from observability import (
    REQUEST_ID_HEADER,
    ChatRunTracker,
    OperationalTelemetry,
    RequestObservabilityMiddleware,
    configure_logging,
)

REQUEST_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")


def chat_payload(**overrides):
    payload = {
        "model_key": "groq-gpt-oss-20b",
        "system_prompt": "private-system-sentinel",
        "messages": [{"role": "user", "content": "private-prompt-sentinel"}],
        "allow_search": False,
    }
    payload.update(overrides)
    return payload


def context_usage(*, truncated=False):
    return ContextUsage(
        estimation_method="langchain_approximate_v1",
        context_window_tokens=1_000,
        reserved_output_tokens=128,
        safety_margin_tokens=256,
        input_budget_tokens=616,
        estimated_full_input_tokens=40,
        estimated_sent_input_tokens=20,
        original_message_count=3 if truncated else 1,
        included_message_count=1,
        omitted_message_count=2 if truncated else 0,
        was_truncated=truncated,
    )


def telemetry_fixture():
    stream = StringIO()
    logger = logging.getLogger(f"observability-test-{id(stream)}")
    logger = configure_logging("DEBUG", "json", stream=stream, logger=logger)
    telemetry = OperationalTelemetry(
        registry=CollectorRegistry(),
        logger=logger,
    )
    return telemetry, stream


def sample_value(telemetry, name, labels=None):
    return telemetry.registry.get_sample_value(name, labels or {})


def test_request_ids_are_server_owned_correlated_and_concurrency_safe():
    telemetry, stream = telemetry_fixture()
    app = backend.create_app(telemetry)

    def make_request(index):
        with TestClient(app) as client:
            return client.get(
                "/models",
                headers={REQUEST_ID_HEADER: f"caller-controlled-{index}"},
            ).headers[REQUEST_ID_HEADER]

    with ThreadPoolExecutor(max_workers=6) as executor:
        request_ids = list(executor.map(make_request, range(12)))

    assert len(set(request_ids)) == 12
    assert all(REQUEST_ID_PATTERN.fullmatch(value) for value in request_ids)
    assert all("caller-controlled" not in value for value in request_ids)

    records = [json.loads(line) for line in stream.getvalue().splitlines()]
    completion_ids = {
        record["request_id"]
        for record in records
        if record["event"] == "http_request_completed"
    }
    assert completion_ids == set(request_ids)
    assert (
        sample_value(
            telemetry,
            "agentic_chatbot_http_requests_total",
            {"method": "GET", "route": "/models", "status_class": "2xx"},
        )
        == 12
    )


def test_validation_and_unmatched_routes_are_bounded_and_correlated():
    telemetry, stream = telemetry_fixture()
    client = TestClient(backend.create_app(telemetry))

    invalid = client.post("/chat", json=chat_payload(messages=[]))
    unmatched = client.get("/user-controlled-secret-path")
    unusual_method = client.request("PRIVATE-METHOD", "/models")

    assert REQUEST_ID_PATTERN.fullmatch(invalid.headers[REQUEST_ID_HEADER])
    assert REQUEST_ID_PATTERN.fullmatch(unmatched.headers[REQUEST_ID_HEADER])
    assert unusual_method.status_code == 405
    assert (
        sample_value(
            telemetry,
            "agentic_chatbot_http_requests_total",
            {"method": "POST", "route": "/chat", "status_class": "4xx"},
        )
        == 1
    )
    assert (
        sample_value(
            telemetry,
            "agentic_chatbot_http_requests_total",
            {"method": "GET", "route": "unmatched", "status_class": "4xx"},
        )
        == 1
    )
    assert "user-controlled-secret-path" not in stream.getvalue()
    assert "PRIVATE-METHOD" not in stream.getvalue()
    assert (
        sample_value(
            telemetry,
            "agentic_chatbot_http_requests_total",
            {"method": "OTHER", "route": "/models", "status_class": "4xx"},
        )
        == 1
    )


def test_sync_chat_metrics_and_logs_use_only_safe_bounded_evidence(monkeypatch):
    telemetry, stream = telemetry_fixture()
    client = TestClient(backend.create_app(telemetry))
    source = SearchSource(
        source_id="S1",
        title="private-title-sentinel",
        url="https://private-url-sentinel.example/path",
        snippet="private-snippet-sentinel",
    )

    monkeypatch.setattr(
        backend,
        "get_response_from_ai_agent",
        lambda *args, **kwargs: AgentOutcome(
            reply="private-answer-sentinel [S1]",
            search=SearchEvidence(
                allowed=True,
                attempted=True,
                executions=(
                    SearchExecution(
                        query="private-query-sentinel",
                        status="succeeded",
                        sources=(source,),
                    ),
                ),
            ),
            grounding=GroundingEvidence(
                status="cited",
                cited_source_ids=("S1",),
                repair_attempted=True,
            ),
        ),
    )

    response = client.post("/chat", json=chat_payload(allow_search=True))

    assert response.status_code == 200
    labels = {
        "transport": "sync",
        "model_key": "groq-gpt-oss-20b",
        "outcome": "success",
    }
    assert (
        sample_value(
            telemetry,
            "agentic_chatbot_chat_runs_total",
            labels,
        )
        == 1
    )
    assert (
        sample_value(
            telemetry,
            "agentic_chatbot_search_executions_total",
            {"model_key": "groq-gpt-oss-20b", "status": "succeeded"},
        )
        == 1
    )
    assert (
        sample_value(
            telemetry,
            "agentic_chatbot_grounding_results_total",
            {
                "model_key": "groq-gpt-oss-20b",
                "status": "cited",
                "repair_attempted": "true",
            },
        )
        == 1
    )
    log_output = stream.getvalue()
    for private_value in (
        "private-system-sentinel",
        "private-prompt-sentinel",
        "private-answer-sentinel",
        "private-title-sentinel",
        "private-url-sentinel",
        "private-snippet-sentinel",
        "private-query-sentinel",
    ):
        assert private_value not in log_output
    chat_record = next(
        json.loads(line)
        for line in log_output.splitlines()
        if json.loads(line)["event"] == "chat_run_completed"
    )
    assert chat_record["request_id"] == response.headers[REQUEST_ID_HEADER]


def test_unknown_models_and_unexpected_errors_do_not_leak_values(monkeypatch):
    telemetry, stream = telemetry_fixture()
    client = TestClient(
        backend.create_app(telemetry),
        raise_server_exceptions=False,
    )

    unsupported = client.post(
        "/chat",
        json=chat_payload(model_key="private-model-sentinel"),
    )

    def fail_with_private_diagnostic(*args, **kwargs):
        raise RuntimeError("private-exception-sentinel")

    monkeypatch.setattr(
        backend, "get_response_from_ai_agent", fail_with_private_diagnostic
    )
    unexpected = client.post("/chat", json=chat_payload())

    assert unsupported.status_code == 400
    assert unexpected.status_code == 500
    assert (
        sample_value(
            telemetry,
            "agentic_chatbot_chat_runs_total",
            {
                "transport": "sync",
                "model_key": "unknown",
                "outcome": "unsupported_model",
            },
        )
        == 1
    )
    log_output = stream.getvalue()
    assert "private-model-sentinel" not in log_output
    assert "private-exception-sentinel" not in log_output
    assert "RuntimeError" in log_output


def test_stream_metrics_finalize_once_and_hide_runtime_diagnostics(monkeypatch):
    telemetry, stream = telemetry_fixture()
    client = TestClient(backend.create_app(telemetry))
    monkeypatch.setattr(
        backend,
        "prepare_agent_run",
        lambda *args, **kwargs: PreparedAgentRun(object(), {}, False),
    )

    def failed_stream(value):
        yield AgentStreamEvent("delta", "Visible partial")
        raise RuntimeError("private-stream-exception-sentinel")

    monkeypatch.setattr(backend, "stream_prepared_agent", failed_stream)

    response = client.post("/chat/stream", json=chat_payload())

    assert response.status_code == 200
    assert sample_value(telemetry, "agentic_chatbot_active_streams") == 0
    assert (
        sample_value(
            telemetry,
            "agentic_chatbot_chat_runs_total",
            {
                "transport": "stream",
                "model_key": "groq-gpt-oss-20b",
                "outcome": "upstream_stream_failed",
            },
        )
        == 1
    )
    assert (
        sample_value(
            telemetry,
            "agentic_chatbot_stream_time_to_first_delta_seconds_count",
            {"model_key": "groq-gpt-oss-20b"},
        )
        == 1
    )
    assert "private-stream-exception-sentinel" not in stream.getvalue()
    assert "RuntimeError" in stream.getvalue()


def test_successful_stream_records_domain_metrics_once(monkeypatch):
    telemetry, _ = telemetry_fixture()
    client = TestClient(backend.create_app(telemetry))
    monkeypatch.setattr(
        backend,
        "prepare_agent_run",
        lambda *args, **kwargs: PreparedAgentRun(object(), {}, False),
    )
    monkeypatch.setattr(
        backend,
        "stream_prepared_agent",
        lambda value: iter(
            [
                AgentStreamEvent("delta", "Complete answer"),
                AgentStreamEvent(
                    "complete",
                    AgentOutcome(
                        "Complete answer",
                        SearchEvidence(allowed=False, attempted=False),
                        GroundingEvidence(status="not_applicable"),
                    ),
                ),
            ]
        ),
    )

    response = client.post("/chat/stream", json=chat_payload())

    assert response.status_code == 200
    assert sample_value(telemetry, "agentic_chatbot_active_streams") == 0
    assert (
        sample_value(
            telemetry,
            "agentic_chatbot_chat_runs_total",
            {
                "transport": "stream",
                "model_key": "groq-gpt-oss-20b",
                "outcome": "success",
            },
        )
        == 1
    )
    assert (
        sample_value(
            telemetry,
            "agentic_chatbot_stream_time_to_first_delta_seconds_count",
            {"model_key": "groq-gpt-oss-20b"},
        )
        == 1
    )


def test_tracker_is_idempotent_and_closes_abandoned_streams():
    telemetry, _ = telemetry_fixture()
    tracker = telemetry.start_chat("stream")
    assert isinstance(tracker, ChatRunTracker)
    tracker.set_model_key("groq-gpt-oss-20b")
    tracker.open_stream()
    tracker.fail("client_disconnect")
    tracker.fail("internal_server_error")

    assert sample_value(telemetry, "agentic_chatbot_active_streams") == 0
    assert (
        sample_value(
            telemetry,
            "agentic_chatbot_chat_runs_total",
            {
                "transport": "stream",
                "model_key": "groq-gpt-oss-20b",
                "outcome": "client_disconnect",
            },
        )
        == 1
    )
    assert (
        sample_value(
            telemetry,
            "agentic_chatbot_chat_runs_total",
            {
                "transport": "stream",
                "model_key": "groq-gpt-oss-20b",
                "outcome": "internal_server_error",
            },
        )
        is None
    )


def test_context_metrics_record_only_bounded_terminal_evidence():
    telemetry, _ = telemetry_fixture()
    tracker = telemetry.start_chat("sync")
    tracker.set_model_key("groq-gpt-oss-20b")
    tracker.succeed(
        ChatResponse(
            model_key="groq-gpt-oss-20b",
            reply="Answer",
            context=context_usage(truncated=True),
            search=SearchEvidence(allowed=False, attempted=False),
            grounding=GroundingEvidence(status="not_applicable"),
        )
    )

    assert (
        sample_value(
            telemetry,
            "agentic_chatbot_context_input_tokens_count",
            {"model_key": "groq-gpt-oss-20b", "truncated": "true"},
        )
        == 1
    )


def test_interrupted_response_body_is_counted_as_aborted():
    telemetry, stream = telemetry_fixture()

    async def inner_app(scope, receive, send):
        scope["route"] = SimpleNamespace(path="/chat/stream")
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"partial"})

    async def disconnected_send(message):
        if message["type"] == "http.response.body":
            raise RuntimeError("client disconnected")

    middleware = RequestObservabilityMiddleware(inner_app, telemetry)
    scope = {"type": "http", "method": "POST", "state": {}}

    with pytest.raises(RuntimeError, match="client disconnected"):
        run(middleware(scope, lambda: None, disconnected_send))

    assert (
        sample_value(
            telemetry,
            "agentic_chatbot_http_requests_total",
            {"method": "POST", "route": "/chat/stream", "status_class": "aborted"},
        )
        == 1
    )
    record = json.loads(stream.getvalue())
    assert record["response_completed"] is False


def test_metrics_endpoint_does_not_instrument_its_own_scrapes():
    telemetry, _ = telemetry_fixture()
    client = TestClient(backend.create_app(telemetry))

    first = client.get("/metrics")
    second = client.get("/metrics")

    assert first.status_code == 200
    assert first.headers["content-type"].startswith("text/plain")
    assert "agentic_chatbot_http_requests_total" in second.text
    assert (
        sample_value(
            telemetry,
            "agentic_chatbot_http_requests_total",
            {"method": "GET", "route": "/metrics", "status_class": "2xx"},
        )
        is None
    )


@pytest.mark.parametrize("log_format", ["json", "console"])
def test_configured_log_formats_are_safe_and_readable(log_format):
    stream = StringIO()
    logger = configure_logging(
        "INFO",
        log_format,
        stream=stream,
        logger=logging.getLogger(f"format-test-{log_format}"),
    )
    telemetry = OperationalTelemetry(
        registry=CollectorRegistry(),
        logger=logger,
    )

    telemetry.log_event(
        logging.INFO,
        "sample_event",
        outcome="success",
        prompt="private-log-field-sentinel",
    )

    output = stream.getvalue()
    assert "sample_event" in output
    assert "outcome" in output
    assert "private-log-field-sentinel" not in output
    if log_format == "json":
        assert json.loads(output)["outcome"] == "success"


def test_unstructured_logs_and_invalid_request_ids_do_not_bypass_allowlist():
    stream = StringIO()
    logger = configure_logging(
        "INFO",
        "json",
        stream=stream,
        logger=logging.getLogger("unstructured-log-test"),
    )

    logger.info(
        "private-unstructured-message-sentinel",
        extra={"request_id": "caller-controlled-request-id"},
    )

    output = json.loads(stream.getvalue())
    assert output["event"] == "unstructured_log"
    assert "request_id" not in output
    assert "private-unstructured-message-sentinel" not in stream.getvalue()


def test_exception_frames_use_only_file_names():
    telemetry, stream = telemetry_fixture()

    try:
        raise RuntimeError("private-diagnostic")
    except RuntimeError as exc:
        telemetry.log_unexpected_exception("unexpected_test_error", exc)

    record = json.loads(stream.getvalue())
    assert record["traceback_frames"][-1]["file"] == "test_observability.py"
    assert "/" not in record["traceback_frames"][-1]["file"]
    assert "\\" not in record["traceback_frames"][-1]["file"]
    assert "private-diagnostic" not in stream.getvalue()
