import json
import logging
import sys
from collections.abc import Callable, Mapping, MutableMapping
from contextvars import ContextVar, Token
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from traceback import extract_tb
from typing import Any, Literal
from uuid import uuid4

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

from api_contract import ChatResponse

REQUEST_ID_HEADER = "X-Request-ID"
UNKNOWN_MODEL_KEY = "unknown"

KNOWN_CHAT_OUTCOMES = frozenset(
    {
        "success",
        "unsupported_model",
        "unsupported_capability",
        "context_window_exceeded",
        "service_configuration_error",
        "invalid_upstream_response",
        "agent_tool_limit_exceeded",
        "upstream_stream_failed",
        "internal_server_error",
        "client_disconnect",
    }
)

EXCLUDED_HTTP_METRIC_ROUTES = frozenset({"/metrics", "/docs", "/openapi.json"})
KNOWN_HTTP_METHODS = frozenset(
    {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"}
)
SAFE_LOG_FIELDS = frozenset(
    {
        "method",
        "route",
        "status_code",
        "response_completed",
        "duration_ms",
        "exception_type",
        "traceback_frames",
        "transport",
        "model_key",
        "outcome",
        "search_allowed",
        "search_attempted",
        "successful_searches",
        "failed_searches",
        "grounding_status",
        "repair_attempted",
        "context_truncated",
        "omitted_message_count",
    }
)
HTTP_DURATION_BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120)
TOKEN_BUCKETS = (128, 512, 2_048, 8_192, 32_768, 65_536, 131_072)

_request_id_context: ContextVar[str | None] = ContextVar(
    "request_id",
    default=None,
)


def _safe_request_id(value: Any) -> str | None:
    if not isinstance(value, str) or len(value) != 32:
        return None
    return (
        value if all(character in "0123456789abcdef" for character in value) else None
    )


def new_request_id() -> str:
    """Return an opaque correlation identifier that contains no user input."""

    return uuid4().hex


def bind_request_id(request_id: str) -> Token[str | None]:
    return _request_id_context.set(request_id)


def reset_request_id(token: Token[str | None]) -> None:
    _request_id_context.reset(token)


def current_request_id() -> str | None:
    return _request_id_context.get()


class JsonLogFormatter(logging.Formatter):
    """Serialize application-owned operational fields as one JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": getattr(record, "event", "unstructured_log"),
        }
        request_id = _safe_request_id(
            getattr(record, "request_id", None) or current_request_id()
        )
        if request_id is not None:
            payload["request_id"] = request_id
        fields = getattr(record, "event_fields", {})
        if isinstance(fields, Mapping):
            payload.update(
                {key: value for key, value in fields.items() if key in SAFE_LOG_FIELDS}
            )
        return json.dumps(payload, separators=(",", ":"), sort_keys=True)


class ConsoleLogFormatter(logging.Formatter):
    """Render the same safe fields in a locally readable representation."""

    def format(self, record: logging.LogRecord) -> str:
        request_id = _safe_request_id(
            getattr(record, "request_id", None) or current_request_id()
        )
        fields = getattr(record, "event_fields", {})
        field_text = " ".join(
            f"{key}={value!r}"
            for key, value in sorted(fields.items())
            if key in SAFE_LOG_FIELDS
        )
        parts = [record.levelname, getattr(record, "event", "unstructured_log")]
        if request_id is not None:
            parts.append(f"request_id={request_id}")
        if field_text:
            parts.append(field_text)
        return " ".join(parts)


def configure_logging(
    level: str,
    log_format: Literal["json", "console"],
    *,
    stream: Any = None,
    logger: logging.Logger | None = None,
) -> logging.Logger:
    """Configure only this application's logger, leaving host logging intact."""

    logger = logger or logging.getLogger("agentic_chatbot")
    logger.handlers.clear()
    handler = logging.StreamHandler(stream if stream is not None else sys.stderr)
    handler.setFormatter(
        JsonLogFormatter() if log_format == "json" else ConsoleLogFormatter()
    )
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    return logger


def _safe_traceback_frames(exc: BaseException) -> list[dict[str, Any]]:
    return [
        {
            "file": Path(frame.filename).name,
            "function": frame.name,
            "line": frame.lineno,
        }
        for frame in extract_tb(exc.__traceback__)[-8:]
    ]


