from collections.abc import Iterator
from typing import Literal, cast

from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response, StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST
from starlette.types import ExceptionHandler

from ai_agent import (
    AgentOutcome,
    AgentToolLimitExceededError,
    InvalidAgentResponseError,
    MissingConfigurationError,
    get_response_from_ai_agent,
    prepare_agent_run,
    stream_prepared_agent,
)
from api_contract import (
    ChatRequest,
    ChatResponse,
    ChatStreamEvent,
    ErrorDetail,
    ErrorResponse,
    StreamCompleteEvent,
    StreamDeltaEvent,
    StreamErrorEvent,
    StreamStartedEvent,
    StreamStatusEvent,
    ValidationIssue,
)
from config import get_settings
from context_budget import ContextWindowExceededError, plan_context
from model_registry import (
    ModelsResponse,
    UnsupportedModelError,
    get_model_by_key,
    get_models_response,
)
from observability import (
    REQUEST_ID_HEADER,
    ChatRunTracker,
    OperationalTelemetry,
    RequestObservabilityMiddleware,
    configure_logging,
    safe_route,
)

REQUEST_ID_RESPONSE_HEADERS = {
    REQUEST_ID_HEADER: {
        "description": "Opaque server-generated request correlation identifier.",
        "schema": {"type": "string", "pattern": "^[0-9a-f]{32}$"},
    }
}


class ApiContractError(RuntimeError):
    """A deliberately exposed API failure with stable HTTP semantics."""

    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _error_response(
    status_code: int,
    code: str,
    message: str,
    details: tuple[ValidationIssue, ...] = (),
) -> JSONResponse:
    payload = ErrorResponse(
        error=ErrorDetail(code=code, message=message, details=details)
    )
    return JSONResponse(
        status_code=status_code, content=payload.model_dump(mode="json")
    )


router = APIRouter()


def _telemetry(request: Request) -> OperationalTelemetry:
    return cast(OperationalTelemetry, request.app.state.telemetry)


def _chat_tracker(request: Request) -> ChatRunTracker | None:
    tracker = getattr(request.state, "chat_tracker", None)
    return tracker if isinstance(tracker, ChatRunTracker) else None


def _fail_chat_tracker(request: Request, outcome: str) -> None:
    tracker = _chat_tracker(request)
    if tracker is not None:
        tracker.fail(outcome)


async def api_contract_error_handler(
    request: Request,
    exc: ApiContractError,
) -> JSONResponse:
    _fail_chat_tracker(request, exc.code)
    return _error_response(exc.status_code, exc.code, exc.message)


async def request_validation_error_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    details = tuple(
        ValidationIssue(
            location=tuple(error["loc"]),
            message=error["msg"],
            type=error["type"],
        )
        for error in exc.errors()
    )
    return _error_response(
        422,
        "request_validation_error",
        "The request body is invalid.",
        details,
    )


async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    _fail_chat_tracker(request, "internal_server_error")
    _telemetry(request).log_unexpected_exception(
        "unexpected_request_error",
        exc,
        method=request.method,
        route=safe_route(request.scope),
    )
    return _error_response(
        500,
        "internal_server_error",
        "An unexpected internal error occurred.",
    )


@router.get(
    "/models",
    response_model=ModelsResponse,
    responses={200: {"headers": REQUEST_ID_RESPONSE_HEADERS}},
)
def models_endpoint() -> ModelsResponse:
    """Return the application-owned catalog used by every client."""

    return get_models_response()


