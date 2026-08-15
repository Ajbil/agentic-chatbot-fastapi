from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from api_contract import ChatMessage, ChatRequest, ChatResponse

EvaluationCategory = Literal[
    "static_no_search",
    "search_required",
    "search_optional",
    "uncertainty",
    "instruction_resilience",
    "multi_turn",
    "conflicting_evidence",
]
SearchPolicy = Literal["forbidden", "required", "optional"]
CheckSeverity = Literal["hard", "advisory"]
EvaluationMode = Literal["replay", "live"]


class EvaluationInput(BaseModel):
    """Model-independent request fields shared by replay and live evaluation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    system_prompt: str = Field(min_length=1, max_length=4_000)
    messages: tuple[ChatMessage, ...] = Field(min_length=1, max_length=50)
    allow_search: bool

    @model_validator(mode="after")
    def validate_canonical_messages(self) -> Self:
        ChatRequest(
            model_key="evaluation-placeholder",
            system_prompt=self.system_prompt,
            messages=list(self.messages),
            allow_search=self.allow_search,
        )
        return self

    def to_chat_request(self, model_key: str) -> ChatRequest:
        return ChatRequest(
            model_key=model_key,
            system_prompt=self.system_prompt,
            messages=list(self.messages),
            allow_search=self.allow_search,
        )


class EvaluationExpectations(BaseModel):
    """Deterministic properties expected from one nondeterministic answer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    search_policy: SearchPolicy
    min_successful_searches: int = Field(default=0, ge=0, le=3)
    min_unique_sources: int = Field(default=0, ge=0, le=6)
    required_concepts: tuple[tuple[str, ...], ...] = ()
    forbidden_phrases: tuple[str, ...] = ()
    min_reply_characters: int = Field(default=20, ge=1, le=20_000)

    @field_validator("required_concepts")
    @classmethod
    def validate_concept_groups(
        cls,
        groups: tuple[tuple[str, ...], ...],
    ) -> tuple[tuple[str, ...], ...]:
        if any(not group for group in groups):
            raise ValueError("Required-concept groups must not be empty.")
        for group in groups:
            if any(not phrase.strip() for phrase in group):
                raise ValueError("Required concepts must not be blank.")
        return groups

    @field_validator("forbidden_phrases")
    @classmethod
    def validate_forbidden_phrases(
        cls,
        phrases: tuple[str, ...],
    ) -> tuple[str, ...]:
        if any(not phrase.strip() for phrase in phrases):
            raise ValueError("Forbidden phrases must not be blank.")
        return phrases


class EvaluationCase(BaseModel):
    """One versioned evaluation example and its expected properties."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,63}$")
    category: EvaluationCategory
    description: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    input: EvaluationInput
    expectations: EvaluationExpectations

    @model_validator(mode="after")
    def validate_search_expectations(self) -> Self:
        policy = self.expectations.search_policy
        if policy == "forbidden" and self.input.allow_search:
            raise ValueError("Forbidden-search cases must disable search permission.")
        if policy != "forbidden" and not self.input.allow_search:
            raise ValueError("Required or optional search cases must permit search.")
        if policy == "required" and self.expectations.min_successful_searches < 1:
            raise ValueError(
                "Required-search cases need at least one successful search."
            )
        if policy != "required" and (
            self.expectations.min_successful_searches > 0
            or self.expectations.min_unique_sources > 0
        ):
            raise ValueError(
                "Only required-search cases may require searches or sources."
            )
        return self


class EvaluationDataset(BaseModel):
    """A complete, versioned set of evaluation cases."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    dataset_version: str = Field(pattern=r"^v[1-9][0-9]*$")
    cases: tuple[EvaluationCase, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def require_unique_case_ids(self) -> Self:
        case_ids = [case.id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("Evaluation case IDs must be unique.")
        return self


class CandidateRecord(BaseModel):
    """One captured candidate response or safe execution failure."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    response: ChatResponse | None = None
    error: str | None = Field(default=None, min_length=1, max_length=500)
    latency_ms: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def require_one_outcome(self) -> Self:
        if (self.response is None) == (self.error is None):
            raise ValueError("A candidate must contain exactly one response or error.")
        return self


class EvaluationCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    severity: CheckSeverity
    passed: bool
    evidence: str


class EvaluationCaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    category: EvaluationCategory
    hard_checks_passed: bool
    checks: tuple[EvaluationCheck, ...]
    latency_ms: float | None = None


class EvaluationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    total_cases: int
    hard_passed_cases: int
    hard_pass_rate: float
    advisory_checks_passed: int
    advisory_checks_total: int
    advisory_pass_rate: float
    search_required_cases: int
    search_required_attempted: int
    search_required_attempt_rate: float
    optional_search_cases: int
    optional_search_avoided: int
    optional_search_avoidance_rate: float
    provenance_required_cases: int
    provenance_satisfied: int
    provenance_success_rate: float
    execution_failures: int


class EvaluationTarget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: EvaluationMode
    model_key: str
    git_commit: str | None = None
    generated_at_utc: str | None = None


class EvaluationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    dataset_version: str
    target: EvaluationTarget
    summary: EvaluationSummary
    cases: tuple[EvaluationCaseResult, ...]
