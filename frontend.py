import streamlit as st
from pydantic import ValidationError

from api_contract import (
    DEFAULT_SYSTEM_PROMPT,
    MAX_MESSAGE_CHARACTERS,
    MAX_SYSTEM_PROMPT_CHARACTERS,
)
from config import get_settings
from frontend_catalog import ModelCatalogError, fetch_model_catalog, models_for_provider
from frontend_chat import ChatClientError, send_chat
from frontend_session import (
    ConversationSettings,
    ConversationState,
    ConversationStateError,
    TurnAttempt,
)


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
    for message in state.messages:
        with st.chat_message(message.role):
            st.markdown(message.content)


def _send_attempt(
    state: ConversationState,
    attempt: TurnAttempt,
    backend_chat_url: str,
    timeout: float,
) -> None:
    with st.spinner("Waiting for the assistant..."):
        try:
            response = send_chat(backend_chat_url, timeout, attempt.request)
            state.commit_turn(attempt, response.reply)
        except ChatClientError as exc:
            state.record_failure(
                attempt,
                code=exc.code,
                message=str(exc),
                status_code=exc.status_code,
            )
        except ValidationError:
            state.record_failure(
                attempt,
                code="invalid_assistant_message",
                message="The assistant response cannot be added to conversation history.",
            )

    st.rerun()


def _render_failed_turn(
    state: ConversationState,
    backend_chat_url: str,
    timeout: float,
    retry_disabled: bool,
) -> None:
    failed_turn = state.failed_turn
    if failed_turn is None:
        return

    with st.chat_message("user"):
        st.markdown(failed_turn.user_message.content)
        st.caption("Not added to conversation history because the request failed.")

    st.error(failed_turn.message)
    status_suffix = (
        f" · HTTP {failed_turn.status_code}"
        if failed_turn.status_code is not None
        else ""
    )
    st.caption(f"Error code: {failed_turn.code}{status_suffix}")

    if st.button(
        "Retry",
        type="primary",
        icon=":material/refresh:",
        disabled=retry_disabled,
    ):
        _send_attempt(
            state,
            state.retry_turn(),
            backend_chat_url,
            timeout,
        )


def _render_locked_settings(state, catalog, models_by_key):
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


def _render_editable_settings(catalog, models_by_key):
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


def main():
    settings = get_settings()
    state = _conversation_state()

    st.set_page_config(page_title="Agentic Chatbot", layout="centered")
    st.title("Agentic Chatbot")
    st.caption("Session-scoped conversation history with Groq, OpenAI, and optional web search.")

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
    _render_failed_turn(
        state,
        settings.backend_chat_url,
        settings.backend_request_timeout_seconds,
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
                settings.backend_chat_url,
                settings.backend_request_timeout_seconds,
            )


if __name__ == "__main__":
    main()