@router.post(
    "/chat",
    response_model=ChatResponse,
    responses={
        200: {"headers": REQUEST_ID_RESPONSE_HEADERS},
        400: {
            "model": ErrorResponse,
            "description": "Unsupported request choice",
            "headers": REQUEST_ID_RESPONSE_HEADERS,
        },
        413: {
            "model": ErrorResponse,
            "description": "Context window exceeded",
            "headers": REQUEST_ID_RESPONSE_HEADERS,
        },
        422: {
            "model": ErrorResponse,
            "description": "Request validation failed",
            "headers": REQUEST_ID_RESPONSE_HEADERS,
        },
        502: {
            "model": ErrorResponse,
            "description": "Invalid upstream response",
            "headers": REQUEST_ID_RESPONSE_HEADERS,
        },
        503: {
            "model": ErrorResponse,
            "description": "Service configuration missing",
            "headers": REQUEST_ID_RESPONSE_HEADERS,
        },
        500: {
            "model": ErrorResponse,
            "description": "Unexpected internal error",
            "headers": REQUEST_ID_RESPONSE_HEADERS,
        },
    },
)
def chat_endpoint(payload: ChatRequest, request: Request) -> ChatResponse:
    """Run one agent request through the canonical chat contract."""

    tracker = _telemetry(request).start_chat("sync")
    request.state.chat_tracker = tracker

    try:
        model = get_model_by_key(payload.model_key)
    except UnsupportedModelError as exc:
        raise ApiContractError(400, "unsupported_model", str(exc)) from exc

    tracker.set_model_key(model.key)

    if payload.allow_search and not model.supports_tool_calling:
        raise ApiContractError(
            400,
            "unsupported_capability",
            f"Model '{model.key}' does not support search tools.",
        )

    try:
        context_plan = plan_context(model, payload.system_prompt, payload.messages)
    except ContextWindowExceededError as exc:
        raise ApiContractError(
            413,
            "context_window_exceeded",
            str(exc),
        ) from exc

    try:
        agent_outcome = get_response_from_ai_agent(
            model,
            list(context_plan.messages),
            payload.allow_search,
            payload.system_prompt,
        )
    except MissingConfigurationError as exc:
        raise ApiContractError(
            503,
            "service_configuration_error",
            str(exc),
        ) from exc
    except InvalidAgentResponseError as exc:
        raise ApiContractError(
            502,
            "invalid_upstream_response",
            str(exc),
        ) from exc
    except AgentToolLimitExceededError as exc:
        raise ApiContractError(
            502,
            "agent_tool_limit_exceeded",
            str(exc),
        ) from exc

    response = ChatResponse(
        model_key=model.key,
        reply=agent_outcome.reply,
        context=context_plan.usage,
        search=agent_outcome.search,
        grounding=agent_outcome.grounding,
    )
    tracker.succeed(response)
    return response


def _serialize_stream_event(event: ChatStreamEvent) -> bytes:
    return (event.model_dump_json() + "\n").encode("utf-8")


def _runtime_error_detail(
    exc: Exception,
    telemetry: OperationalTelemetry,
    request_id: str | None,
) -> ErrorDetail:
    if isinstance(exc, AgentToolLimitExceededError):
        return ErrorDetail(code="agent_tool_limit_exceeded", message=str(exc))
    if isinstance(exc, InvalidAgentResponseError):
        return ErrorDetail(code="invalid_upstream_response", message=str(exc))
    telemetry.log_unexpected_exception(
        "unexpected_stream_error",
        exc,
        request_id=request_id,
    )
    return ErrorDetail(
        code="upstream_stream_failed",
        message="The assistant stream failed before it completed.",
    )


