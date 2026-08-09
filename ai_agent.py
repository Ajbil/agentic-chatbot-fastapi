from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage
from langchain_groq import ChatGroq
from langchain_tavily import TavilySearch
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from api_contract import MAX_MESSAGE_CHARACTERS, ChatMessage
from config import Settings, get_settings
from model_registry import ModelSpec, Provider


class MissingConfigurationError(RuntimeError):
    """Raised when a requested feature is missing required configuration."""


class InvalidAgentResponseError(RuntimeError):
    """Raised when the agent completes without a usable assistant response."""


def _require_secret(secret: SecretStr | None, variable_name: str) -> str:
    if secret is None or not secret.get_secret_value().strip():
        raise MissingConfigurationError(
            f"{variable_name} is required for this request. Add it to your .env file or environment."
        )

    return secret.get_secret_value()


def _convert_messages_to_langchain(messages: list[ChatMessage]):
    langchain_messages = []
    for message in messages:
        if message.role == "user":
            langchain_messages.append(HumanMessage(content=message.content))
        else:
            langchain_messages.append(AIMessage(content=message.content))

    return langchain_messages


def get_response_from_ai_agent(
    model: ModelSpec,
    messages: list[ChatMessage],
    allow_search: bool,
    system_prompt: str,
    settings: Settings | None = None,
) -> str:
    app_settings = settings or get_settings()

    if model.provider == Provider.GROQ:
        provider_api_key = _require_secret(app_settings.groq_api_key, "GROQ_API_KEY")
    elif model.provider == Provider.OPENAI:
        provider_api_key = _require_secret(
            app_settings.openai_api_key,
            "OPENAI_API_KEY",
        )
    else:
        raise ValueError(f"Unsupported provider: {model.provider}")

    tavily_api_key = None
    if allow_search:
        tavily_api_key = _require_secret(app_settings.tavily_api_key, "TAVILY_API_KEY")

    if model.provider == Provider.GROQ:
        llm = ChatGroq(
            model=model.model_id,
            groq_api_key=provider_api_key,
            max_tokens=model.max_output_tokens,
        )
    else:
        llm = ChatOpenAI(
            model=model.model_id,
            api_key=provider_api_key,
            max_completion_tokens=model.max_output_tokens,
        )

    tools = (
        [TavilySearch(max_results=2, api_key=tavily_api_key)]
        if tavily_api_key is not None
        else []
    )

    agent = create_agent(
        model=llm,
        tools=tools,
        system_prompt=system_prompt,
    )

    state = {"messages": _convert_messages_to_langchain(messages)}
    response = agent.invoke(state)
    messages = response.get("messages", [])
    ai_messages = [msg for msg in messages if isinstance(msg, AIMessage)]

    if ai_messages:
        latest_message = ai_messages[-1]
        if isinstance(latest_message.content, str) and latest_message.content.strip():
            if len(latest_message.content) > MAX_MESSAGE_CHARACTERS:
                raise InvalidAgentResponseError(
                    "The model provider returned an assistant message that exceeds "
                    f"the {MAX_MESSAGE_CHARACTERS}-character conversation limit."
                )
            return latest_message.content

    raise InvalidAgentResponseError(
        "The model provider did not return a usable assistant message."
    )
