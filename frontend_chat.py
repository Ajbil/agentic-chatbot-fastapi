from collections.abc import Iterator

import requests
from pydantic import ValidationError

from api_contract import (
    CHAT_STREAM_EVENT_ADAPTER,
    ChatRequest,
    ChatResponse,
    ChatStreamEvent,
    ErrorResponse,
    StreamCompleteEvent,
    StreamDeltaEvent,
    StreamErrorEvent,
    StreamStartedEvent,
)


class ChatClientError(RuntimeError):
    """Raised when the frontend cannot obtain a valid chat response."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "chat_request_failed",
        status_code: int | None = None,
        partial_reply: str = "",
    ):
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.partial_reply = partial_reply


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


def stream_chat(
    url: str,
    connect_timeout: float,
    read_timeout: float,
    request: ChatRequest,
) -> Iterator[ChatStreamEvent]:
    """Yield validated chat events while enforcing the public stream protocol."""

    try:
        response = requests.post(
            url,
            json=request.model_dump(mode="json"),
            stream=True,
            timeout=(connect_timeout, read_timeout),
        )
    except requests.RequestException as exc:
        raise ChatClientError(f"The backend chat request failed: {exc}") from exc

    assembled_reply = ""
    expected_sequence = 1
    started = False
    terminal = False
    try:
        if response.status_code != 200:
            try:
                error_response = ErrorResponse.model_validate(response.json())
            except (ValueError, ValidationError) as exc:
                raise ChatClientError(
                    "The backend returned an invalid error response.",
                    status_code=response.status_code,
                ) from exc
            raise ChatClientError(
                error_response.error.message,
                code=error_response.error.code,
                status_code=response.status_code,
            )

        try:
            lines = response.iter_lines(decode_unicode=True)
            for line in lines:
                if not line:
                    continue
                if terminal:
                    raise ChatClientError(
                        "The backend stream continued after its terminal event.",
                        code="invalid_stream_response",
                        partial_reply=assembled_reply,
                    )
                try:
                    event = CHAT_STREAM_EVENT_ADAPTER.validate_json(line)
                except (ValueError, ValidationError) as exc:
                    raise ChatClientError(
                        "The backend returned an invalid stream event.",
                        code="invalid_stream_response",
                        partial_reply=assembled_reply,
                    ) from exc
                if event.sequence != expected_sequence:
                    raise ChatClientError(
                        "The backend stream contained an invalid event sequence.",
                        code="invalid_stream_response",
                        partial_reply=assembled_reply,
                    )
                expected_sequence += 1

                if not started:
                    if not isinstance(event, StreamStartedEvent):
                        raise ChatClientError(
                            "The backend stream did not begin with a started event.",
                            code="invalid_stream_response",
                        )
                    if event.model_key != request.model_key:
                        raise ChatClientError(
                            "The backend stream started with the wrong model.",
                            code="invalid_stream_response",
                        )
                    started = True
                elif isinstance(event, StreamStartedEvent):
                    raise ChatClientError(
                        "The backend stream contained more than one started event.",
                        code="invalid_stream_response",
                        partial_reply=assembled_reply,
                    )

                if isinstance(event, StreamDeltaEvent):
                    assembled_reply += event.text
                elif isinstance(event, StreamCompleteEvent):
                    if event.response.reply != assembled_reply:
                        raise ChatClientError(
                            "The streamed answer did not match the completed response.",
                            code="invalid_stream_response",
                            partial_reply=assembled_reply,
                        )
                    terminal = True
                elif isinstance(event, StreamErrorEvent):
                    terminal = True
                if isinstance(event, StreamErrorEvent):
                    raise ChatClientError(
                        event.error.message,
                        code=event.error.code,
                        partial_reply=assembled_reply,
                    )
                yield event
        except requests.RequestException as exc:
            raise ChatClientError(
                f"The backend chat stream failed: {exc}",
                partial_reply=assembled_reply,
            ) from exc

        if terminal:
            return
        raise ChatClientError(
            "The backend stream ended before a terminal event.",
            code="invalid_stream_response",
            partial_reply=assembled_reply,
        )
    finally:
        response.close()
