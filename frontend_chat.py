import requests
from pydantic import ValidationError

from api_contract import ChatRequest, ChatResponse, ErrorResponse


class ChatClientError(RuntimeError):
    """Raised when the frontend cannot obtain a valid chat response."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "chat_request_failed",
        status_code: int | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def send_chat(url: str, timeout: float, request: ChatRequest) -> ChatResponse:
    """Send one canonical request and validate either response contract."""

    try:
        response = requests.post(
            url,
            json=request.model_dump(mode="json"),
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise ChatClientError(f"The backend chat request failed: {exc}") from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise ChatClientError(
            "The backend returned malformed JSON.",
            status_code=response.status_code,
        ) from exc

    if response.status_code == 200:
        try:
            return ChatResponse.model_validate(payload)
        except ValidationError as exc:
            raise ChatClientError(
                "The backend returned an invalid success response.",
                status_code=response.status_code,
            ) from exc

    try:
        error_response = ErrorResponse.model_validate(payload)
    except ValidationError as exc:
        raise ChatClientError(
            "The backend returned an invalid error response.",
            status_code=response.status_code,
        ) from exc

    raise ChatClientError(
        error_response.error.message,
        code=error_response.error.code,
        status_code=response.status_code,
    )
