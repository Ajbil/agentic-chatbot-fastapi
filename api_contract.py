import re
from typing import Annotated, Literal, Self

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_validator,
    model_validator,
)

DEFAULT_SYSTEM_PROMPT = "Act as a helpful AI Assistant"
MAX_MESSAGES = 50
MAX_MESSAGE_CHARACTERS = 20_000
MAX_SYSTEM_PROMPT_CHARACTERS = 4_000
MAX_SEARCH_EXECUTIONS = 3
MAX_SEARCH_QUERY_CHARACTERS = 500
MAX_SOURCE_TITLE_CHARACTERS = 300
MAX_SOURCE_SNIPPET_CHARACTERS = 1_000
MAX_UNIQUE_SEARCH_SOURCES = 6
SOURCE_ID_PATTERN = r"^S[1-6]$"
CITATION_MARKER_PATTERN = re.compile(r"\[(S[0-9]+)\]")


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
    def require_canonical_turn_order(self) -> Self:
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
    def require_internally_consistent_evidence(self) -> Self:
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


class SearchSource(BaseModel):
    """One untrusted web result returned by the configured search provider."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str = Field(pattern=SOURCE_ID_PATTERN)
    title: str = Field(min_length=1, max_length=MAX_SOURCE_TITLE_CHARACTERS)
    url: AnyHttpUrl
    snippet: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_SOURCE_SNIPPET_CHARACTERS,
    )

    @field_validator("title", "snippet")
    @classmethod
    def reject_blank_source_text(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Source text must not be blank.")
        return value.strip() if value is not None else None


class SearchExecution(BaseModel):
    """One model-requested web search and its normalized result evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    query: str = Field(min_length=1, max_length=MAX_SEARCH_QUERY_CHARACTERS)
    status: Literal["succeeded", "failed"]
    sources: tuple[SearchSource, ...] = Field(default=(), max_length=2)

    @field_validator("query")
    @classmethod
    def reject_blank_query(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Search query must not be blank.")
        return value.strip()

    @model_validator(mode="after")
    def require_sources_only_for_success(self) -> Self:
        if self.status == "succeeded" and not self.sources:
            raise ValueError("A successful search must contain at least one source.")
        if self.status == "failed" and self.sources:
            raise ValueError("A failed search must not contain sources.")
        return self


class SearchEvidence(BaseModel):
    """Auditable search permission, execution, and retrieval evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    allowed: bool
    attempted: bool
    executions: tuple[SearchExecution, ...] = Field(
        default=(),
        max_length=MAX_SEARCH_EXECUTIONS,
    )

    @model_validator(mode="after")
    def require_consistent_search_state(self) -> Self:
        if self.attempted != bool(self.executions):
            raise ValueError("Search attempted must match whether executions exist.")
        if not self.allowed and self.attempted:
            raise ValueError("Search cannot be attempted when it was not allowed.")

        urls_by_id: dict[str, str] = {}
        ids_by_url: dict[str, str] = {}
        for execution in self.executions:
            for source in execution.sources:
                normalized_url = str(source.url)
                previous_url = urls_by_id.setdefault(source.source_id, normalized_url)
                previous_id = ids_by_url.setdefault(normalized_url, source.source_id)
                if previous_url != normalized_url or previous_id != source.source_id:
                    raise ValueError(
                        "Search source identifiers must map one-to-one with URLs."
                    )
        return self


class GroundingEvidence(BaseModel):
    """Deterministic citation-reference evidence for one assistant answer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["not_applicable", "unavailable", "cited"]
    cited_source_ids: tuple[str, ...] = Field(
        default=(),
        max_length=MAX_UNIQUE_SEARCH_SOURCES,
    )
    repair_attempted: bool = False

    @field_validator("cited_source_ids")
    @classmethod
    def require_valid_unique_source_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("Cited source identifiers must be unique.")
        for source_id in value:
            if re.fullmatch(SOURCE_ID_PATTERN, source_id) is None:
                raise ValueError("A cited source identifier is invalid.")
        return value


class ChatResponse(BaseModel):
    """A successful response from POST /chat."""

    model_config = ConfigDict(extra="forbid")

    model_key: str
    reply: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARACTERS)
    context: ContextUsage
    search: SearchEvidence
    grounding: GroundingEvidence

    @model_validator(mode="after")
    def require_consistent_grounding_evidence(self) -> Self:
        available_source_ids = {
            source.source_id
            for execution in self.search.executions
            if execution.status == "succeeded"
            for source in execution.sources
        }
        markers = CITATION_MARKER_PATTERN.findall(self.reply)
        cited_in_order = tuple(dict.fromkeys(markers))

        if self.grounding.cited_source_ids != cited_in_order:
            raise ValueError(
                "Grounding evidence must match inline citation markers in order."
            )
        if not set(cited_in_order).issubset(available_source_ids):
            raise ValueError("The answer cites a source that was not retrieved.")

        expected_status: Literal["not_applicable", "unavailable", "cited"]
        if available_source_ids:
            expected_status = "cited"
        elif self.search.attempted:
            expected_status = "unavailable"
        else:
            expected_status = "not_applicable"
        if self.grounding.status != expected_status:
            raise ValueError("Grounding status does not match the search evidence.")
        if expected_status == "cited" and not cited_in_order:
            raise ValueError(
                "An answer based on retrieved evidence must cite a source."
            )
        if expected_status != "cited" and cited_in_order:
            raise ValueError("An answer cannot cite unavailable search evidence.")
        return self


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


class _StreamEvent(BaseModel):
    """Fields shared by every version-one chat stream event."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[1] = 1
    sequence: int = Field(gt=0)


class StreamStartedEvent(_StreamEvent):
    type: Literal["started"] = "started"
    model_key: str = Field(min_length=1)


class StreamStatusEvent(_StreamEvent):
    type: Literal["status"] = "status"
    stage: Literal[
        "model_running",
        "search_running",
        "search_results_received",
        "finalizing",
    ]


class StreamDeltaEvent(_StreamEvent):
    type: Literal["delta"] = "delta"
    text: str = Field(min_length=1)


class StreamCompleteEvent(_StreamEvent):
    type: Literal["complete"] = "complete"
    response: ChatResponse


class StreamErrorEvent(_StreamEvent):
    type: Literal["error"] = "error"
    error: ErrorDetail


ChatStreamEvent = Annotated[
    StreamStartedEvent
    | StreamStatusEvent
    | StreamDeltaEvent
    | StreamCompleteEvent
    | StreamErrorEvent,
    Field(discriminator="type"),
]
CHAT_STREAM_EVENT_ADAPTER: TypeAdapter[ChatStreamEvent] = TypeAdapter(ChatStreamEvent)