class OperationalTelemetry:
    """Own privacy-safe logs and bounded in-process Prometheus metrics."""

    def __init__(
        self,
        *,
        registry: CollectorRegistry | None = None,
        logger: logging.Logger | None = None,
        clock: Callable[[], float] = perf_counter,
    ):
        self.registry = registry or CollectorRegistry()
        self.logger = logger or logging.getLogger("agentic_chatbot")
        self.clock = clock
        self.http_requests = Counter(
            "agentic_chatbot_http_requests_total",
            "Completed HTTP requests.",
            ("method", "route", "status_class"),
            registry=self.registry,
        )
        self.http_duration = Histogram(
            "agentic_chatbot_http_request_duration_seconds",
            "End-to-end HTTP response duration, including streamed bodies.",
            ("method", "route"),
            buckets=HTTP_DURATION_BUCKETS,
            registry=self.registry,
        )
        self.chat_runs = Counter(
            "agentic_chatbot_chat_runs_total",
            "Terminal outcomes for validated chat requests.",
            ("transport", "model_key", "outcome"),
            registry=self.registry,
        )
        self.chat_duration = Histogram(
            "agentic_chatbot_chat_run_duration_seconds",
            "End-to-end validated chat operation duration.",
            ("transport", "model_key", "outcome"),
            buckets=HTTP_DURATION_BUCKETS,
            registry=self.registry,
        )
        self.active_streams = Gauge(
            "agentic_chatbot_active_streams",
            "Validated chat streams that have not reached a terminal outcome.",
            registry=self.registry,
        )
        self.first_delta_duration = Histogram(
            "agentic_chatbot_stream_time_to_first_delta_seconds",
            "Time from validated stream start to the first answer delta.",
            ("model_key",),
            buckets=HTTP_DURATION_BUCKETS,
            registry=self.registry,
        )
        self.search_executions = Counter(
            "agentic_chatbot_search_executions_total",
            "Normalized search executions returned by chat runs.",
            ("model_key", "status"),
            registry=self.registry,
        )
        self.grounding_results = Counter(
            "agentic_chatbot_grounding_results_total",
            "Terminal grounding contract outcomes.",
            ("model_key", "status", "repair_attempted"),
            registry=self.registry,
        )
        self.context_input_tokens = Histogram(
            "agentic_chatbot_context_input_tokens",
            "Estimated model input tokens sent for successful chat runs.",
            ("model_key", "truncated"),
            buckets=TOKEN_BUCKETS,
            registry=self.registry,
        )

    def render_metrics(self) -> bytes:
        return generate_latest(self.registry)

    def log_event(
        self,
        level: int,
        event: str,
        *,
        request_id: str | None = None,
        **fields: Any,
    ) -> None:
        self.logger.log(
            level,
            event,
            extra={
                "event": event,
                "request_id": request_id,
                "event_fields": fields,
            },
        )

    def log_unexpected_exception(
        self,
        event: str,
        exc: BaseException,
        *,
        request_id: str | None = None,
        **fields: Any,
    ) -> None:
        self.log_event(
            logging.ERROR,
            event,
            request_id=request_id,
            exception_type=type(exc).__name__,
            traceback_frames=_safe_traceback_frames(exc),
            **fields,
        )

    def observe_http(
        self,
        *,
        method: str,
        route: str,
        status_code: int,
        duration_seconds: float,
        request_id: str,
        response_completed: bool,
    ) -> None:
        status_class = (
            f"{status_code // 100}xx"
            if response_completed and 100 <= status_code <= 599
            else "aborted"
            if not response_completed
            else "other"
        )
        method = safe_method(method)
        if route not in EXCLUDED_HTTP_METRIC_ROUTES:
            self.http_requests.labels(method, route, status_class).inc()
            self.http_duration.labels(method, route).observe(duration_seconds)
        self.log_event(
            logging.INFO,
            "http_request_completed",
            request_id=request_id,
            method=method,
            route=route,
            status_code=status_code,
            response_completed=response_completed,
            duration_ms=round(duration_seconds * 1_000, 3),
        )

    def start_chat(self, transport: Literal["sync", "stream"]) -> "ChatRunTracker":
        return ChatRunTracker(
            telemetry=self,
            transport=transport,
            request_id=current_request_id(),
            started_at=self.clock(),
        )


