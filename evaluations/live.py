from collections.abc import Iterable
from time import perf_counter

import requests
from pydantic import ValidationError

from api_contract import ChatResponse, ErrorResponse
from evaluations.models import CandidateRecord, EvaluationCase, EvaluationDataset
from model_registry import ModelsResponse


class LiveEvaluationError(RuntimeError):
    """Raised when a live evaluation cannot safely begin."""


def select_cases(
    dataset: EvaluationDataset,
    case_ids: Iterable[str],
) -> tuple[EvaluationCase, ...]:
    requested = tuple(case_ids)
    if not requested:
        return dataset.cases
    if len(requested) != len(set(requested)):
        raise LiveEvaluationError("Live case filters must not contain duplicates.")

    cases_by_id = {case.id: case for case in dataset.cases}
    unknown = sorted(set(requested) - set(cases_by_id))
    if unknown:
        raise LiveEvaluationError(f"Unknown evaluation case IDs: {unknown}")
    return tuple(cases_by_id[case_id] for case_id in requested)


def validate_live_target(
    backend_base_url: str,
    model_key: str,
    timeout_seconds: float,
) -> None:
    try:
        response = requests.get(
            f"{backend_base_url.rstrip('/')}/models",
            timeout=timeout_seconds,
        )
    except requests.RequestException as exc:
        raise LiveEvaluationError(
            f"Backend catalog request failed ({type(exc).__name__})."
        ) from exc
    if response.status_code != 200:
        raise LiveEvaluationError(
            f"Backend catalog returned HTTP {response.status_code}."
        )
    try:
        catalog = ModelsResponse.model_validate(response.json())
    except (ValueError, ValidationError) as exc:
        raise LiveEvaluationError("Backend catalog response is invalid.") from exc
    if model_key not in {model.key for model in catalog.models}:
        raise LiveEvaluationError(
            f"Model key is not in the backend catalog: {model_key}"
        )


def run_live_cases(
    cases: Iterable[EvaluationCase],
    backend_base_url: str,
    model_key: str,
    timeout_seconds: float,
) -> tuple[CandidateRecord, ...]:
    records: list[CandidateRecord] = []
    chat_url = f"{backend_base_url.rstrip('/')}/chat"
    for case in cases:
        started = perf_counter()
        try:
            response = requests.post(
                chat_url,
                json=case.input.to_chat_request(model_key).model_dump(mode="json"),
                timeout=timeout_seconds,
            )
            latency_ms = round((perf_counter() - started) * 1_000, 3)
            if response.status_code != 200:
                records.append(
                    CandidateRecord(
                        case_id=case.id,
                        error=_safe_http_error(response),
                        latency_ms=latency_ms,
                    )
                )
                continue
            try:
                chat_response = ChatResponse.model_validate(response.json())
            except (ValueError, ValidationError):
                records.append(
                    CandidateRecord(
                        case_id=case.id,
                        error="invalid_success_response",
                        latency_ms=latency_ms,
                    )
                )
                continue
            if chat_response.model_key != model_key:
                records.append(
                    CandidateRecord(
                        case_id=case.id,
                        error="response_model_key_mismatch",
                        latency_ms=latency_ms,
                    )
                )
                continue
            records.append(
                CandidateRecord(
                    case_id=case.id,
                    response=chat_response,
                    latency_ms=latency_ms,
                )
            )
        except requests.RequestException as exc:
            records.append(
                CandidateRecord(
                    case_id=case.id,
                    error=f"request_failed:{type(exc).__name__}",
                    latency_ms=round((perf_counter() - started) * 1_000, 3),
                )
            )
    return tuple(records)


def _safe_http_error(response: requests.Response) -> str:
    try:
        error = ErrorResponse.model_validate(response.json())
    except (ValueError, ValidationError):
        return f"http_{response.status_code}:invalid_error_response"
    return f"http_{response.status_code}:{error.error.code}"
