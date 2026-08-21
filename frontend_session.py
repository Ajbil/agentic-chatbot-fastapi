from dataclasses import dataclass, field

from api_contract import (
    DEFAULT_SYSTEM_PROMPT,
    MAX_MESSAGES,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ContextUsage,
    GroundingEvidence,
    SearchEvidence,
)


class ConversationStateError(RuntimeError):
    """Raised when the UI attempts an invalid conversation transition."""


@dataclass(frozen=True)
class ConversationSettings:
    """Settings whose meaning must remain stable for one conversation."""

    model_key: str
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    allow_search: bool = False


@dataclass(frozen=True)
class TurnAttempt:
    """The exact user turn and request being sent or retried."""

    user_message: ChatMessage
    request: ChatRequest


@dataclass(frozen=True)
class FailedTurn:
    """A user turn that is visible but not committed to model history."""

    user_message: ChatMessage
    code: str
    message: str
    status_code: int | None = None
    partial_reply: str = ""
    request_id: str | None = None


@dataclass(frozen=True)
class CommittedTurn:
    """One successful exchange and the evidence produced with its answer."""

    user_message: ChatMessage
    assistant_message: ChatMessage
    context: ContextUsage
    search: SearchEvidence
    grounding: GroundingEvidence


@dataclass
class ConversationState:
    """Ephemeral, browser-session-owned conversation state."""

    turns: list[CommittedTurn] = field(default_factory=list)
    settings: ConversationSettings | None = None
    failed_turn: FailedTurn | None = None

    @property
    def messages(self) -> list[ChatMessage]:
        return [
            message
            for turn in self.turns
            for message in (turn.user_message, turn.assistant_message)
        ]

    @property
    def last_context_usage(self) -> ContextUsage | None:
        return self.turns[-1].context if self.turns else None

    @property
    def settings_locked(self) -> bool:
        return self.settings is not None

    @property
    def can_start_turn(self) -> bool:
        return self.failed_turn is None and len(self.messages) + 2 <= MAX_MESSAGES

    @property
    def message_limit_reached(self) -> bool:
        return len(self.messages) + 2 > MAX_MESSAGES

    def begin_turn(
        self,
        content: str,
        settings: ConversationSettings,
    ) -> TurnAttempt:
        if self.failed_turn is not None:
            raise ConversationStateError(
                "Retry or start a new chat before sending another message."
            )
        if self.message_limit_reached:
            raise ConversationStateError(
                "This conversation reached its 50-message limit. Start a new chat."
            )
        if self.settings is not None and settings != self.settings:
            raise ConversationStateError(
                "Conversation settings cannot change after the first turn."
            )

        user_message = ChatMessage(role="user", content=content)
        request = self._build_request(settings, user_message)

        if self.settings is None:
            self.settings = settings

        return TurnAttempt(user_message=user_message, request=request)

    def retry_turn(self) -> TurnAttempt:
        if self.failed_turn is None or self.settings is None:
            raise ConversationStateError("There is no failed turn to retry.")

        user_message = self.failed_turn.user_message
        request = self._build_request(self.settings, user_message)
        return TurnAttempt(user_message=user_message, request=request)

    def commit_turn(self, attempt: TurnAttempt, response: ChatResponse) -> None:
        if response.model_key != attempt.request.model_key:
            raise ConversationStateError(
                "The backend response model does not match the requested model."
            )
        if response.search.allowed != attempt.request.allow_search:
            raise ConversationStateError(
                "The backend search evidence does not match the request permission."
            )

        assistant_message = ChatMessage(role="assistant", content=response.reply)
        self.turns.append(
            CommittedTurn(
                user_message=attempt.user_message,
                assistant_message=assistant_message,
                context=response.context,
                search=response.search,
                grounding=response.grounding,
            )
        )
        self.failed_turn = None

    def record_failure(
        self,
        attempt: TurnAttempt,
        *,
        code: str,
        message: str,
        status_code: int | None = None,
        partial_reply: str = "",
        request_id: str | None = None,
    ) -> None:
        self.failed_turn = FailedTurn(
            user_message=attempt.user_message,
            code=code,
            message=message,
            status_code=status_code,
            partial_reply=partial_reply,
            request_id=request_id,
        )

    def reset(self) -> None:
        self.turns.clear()
        self.settings = None
        self.failed_turn = None

    def _build_request(
        self,
        settings: ConversationSettings,
        user_message: ChatMessage,
    ) -> ChatRequest:
        return ChatRequest(
            model_key=settings.model_key,
            system_prompt=settings.system_prompt,
            messages=[*self.messages, user_message],
            allow_search=settings.allow_search,
        )
