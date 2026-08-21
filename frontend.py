from collections.abc import Iterator

import streamlit as st
from pydantic import ValidationError

from api_contract import (
    DEFAULT_SYSTEM_PROMPT,
    MAX_MESSAGE_CHARACTERS,
    MAX_SYSTEM_PROMPT_CHARACTERS,
    ChatResponse,
    GroundingEvidence,
    SearchEvidence,
    StreamCompleteEvent,
    StreamDeltaEvent,
    StreamStatusEvent,
)
from config import get_settings
from frontend_catalog import ModelCatalogError, fetch_model_catalog, models_for_provider
from frontend_chat import ChatClientError, stream_chat
from frontend_session import (
    ConversationSettings,
    ConversationState,
    ConversationStateError,
    TurnAttempt,
)
from model_registry import ModelSpec, ModelsResponse

SESSION_STATE_KEY = "conversation_state"
WIDGET_STATE_KEYS = (
    "selected_provider",
    "selected_model_key",
    "system_prompt",
    "allow_web_search",
)


def _conversation_state() -> ConversationState:
    state = st.session_state.get(SESSION_STATE_KEY)
    if not isinstance(state, ConversationState):
        state = ConversationState()
        st.session_state[SESSION_STATE_KEY] = state
    return state


def _new_chat() -> None:
    st.session_state[SESSION_STATE_KEY] = ConversationState()
    for key in WIDGET_STATE_KEYS:
        st.session_state.pop(key, None)


def _render_history(state: ConversationState) -> None:
    for turn_index, turn in enumerate(state.turns, start=1):
        with st.chat_message("user"):
            st.markdown(turn.user_message.content)
        with st.chat_message("assistant"):
            st.markdown(turn.assistant_message.content)
            _render_search_evidence(turn.search, turn.grounding, turn_index)


def _render_search_evidence(
    evidence: SearchEvidence,
    grounding: GroundingEvidence,
    turn_index: int,
) -> None:
    if not evidence.allowed:
        return
    if not evidence.attempted:
        st.caption("Web search was available but not used for this answer.")
        return

    successful = [item for item in evidence.executions if item.status == "succeeded"]
    failed_count = len(evidence.executions) - len(successful)

    if successful:
        with st.expander("Web sources"):
            for execution_index, execution in enumerate(successful, start=1):
                st.caption(f"Search {execution_index}: {execution.query}")
                for source_index, source in enumerate(execution.sources, start=1):
                    st.link_button(
                        f"[{source.source_id}] {source.title}",
                        str(source.url),
                        key=f"source-{turn_index}-{execution_index}-{source_index}",
                    )
                    if source.snippet:
                        st.text(source.snippet)

    if failed_count:
        if successful:
            st.warning(
                f"{failed_count} additional web search attempt(s) returned no "
                "usable evidence."
            )
        else:
            st.warning("Web search was attempted but returned no usable evidence.")

    if grounding.status == "cited":
        cited = ", ".join(f"[{source_id}]" for source_id in grounding.cited_source_ids)
        st.caption(
            f"Validated source references: {cited}. This confirms reference "
            "integrity, not that each source semantically proves every claim."
        )
        if grounding.repair_attempted:
            st.caption(
                "The assistant corrected invalid citations once before delivery."
            )


def _render_context_usage(state: ConversationState) -> None:
    usage = state.last_context_usage
    if usage is None:
        return

    st.caption(
        "Latest model input estimate: "
        f"{usage.estimated_sent_input_tokens:,} / {usage.input_budget_tokens:,} "
        "tokens "
        f"(output reserve: {usage.reserved_output_tokens:,}; "
        f"safety margin: {usage.safety_margin_tokens:,})."
    )
    if usage.was_truncated:
        st.warning(
            f"For the latest answer, the backend omitted "
            f"{usage.omitted_message_count} older message(s) from the model input. "
            "The full transcript remains visible in this browser session."
        )


