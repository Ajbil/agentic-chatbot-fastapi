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
    def require_canonical_turn_order(self):
        for index, message in enumerate(self.messages):
            expected_role = "user" if index % 2 == 0 else "assistant"
            if message.role != expected_role:
                raise ValueError(
                    "Messages must start with 'user', alternate between 'user' "
                    "and 'assistant', and end with 'user'."
                )
        if self.messages[-1].role != "user":
            raise ValueError(
                "Messages must start with 'user', alternate between 'user' "
                "and 'assistant', and end with 'user'."
            )
        return self


class ContextUsage(BaseModel):
    """Estimated context-budget evidence for one successful chat request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    estimation_method: Literal["langchain_approximate_v1"]
    context_window_tokens: int = Field(gt=0)
    reserved_output_tokens: int = Field(gt=0)
    safety_margin_tokens: int = Field(gt=0)
    input_budget_tokens: int = Field(gt=0)
    estimated_full_input_tokens: int = Field(gt=0)
    estimated_sent_input_tokens: int = Field(gt=0)
    original_message_count: int = Field(gt=0)
    included_message_count: int = Field(gt=0)
    omitted_message_count: int = Field(ge=0)
    was_truncated: bool

    @model_validator(mode="after")
    def require_internally_consistent_evidence(self):
        if self.input_budget_tokens != (
            self.context_window_tokens
            - self.reserved_output_tokens
            - self.safety_margin_tokens
        ):
            raise ValueError("Input budget does not match its model reservations.")
        if self.included_message_count + self.omitted_message_count != (
            self.original_message_count
        ):
            raise ValueError("Message counts do not reconcile.")
        if self.was_truncated != (self.omitted_message_count > 0):
            raise ValueError("Truncation flag does not match the omitted count.")
        if self.estimated_sent_input_tokens > self.input_budget_tokens:
            raise ValueError("Sent input estimate exceeds the input budget.")
        if self.estimated_sent_input_tokens > self.estimated_full_input_tokens:
            raise ValueError("Sent input estimate exceeds the full input estimate.")
        return self


class ChatResponse(BaseModel):
    """A successful response from POST /chat."""

    model_config = ConfigDict(extra="forbid")

    model_key: str
    reply: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARACTERS)
    context: ContextUsage


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