@dataclass
class ChatRunTracker:
    """Finalize one validated chat operation exactly once."""

    telemetry: OperationalTelemetry
    transport: Literal["sync", "stream"]
    request_id: str | None
    started_at: float
    model_key: str = UNKNOWN_MODEL_KEY
    finished: bool = False
    first_delta_recorded: bool = False
    stream_opened: bool = False

    def set_model_key(self, model_key: str) -> None:
        self.model_key = model_key

    def open_stream(self) -> None:
        if not self.stream_opened:
            self.telemetry.active_streams.inc()
            self.stream_opened = True

    def first_delta(self) -> None:
        if self.transport == "stream" and not self.first_delta_recorded:
            self.telemetry.first_delta_duration.labels(self.model_key).observe(
                max(0.0, self.telemetry.clock() - self.started_at)
            )
            self.first_delta_recorded = True

    def succeed(self, response: ChatResponse) -> None:
        if self.finished:
            return
        for execution in response.search.executions:
            self.telemetry.search_executions.labels(
                self.model_key,
                execution.status,
            ).inc()
        self.telemetry.grounding_results.labels(
            self.model_key,
            response.grounding.status,
            _bool_label(response.grounding.repair_attempted),
        ).inc()
        self.telemetry.context_input_tokens.labels(
            self.model_key,
            _bool_label(response.context.was_truncated),
        ).observe(response.context.estimated_sent_input_tokens)
        successful_searches = sum(
            execution.status == "succeeded" for execution in response.search.executions
        )
        self._finish(
            "success",
            logging.INFO,
            search_allowed=response.search.allowed,
            search_attempted=response.search.attempted,
            successful_searches=successful_searches,
            failed_searches=len(response.search.executions) - successful_searches,
            grounding_status=response.grounding.status,
            repair_attempted=response.grounding.repair_attempted,
            context_truncated=response.context.was_truncated,
            omitted_message_count=response.context.omitted_message_count,
        )

    def fail(self, outcome: str) -> None:
        safe_outcome = (
            outcome if outcome in KNOWN_CHAT_OUTCOMES else "internal_server_error"
        )
        level = (
            logging.WARNING
            if safe_outcome != "internal_server_error"
            else logging.ERROR
        )
        self._finish(safe_outcome, level)

    def _finish(self, outcome: str, level: int, **fields: Any) -> None:
        if self.finished:
            return
        duration = max(0.0, self.telemetry.clock() - self.started_at)
        self.telemetry.chat_runs.labels(
            self.transport,
            self.model_key,
            outcome,
        ).inc()
        self.telemetry.chat_duration.labels(
            self.transport,
            self.model_key,
            outcome,
        ).observe(duration)
        self.telemetry.log_event(
            level,
            "chat_run_completed" if outcome == "success" else "chat_run_failed",
            request_id=self.request_id,
            transport=self.transport,
            model_key=self.model_key,
            outcome=outcome,
            duration_ms=round(duration * 1_000, 3),
            **fields,
        )
        if self.stream_opened:
            self.telemetry.active_streams.dec()
            self.stream_opened = False
        self.finished = True


def _bool_label(value: bool) -> str:
    return "true" if value else "false"


class RequestObservabilityMiddleware:
    """Correlate and measure the complete ASGI HTTP response lifecycle."""

    def __init__(self, app: Any, telemetry: OperationalTelemetry):
        self.app = app
        self.telemetry = telemetry

    async def __call__(
        self,
        scope: MutableMapping[str, Any],
        receive: Callable[..., Any],
        send: Callable[..., Any],
    ) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        request_id = new_request_id()
        scope.setdefault("state", {})["request_id"] = request_id
        token = bind_request_id(request_id)
        started_at = self.telemetry.clock()
        status_code = 500
        completed = False

        async def send_with_observability(message: MutableMapping[str, Any]) -> None:
            nonlocal status_code, completed
            if message.get("type") == "http.response.start":
                status_code = int(message.get("status", 500))
                headers = list(message.get("headers", []))
                headers.append(
                    (
                        REQUEST_ID_HEADER.lower().encode("ascii"),
                        request_id.encode("ascii"),
                    )
                )
                message["headers"] = headers
            if message.get("type") == "http.response.body" and not message.get(
                "more_body", False
            ):
                await send(message)
                completed = True
                self._finish_http(
                    scope,
                    status_code,
                    started_at,
                    request_id,
                    response_completed=True,
                )
                return
            await send(message)

        try:
            await self.app(scope, receive, send_with_observability)
        finally:
            if not completed:
                self._finish_http(
                    scope,
                    status_code,
                    started_at,
                    request_id,
                    response_completed=False,
                )
            reset_request_id(token)

    def _finish_http(
        self,
        scope: Mapping[str, Any],
        status_code: int,
        started_at: float,
        request_id: str,
        response_completed: bool,
    ) -> None:
        self.telemetry.observe_http(
            method=str(scope.get("method", "UNKNOWN")),
            route=safe_route(scope),
            status_code=status_code,
            duration_seconds=max(0.0, self.telemetry.clock() - started_at),
            request_id=request_id,
            response_completed=response_completed,
        )


def safe_route(scope: Mapping[str, Any]) -> str:
    """Return a bounded route template rather than a user-controlled raw path."""

    route = getattr(scope.get("route"), "path", None)
    return route if isinstance(route, str) else "unmatched"


def safe_method(method: str) -> str:
    """Bound HTTP method cardinality before logging or labeling it."""

    normalized = method.upper()
    return normalized if normalized in KNOWN_HTTP_METHODS else "OTHER"