def _send_attempt(
    state: ConversationState,
    attempt: TurnAttempt,
    backend_chat_stream_url: str,
    connect_timeout: float,
    read_timeout: float,
) -> None:
    stage_labels = {
        "model_running": "Contacting the model...",
        "search_running": "Searching the web...",
        "search_results_received": "Processing retrieved sources...",
        "finalizing": "Finalizing the answer...",
    }
    completed_response: ChatResponse | None = None
    with st.chat_message("assistant"):
        status_placeholder = st.empty()

        def answer_fragments() -> Iterator[str]:
            nonlocal completed_response
            for event in stream_chat(
                backend_chat_stream_url,
                connect_timeout,
                read_timeout,
                attempt.request,
            ):
                if isinstance(event, StreamStatusEvent):
                    status_placeholder.caption(stage_labels[event.stage])
                elif isinstance(event, StreamDeltaEvent):
                    yield event.text
                elif isinstance(event, StreamCompleteEvent):
                    completed_response = event.response

        try:
            st.write_stream(answer_fragments())
            status_placeholder.empty()
            if completed_response is None:
                raise ChatClientError(
                    "The backend stream ended without a completed response.",
                    code="invalid_stream_response",
                )
            state.commit_turn(attempt, completed_response)
        except ChatClientError as exc:
            status_placeholder.empty()
            state.record_failure(
                attempt,
                code=exc.code,
                message=str(exc),
                status_code=exc.status_code,
                partial_reply=exc.partial_reply,
                request_id=exc.request_id,
            )
        except (ValidationError, ConversationStateError):
            state.record_failure(
                attempt,
                code="invalid_backend_response",
                message="The backend response cannot be added to conversation history.",
            )

    st.rerun()


def _render_failed_turn(
    state: ConversationState,
    backend_chat_stream_url: str,
    connect_timeout: float,
    read_timeout: float,
    retry_disabled: bool,
) -> None:
    failed_turn = state.failed_turn
    if failed_turn is None:
        return

    with st.chat_message("user"):
        st.markdown(failed_turn.user_message.content)
        st.caption("Not added to conversation history because the request failed.")

    if failed_turn.partial_reply:
        with st.chat_message("assistant"):
            st.markdown(failed_turn.partial_reply)
            st.warning("Incomplete response — not added to conversation history.")

    st.error(failed_turn.message)
    status_suffix = (
        f" · HTTP {failed_turn.status_code}"
        if failed_turn.status_code is not None
        else ""
    )
    st.caption(f"Error code: {failed_turn.code}{status_suffix}")
    if failed_turn.request_id is not None:
        st.caption(f"Request reference: {failed_turn.request_id}")

    if st.button(
        "Retry",
        type="primary",
        icon=":material/refresh:",
        disabled=retry_disabled,
    ):
        _send_attempt(
            state,
            state.retry_turn(),
            backend_chat_stream_url,
            connect_timeout,
            read_timeout,
        )


def _render_locked_settings(
    state: ConversationState,
    catalog: ModelsResponse,
    models_by_key: dict[str, ModelSpec],
) -> ConversationSettings | None:
    locked_settings = state.settings
    if locked_settings is None:
        raise ConversationStateError("Locked settings are unavailable.")

    selected_model = models_by_key.get(locked_settings.model_key)
    if selected_model is None:
        st.sidebar.error(
            "This conversation's model is no longer in the backend catalog. "
            "Start a new chat to choose another model."
        )
        return None

    providers = list(dict.fromkeys(model.provider.value for model in catalog.models))
    provider_models = models_for_provider(catalog, selected_model.provider.value)
    provider_model_keys = [model.key for model in provider_models]

    st.sidebar.radio(
        "Provider",
        providers,
        index=providers.index(selected_model.provider.value),
        format_func=str.title,
        key="selected_provider",
        disabled=True,
    )
    st.sidebar.selectbox(
        "Model",
        provider_model_keys,
        index=provider_model_keys.index(selected_model.key),
        format_func=lambda key: models_by_key[key].display_name,
        key="selected_model_key",
        disabled=True,
    )
    st.sidebar.text_area(
        "System prompt",
        value=locked_settings.system_prompt,
        max_chars=MAX_SYSTEM_PROMPT_CHARACTERS,
        key="system_prompt",
        disabled=True,
    )
    st.sidebar.checkbox(
        "Allow Web Search",
        value=locked_settings.allow_search,
        key="allow_web_search",
        disabled=True,
    )
    st.sidebar.caption("Start a new chat to change conversation settings.")
    return locked_settings


