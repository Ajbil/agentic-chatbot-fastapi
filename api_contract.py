from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


DEFAULT_SYSTEM_PROMPT = "Act as a helpful AI Assistant"
MAX_MESSAGES = 50
MAX_MESSAGE_CHARACTERS = 20_000
MAX_SYSTEM_PROMPT_CHARACTERS = 4_000


class ChatMessage(BaseModel):
    """One canonical message accepted by the chat API."""

    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARACTERS)

    @field_validator("content")
    @classmethod
    def reject_blank_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Message content must not be blank.")
        return value


class ChatRequest(BaseModel):
    """The only request representation supported by POST /chat."""

    model_config = ConfigDict(extra="forbid")

    model_key: str = Field(min_length=1)
    system_prompt: str = Field(
        default=DEFAULT_SYSTEM_PROMPT,
        min_length=1,
        max_length=MAX_SYSTEM_PROMPT_CHARACTERS,
    )
    messages: list[ChatMessage] = Field(min_length=1, max_length=MAX_MESSAGES)
    allow_search: bool = False

    @field_validator("model_key", "system_prompt")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Value must not be blank.")
        return value

    @model_validator(mode="after")
    def require_final_user_message(self):
        if self.messages[-1].role != "user":
            raise ValueError("The final message must have role 'user'.")
        return self


class ChatResponse(BaseModel):
    """A successful response from POST /chat."""

    model_config = ConfigDict(extra="forbid")

    model_key: str
    reply: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARACTERS)


class ValidationIssue(BaseModel):
    """A safe validation detail that never echoes submitted values."""

    model_config = ConfigDict(extra="forbid")

    location: tuple[str | int, ...]
    message: str
    type: str


class ErrorDetail(BaseModel):
    """Machine-readable and human-readable information about one API failure."""

    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    details: tuple[ValidationIssue, ...] = ()


class ErrorResponse(BaseModel):
    """The common envelope for deliberately handled API errors."""

    model_config = ConfigDict(extra="forbid")

    error: ErrorDetail
