import streamlit as st
from pydantic import ValidationError

from api_contract import ChatMessage, ChatRequest
from config import get_settings
from frontend_catalog import ModelCatalogError, fetch_model_catalog, models_for_provider
from frontend_chat import ChatClientError, send_chat


def main():
    settings = get_settings()

    st.set_page_config(page_title="LangGraph Agent UI", layout="centered")
    st.title("AI Chatbot Agents")
    st.write("Create and Interact with the AI Agents!")

    try:
        catalog = fetch_model_catalog(
            settings.backend_models_url,
            settings.backend_request_timeout_seconds,
        )
    except ModelCatalogError as exc:
        st.error("Could not load supported models from the backend.")
        st.caption(str(exc))
        st.stop()

    models_by_key = {model.key: model for model in catalog.models}
    default_model = models_by_key[catalog.default_model_key]
    providers = list(dict.fromkeys(model.provider.value for model in catalog.models))

    system_prompt = st.text_area(
        "Define the type of AI Agent you need like general, financial, educational, etc..  ",
        height=70,
        placeholder="Type your system prompt here...",
    )

    selected_provider = st.radio(
        "Select Provider:",
        providers,
        index=providers.index(default_model.provider.value),
        format_func=str.title,
    )

    provider_models = models_for_provider(catalog, selected_provider)
    provider_model_keys = [model.key for model in provider_models]
    default_index = (
        provider_model_keys.index(default_model.key)
        if default_model.key in provider_model_keys
        else 0
    )
    selected_model_key = st.selectbox(
        "Select Model:",
        provider_model_keys,
        index=default_index,
        format_func=lambda key: models_by_key[key].display_name,
    )
    selected_model = models_by_key[selected_model_key]

    allow_web_search = st.checkbox(
        "Allow Web Search",
        disabled=not selected_model.supports_tool_calling,
        help=(
            None
            if selected_model.supports_tool_calling
            else "This model does not support the tool calling required for search."
        ),
    )

    user_query = st.text_area(
        "Enter your query: ",
        height=150,
        placeholder="Ask Anything!",
    )

    if st.button("Ask Agent!") and user_query.strip():
        request_values = {
            "model_key": selected_model.key,
            "messages": [ChatMessage(role="user", content=user_query)],
            "allow_search": allow_web_search,
        }
        if system_prompt.strip():
            request_values["system_prompt"] = system_prompt

        try:
            chat_request = ChatRequest.model_validate(request_values)
            chat_response = send_chat(
                settings.backend_chat_url,
                settings.backend_request_timeout_seconds,
                chat_request,
            )
        except ValidationError as exc:
            st.error("The chat request is invalid.")
            st.caption(str(exc))
        except ChatClientError as exc:
            st.error(str(exc))
            st.caption(f"Error code: {exc.code}")
        else:
            st.subheader("Agent Response")
            st.markdown(chat_response.reply)


if __name__ == "__main__":
    main()