@router.post(
    "/chat/stream",
    responses={
        200: {
            "description": "Versioned NDJSON chat event stream",
            "content": {"application/x-ndjson": {"schema": {"type": "string"}}},
            "headers": REQUEST_ID_RESPONSE_HEADERS,
        },
        400: {"model": ErrorResponse, "headers": REQUEST_ID_RESPONSE_HEADERS},
        413: {"model": ErrorResponse, "headers": REQUEST_ID_RESPONSE_HEADERS},
        422: {"model": ErrorResponse, "headers": REQUEST_ID_RESPONSE_HEADERS},
        503: {"model": ErrorResponse, "headers": REQUEST_ID_RESPONSE_HEADERS},
    },
)
def chat_stream_endpoint(payload: ChatRequest, request: Request) -> StreamingResponse:
    """Stream safe progress and answer events for one canonical chat request."""

    telemetry = _telemetry(request)
    tracker = telemetry.start_chat("stream")
    request.state.chat_tracker = tracker

    try:
        model = get_model_by_key(payload.model_key)
    except UnsupportedModelError as exc:
        raise ApiContractError(400, "unsupported_model", str(exc)) from exc
    tracker.set_model_key(model.key)

    if payload.allow_search and not model.supports_tool_calling:
        raise ApiContractError(
            400,
            "unsupported_capability",
            f"Model '{model.key}' does not support search tools.",
        )
    try:
        context_plan = plan_context(model, payload.system_prompt, payload.messages)
    except ContextWindowExceededError as exc:
        raise ApiContractError(413, "context_window_exceeded", str(exc)) from exc
    try:
        prepared = prepare_agent_run(
            model,
            list(context_plan.messages),
            payload.allow_search,
            payload.system_prompt,
        )
    except MissingConfigurationError as exc:
        raise ApiContractError(503, "service_configuration_error", str(exc)) from exc

    def event_bytes() -> Iterator[bytes]:
        sequence = 1
        assembled_reply = ""
        tracker.open_stream()
        try:
            yield _serialize_stream_event(
                StreamStartedEvent(sequence=sequence, model_key=model.key)
            )
            for agent_event in stream_prepared_agent(prepared):
                if agent_event.type == "status":
                    if not isinstance(agent_event.value, str):
                        raise InvalidAgentResponseError(
                            "The agent emitted an invalid status event."
                        )
                    sequence += 1
                    yield _serialize_stream_event(
                        StreamStatusEvent(
                            sequence=sequence,
                            stage=cast(
                                Literal[
                                    "model_running",
                                    "search_running",
                                    "search_results_received",
                                    "finalizing",
                                ],
                                agent_event.value,
                            ),
                        )
                    )
                elif agent_event.type == "delta":
                    if not isinstance(agent_event.value, str):
                        raise InvalidAgentResponseError(
                            "The agent emitted an invalid delta event."
                        )
                    sequence += 1
                    assembled_reply += agent_event.value
                    tracker.first_delta()
                    yield _serialize_stream_event(
                        StreamDeltaEvent(sequence=sequence, text=agent_event.value)
                    )
                else:
                    if not isinstance(agent_event.value, AgentOutcome):
                        raise InvalidAgentResponseError(
                            "The agent emitted an invalid completion event."
                        )
                    outcome = agent_event.value
                    if not assembled_reply:
                        sequence += 1
                        assembled_reply = outcome.reply
                        tracker.first_delta()
                        yield _serialize_stream_event(
                            StreamDeltaEvent(sequence=sequence, text=outcome.reply)
                        )
                    elif assembled_reply != outcome.reply:
                        raise InvalidAgentResponseError(
                            "The streamed assistant text did not match the final response."
                        )
                    response = ChatResponse(
                        model_key=model.key,
                        reply=outcome.reply,
                        context=context_plan.usage,
                        search=outcome.search,
                        grounding=outcome.grounding,
                    )
                    sequence += 1
                    tracker.succeed(response)
                    yield _serialize_stream_event(
                        StreamCompleteEvent(sequence=sequence, response=response)
                    )
                    return
            raise InvalidAgentResponseError(
                "The agent stream ended without a completed response."
            )
        except Exception as exc:
            detail = _runtime_error_detail(exc, telemetry, tracker.request_id)
            tracker.fail(detail.code)
            sequence += 1
            yield _serialize_stream_event(
                StreamErrorEvent(sequence=sequence, error=detail)
            )
        finally:
            if not tracker.finished:
                tracker.fail("client_disconnect")

    return StreamingResponse(event_bytes(), media_type="application/x-ndjson")


@router.get(
    "/metrics",
    include_in_schema=False,
)
def metrics_endpoint(request: Request) -> Response:
    """Expose process-local Prometheus metrics for an external scraper."""

    return Response(
        content=_telemetry(request).render_metrics(),
        headers={"Content-Type": CONTENT_TYPE_LATEST},
    )


def create_app(telemetry: OperationalTelemetry | None = None) -> FastAPI:
    """Construct an application with injectable process-local telemetry."""

    application = FastAPI(title="Langgraph AI Agent")
    application.state.telemetry = telemetry or OperationalTelemetry()
    application.add_middleware(
        RequestObservabilityMiddleware,
        telemetry=application.state.telemetry,
    )
    application.add_exception_handler(
        ApiContractError,
        cast(ExceptionHandler, api_contract_error_handler),
    )
    application.add_exception_handler(
        RequestValidationError,
        cast(ExceptionHandler, request_validation_error_handler),
    )
    application.add_exception_handler(Exception, unexpected_error_handler)
    application.include_router(router)
    return application


_settings = get_settings()
_application_logger = configure_logging(
    _settings.app_log_level,
    _settings.app_log_format,
)
app = create_app(OperationalTelemetry(logger=_application_logger))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=3003)