def _render_editable_settings(
    catalog: ModelsResponse,
    models_by_key: dict[str, ModelSpec],
) -> ConversationSettings:
    default_model = models_by_key[catalog.default_model_key]
    providers = list(dict.fromkeys(model.provider.value for model in catalog.models))

    selected_provider = st.sidebar.radio(
        "Provider",
        providers,
        index=providers.index(default_model.provider.value),
        format_func=str.title,
        key="selected_provider",
    )
    provider_models = models_for_provider(catalog, selected_provider)
    provider_model_keys = [model.key for model in provider_models]
    default_index = (
        provider_model_keys.index(default_model.key)
        if default_model.key in provider_model_keys
        else 0
    )
    selected_model_key = st.sidebar.selectbox(
        "Model",
        provider_model_keys,
        index=default_index,
        format_func=lambda key: models_by_key[key].display_name,
        key="selected_model_key",
    )
    selected_model = models_by_key[selected_model_key]
    system_prompt = st.sidebar.text_area(
        "System prompt",
        value=DEFAULT_SYSTEM_PROMPT,
        max_chars=MAX_SYSTEM_PROMPT_CHARACTERS,
        key="system_prompt",
    )
    allow_web_search = st.sidebar.checkbox(
        "Allow Web Search",
        disabled=not selected_model.supports_tool_calling,
        help=(
            None
            if selected_model.supports_tool_calling
            else "This model does not support the tool calling required for search."
        ),
        key="allow_web_search",
    )

    return ConversationSettings(
        model_key=selected_model.key,
        system_prompt=system_prompt,
        allow_search=(
            allow_web_search if selected_model.supports_tool_calling else False
        ),
    )


def main() -> None:
    settings = get_settings()
    state = _conversation_state()

    st.set_page_config(page_title="Agentic Chatbot", layout="centered")
    st.title("Agentic Chatbot")
    st.caption(
        "Session-scoped conversation history with Groq, OpenAI, and optional web search."
    )

    st.sidebar.header("Conversation settings")
    st.sidebar.button(
        "New chat",
        on_click=_new_chat,
        icon=":material/add_comment:",
        use_container_width=True,
    )

    catalog = None
    catalog_error = None
    try:
        catalog = fetch_model_catalog(
            settings.backend_models_url,
            settings.backend_request_timeout_seconds,
        )
    except ModelCatalogError as exc:
        catalog_error = exc

    if catalog is not None:
        models_by_key = {model.key: model for model in catalog.models}
        if state.settings_locked:
            conversation_settings = _render_locked_settings(
                state,
                catalog,
                models_by_key,
            )
        else:
            conversation_settings = _render_editable_settings(
                catalog,
                models_by_key,
            )
    else:
        conversation_settings = state.settings
        st.sidebar.error("Could not load supported models from the backend.")
        st.sidebar.caption(str(catalog_error))

    catalog_available = catalog is not None and conversation_settings is not None

    _render_history(state)
    _render_context_usage(state)
    _render_failed_turn(
        state,
        settings.backend_chat_stream_url,
        settings.backend_request_timeout_seconds,
        settings.backend_stream_read_timeout_seconds,
        retry_disabled=not catalog_available,
    )

    if state.message_limit_reached:
        st.warning(
            "This conversation reached its 50-message limit. Start a new chat "
            "to continue; messages are not removed automatically."
        )

    input_disabled = (
        not catalog_available
        or state.failed_turn is not None
        or state.message_limit_reached
    )
    if not catalog_available:
        input_placeholder = "Backend model catalog unavailable"
    elif state.failed_turn is not None:
        input_placeholder = "Retry the failed turn or start a new chat"
    elif state.message_limit_reached:
        input_placeholder = "Message limit reached — start a new chat"
    else:
        input_placeholder = "Ask a follow-up question"

    user_query = st.chat_input(
        input_placeholder,
        max_chars=MAX_MESSAGE_CHARACTERS,
        disabled=input_disabled,
    )

    if user_query and conversation_settings is not None:
        try:
            attempt = state.begin_turn(user_query, conversation_settings)
        except (ConversationStateError, ValidationError) as exc:
            st.error(str(exc))
        else:
            with st.chat_message("user"):
                st.markdown(attempt.user_message.content)
            _send_attempt(
                state,
                attempt,
                settings.backend_chat_stream_url,
                settings.backend_request_timeout_seconds,
                settings.backend_stream_read_timeout_seconds,
            )


if __name__ == "__main__":
    main()
