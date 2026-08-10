import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ai_agent import (
    InvalidAgentResponseError,
    MissingConfigurationError,
    get_response_from_ai_agent,
)
from api_contract import (
    ChatRequest,
    ChatResponse,
    ErrorDetail,
    ErrorResponse,
    ValidationIssue,
)
from context_budget import ContextWindowExceededError, plan_context
from model_registry import (
    ModelsResponse,
    UnsupportedModelError,
    get_model_by_key,
    get_models_response,
)


logger = logging.getLogger(__name__)


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
    return JSONResponse(status_code=status_code, content=payload.model_dump(mode="json"))


app = FastAPI(title="Langgraph AI Agent")


@app.exception_handler(ApiContractError)
async def api_contract_error_handler(
    request: Request,
    exc: ApiContractError,
) -> JSONResponse:
    return _error_response(exc.status_code, exc.code, exc.message)


@app.exception_handler(RequestValidationError)
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


@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        "Unhandled error while processing %s %s",
        request.method,
        request.url.path,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    return _error_response(
        500,
        "internal_server_error",
        "An unexpected internal error occurred.",
    )


@app.get("/models", response_model=ModelsResponse)
def models_endpoint():
    """Return the application-owned catalog used by every client."""

    return get_models_response()


@app.post(
    "/chat",
    response_model=ChatResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Unsupported request choice"},
        413: {"model": ErrorResponse, "description": "Context window exceeded"},
        422: {"model": ErrorResponse, "description": "Request validation failed"},
        502: {"model": ErrorResponse, "description": "Invalid upstream response"},
        503: {"model": ErrorResponse, "description": "Service configuration missing"},
        500: {"model": ErrorResponse, "description": "Unexpected internal error"},
    },
)
def chat_endpoint(request: ChatRequest) -> ChatResponse:
    """Run one agent request through the canonical chat contract."""

    try:
        model = get_model_by_key(request.model_key)
    except UnsupportedModelError as exc:
        raise ApiContractError(400, "unsupported_model", str(exc)) from exc

    if request.allow_search and not model.supports_tool_calling:
        raise ApiContractError(
            400,
            "unsupported_capability",
            f"Model '{model.key}' does not support search tools.",
        )

    try:
        context_plan = plan_context(model, request.system_prompt, request.messages)
    except ContextWindowExceededError as exc:
        raise ApiContractError(
            413,
            "context_window_exceeded",
            str(exc),
        ) from exc

    try:
        reply = get_response_from_ai_agent(
            model,
            list(context_plan.messages),
            request.allow_search,
            request.system_prompt,
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

    return ChatResponse(
        model_key=model.key,
        reply=reply,
        context=context_plan.usage,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=3003)
