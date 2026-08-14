import requests

import evaluations.live
import evaluations.storage
from api_contract import ErrorDetail, ErrorResponse
from evaluations.__main__ import main
from evaluations.live import (
    LiveEvaluationError,
    run_live_cases,
    select_cases,
    validate_live_target,
)
from evaluations.storage import load_candidates, load_dataset
from model_registry import get_models_response


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def test_select_cases_preserves_requested_order_and_rejects_invalid_filters():
    dataset = load_dataset()
    selected = select_cases(
        dataset,
        ["multi-turn-name-recall", "static-python-list"],
    )
    assert [case.id for case in selected] == [
        "multi-turn-name-recall",
        "static-python-list",
    ]
    assert select_cases(dataset, []) == dataset.cases

    for invalid in (["missing-case"], ["static-python-list"] * 2):
        try:
            select_cases(dataset, invalid)
        except LiveEvaluationError:
            pass
        else:
            raise AssertionError("Invalid filters should fail before provider calls.")


def test_live_target_validates_catalog_and_model(monkeypatch):
    calls = []

    def fake_get(url, timeout):
        calls.append((url, timeout))
        return FakeResponse(200, get_models_response().model_dump(mode="json"))

    monkeypatch.setattr(evaluations.live.requests, "get", fake_get)
    validate_live_target("http://backend/", "groq-gpt-oss-20b", 12)
    assert calls == [("http://backend/models", 12)]


def test_live_target_rejects_network_http_schema_and_model_failures(monkeypatch):
    failures = (
        requests.Timeout("private detail"),
        FakeResponse(503, {}),
        FakeResponse(200, {"unexpected": True}),
    )
    for failure in failures:

        def fake_get(url, timeout, value=failure):
            if isinstance(value, Exception):
                raise value
            return value

        monkeypatch.setattr(evaluations.live.requests, "get", fake_get)
        try:
            validate_live_target("http://backend", "groq-gpt-oss-20b", 10)
        except LiveEvaluationError as exc:
            assert "private detail" not in str(exc)
        else:
            raise AssertionError("Invalid catalog boundary should fail.")

    monkeypatch.setattr(
        evaluations.live.requests,
        "get",
        lambda url, timeout: FakeResponse(
            200,
            get_models_response().model_dump(mode="json"),
        ),
    )
    try:
        validate_live_target("http://backend", "unknown", 10)
    except LiveEvaluationError as exc:
        assert "unknown" in str(exc)
    else:
        raise AssertionError("Unknown live models must fail before execution.")


def test_live_runner_captures_success_http_error_and_continues(monkeypatch):
    dataset = load_dataset()
    baseline = load_candidates(evaluations.storage.DEFAULT_REPLAY_PATH)
    first_response = baseline[0].response
    assert first_response is not None
    error_payload = ErrorResponse(
        error=ErrorDetail(code="upstream_failed", message="Do not persist this detail")
    ).model_dump(mode="json")
    responses = iter(
        (
            FakeResponse(200, first_response.model_dump(mode="json")),
            FakeResponse(502, error_payload),
        )
    )
    requests_seen = []

    def fake_post(url, json, timeout):
        requests_seen.append((url, json, timeout))
        return next(responses)

    monkeypatch.setattr(evaluations.live.requests, "post", fake_post)
    records = run_live_cases(
        dataset.cases[:2],
        "http://backend/",
        "baseline-model",
        30,
    )
    assert records[0].response == first_response
    assert records[1].error == "http_502:upstream_failed"
    assert "Do not persist" not in records[1].error
    assert len(requests_seen) == 2
    assert all(item[0] == "http://backend/chat" for item in requests_seen)


def test_live_runner_sanitizes_timeout_malformed_json_and_wrong_model(monkeypatch):
    dataset = load_dataset()
    baseline = load_candidates(evaluations.storage.DEFAULT_REPLAY_PATH)
    wrong_model_response = baseline[0].response
    assert wrong_model_response is not None
    responses = iter(
        (
            requests.Timeout("contains-sensitive-upstream-url"),
            FakeResponse(200, ValueError("bad json")),
            FakeResponse(
                200,
                wrong_model_response.model_copy(
                    update={"model_key": "wrong"}
                ).model_dump(mode="json"),
            ),
        )
    )

    def fake_post(url, json, timeout):
        value = next(responses)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(evaluations.live.requests, "post", fake_post)
    records = run_live_cases(
        dataset.cases[:3],
        "http://backend",
        "baseline-model",
        20,
    )
    assert records[0].error == "request_failed:Timeout"
    assert records[1].error == "invalid_success_response"
    assert records[2].error == "response_model_key_mismatch"
    assert "sensitive" not in " ".join(record.error or "" for record in records)


def test_live_runner_sanitizes_invalid_error_envelope(monkeypatch):
    dataset = load_dataset()
    monkeypatch.setattr(
        evaluations.live.requests,
        "post",
        lambda url, json, timeout: FakeResponse(500, ValueError("private")),
    )
    record = run_live_cases(
        dataset.cases[:1],
        "http://backend",
        "baseline-model",
        10,
    )[0]
    assert record.error == "http_500:invalid_error_response"


def test_cli_live_requires_confirmation_before_network(monkeypatch, capsys):
    called = False

    def unexpected_call(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(evaluations.live.requests, "get", unexpected_call)
    assert main(["live", "--model-key", "groq-gpt-oss-20b"]) == 2
    assert called is False
    assert "confirm-live" in capsys.readouterr().err


def test_cli_live_rejects_invalid_timeout_before_network(capsys):
    assert (
        main(
            [
                "live",
                "--model-key",
                "groq-gpt-oss-20b",
                "--confirm-live",
                "--timeout-seconds",
                "0",
            ]
        )
        == 2
    )
    assert "timeout" in capsys.readouterr().err
