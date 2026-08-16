import json
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Protocol, TypedDict, cast

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    AnyMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI
from langchain_tavily import TavilySearch
from langchain_tavily._utilities import TavilySearchAPIWrapper
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
)

from api_contract import (
    MAX_MESSAGE_CHARACTERS,
    MAX_SEARCH_QUERY_CHARACTERS,
    MAX_SOURCE_SNIPPET_CHARACTERS,
    MAX_SOURCE_TITLE_CHARACTERS,
    ChatMessage,
    SearchEvidence,
    SearchExecution,
    SearchSource,
)
from config import Settings, get_settings
from model_registry import ModelSpec, Provider

MAX_SEARCH_CALLS = 3


class MissingConfigurationError(RuntimeError):
    """Raised when a requested feature is missing required configuration."""


class InvalidAgentResponseError(RuntimeError):
    """Raised when the agent completes without a usable assistant response."""


class AgentToolLimitExceededError(RuntimeError):
    """Raised when one agent request exceeds its bounded tool-call allowance."""


class AgentGraphState(TypedDict):
    """Request-scoped workflow state with reducer-owned message accumulation."""

    messages: Annotated[list[AnyMessage], add_messages]


class AgentRunner(Protocol):
    """The small compiled-graph surface owned by this application."""

    def invoke(self, state: AgentGraphState) -> dict[str, Any]: ...

    def stream(
        self,
        state: AgentGraphState,
        *,
        stream_mode: list[str],
        version: str,
    ) -> Iterator[dict[str, Any]]: ...


class SearchInput(BaseModel):
    """The only search argument the model may control in this checkpoint."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=MAX_SEARCH_QUERY_CHARACTERS)

    @field_validator("query")
    @classmethod
    def _normalize_query(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Search query must not be blank.")
        return value.strip()


@dataclass(frozen=True)
class AgentOutcome:
    """The final assistant text and auditable evidence from one agent run."""

    reply: str
    search: SearchEvidence


@dataclass(frozen=True)
class AgentStreamEvent:
    """One application-owned update from a streaming agent execution."""

    type: Literal["status", "delta", "complete"]
    value: str | AgentOutcome


@dataclass(frozen=True)
class PreparedAgentRun:
    """An eagerly validated agent and its canonical input state."""

    agent: AgentRunner
    state: AgentGraphState
    allow_search: bool


def _require_secret(secret: SecretStr | None, variable_name: str) -> SecretStr:
    if secret is None or not secret.get_secret_value().strip():
        raise MissingConfigurationError(
            f"{variable_name} is required for this request. "
            "Add it to your .env file or environment."
        )

    return secret


def _convert_messages_to_langchain(messages: list[ChatMessage]) -> list[AnyMessage]:
    langchain_messages: list[AnyMessage] = []
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
) -> AgentOutcome:
    prepared = prepare_agent_run(
        model,
        messages,
        allow_search,
        system_prompt,
        settings,
    )
    response = prepared.agent.invoke(prepared.state)

    return _outcome_from_messages(response.get("messages", []), allow_search)


def prepare_agent_run(
    model: ModelSpec,
    messages: list[ChatMessage],
    allow_search: bool,
    system_prompt: str,
    settings: Settings | None = None,
) -> PreparedAgentRun:
    """Validate credentials and construct an agent before HTTP streaming starts."""

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
        llm: BaseChatModel = ChatGroq(
            model=model.model_id,
            api_key=provider_api_key,
            max_tokens=model.max_output_tokens,
        )
    else:
        llm = ChatOpenAI(
            model=model.model_id,
            api_key=provider_api_key,
            max_completion_tokens=model.max_output_tokens,
        )

    tools: list[BaseTool] = (
        [
            TavilySearch(
                max_results=2,
                search_depth="basic",
                topic="general",
                auto_parameters=False,
                include_answer=False,
                include_raw_content=False,
                include_images=False,
                args_schema=SearchInput,
                handle_tool_error=True,
                api_wrapper=TavilySearchAPIWrapper.model_validate(
                    {"tavily_api_key": tavily_api_key.get_secret_value()}
                ),
            )
        ]
        if tavily_api_key is not None
        else []
    )
    agent = _build_agent_graph(llm, tools, system_prompt)

    return PreparedAgentRun(
        agent=agent,
        state={"messages": _convert_messages_to_langchain(messages)},
        allow_search=allow_search,
    )


def _build_agent_graph(
    model: BaseChatModel,
    tools: Sequence[BaseTool],
    system_prompt: str,
) -> AgentRunner:
    """Compile the application-owned model/tool workflow for one request."""

    allowed_tools = {tool.name for tool in tools}
    model_runner = cast(
        Runnable[Any, BaseMessage],
        model.bind_tools(list(tools)) if tools else model,
    )

    def call_model(state: AgentGraphState) -> dict[str, list[AnyMessage]]:
        response = model_runner.invoke(
            [SystemMessage(content=system_prompt), *state["messages"]]
        )
        if not isinstance(response, AIMessage):
            raise InvalidAgentResponseError(
                "The model provider did not return an assistant message."
            )
        return {"messages": [response]}

    def route_after_model(
        state: AgentGraphState,
    ) -> Literal["validate_tool_calls", "__end__"]:
        latest = _latest_ai_message(state)
        if not latest.tool_calls:
            return "__end__"
        if not allowed_tools:
            raise InvalidAgentResponseError(
                "The model requested a tool when tools were not enabled."
            )
        return "validate_tool_calls"

    def validate_tool_calls(state: AgentGraphState) -> dict[str, list[AnyMessage]]:
        calls = [
            tool_call
            for message in state["messages"]
            if isinstance(message, AIMessage)
            for tool_call in message.tool_calls
        ]
        if len(calls) > MAX_SEARCH_CALLS:
            raise AgentToolLimitExceededError(
                "The agent exceeded the maximum of three web searches for one request."
            )

        seen_ids: set[str] = set()
        for tool_call in calls:
            tool_name = tool_call.get("name")
            if tool_name not in allowed_tools:
                raise InvalidAgentResponseError(
                    "The model requested an unsupported tool."
                )
            tool_call_id = tool_call.get("id")
            if (
                not isinstance(tool_call_id, str)
                or not tool_call_id.strip()
                or tool_call_id in seen_ids
            ):
                raise InvalidAgentResponseError(
                    "The model returned inconsistent tool-call identifiers."
                )
            seen_ids.add(tool_call_id)
            try:
                SearchInput.model_validate(tool_call.get("args"))
            except ValidationError as exc:
                raise InvalidAgentResponseError(
                    "The model returned invalid web-search arguments."
                ) from exc
        return {}

    builder = StateGraph(AgentGraphState)
    builder.add_node("model", call_model)
    builder.add_node("validate_tool_calls", validate_tool_calls)
    builder.add_edge(START, "model")
    builder.add_conditional_edges(
        "model",
        route_after_model,
        {"validate_tool_calls": "validate_tool_calls", END: END},
    )

    if tools:
        builder.add_node(
            "tools",
            ToolNode(list(tools), handle_tool_errors="Search execution failed."),
        )
        builder.add_edge("validate_tool_calls", "tools")
        builder.add_edge("tools", "model")
    else:
        builder.add_edge("validate_tool_calls", END)

    return cast(AgentRunner, builder.compile())


def _latest_ai_message(state: AgentGraphState) -> AIMessage:
    if not state["messages"] or not isinstance(state["messages"][-1], AIMessage):
        raise InvalidAgentResponseError(
            "The workflow did not end its model node with an assistant message."
        )
    return state["messages"][-1]


def stream_prepared_agent(
    prepared: PreparedAgentRun,
) -> Iterator[AgentStreamEvent]:
    """Translate LangGraph v2 events into safe application-level updates."""

    yield AgentStreamEvent("status", "model_running")
    response_messages: list[BaseMessage] = []
    buffered_text: list[str] = []
    raw_stream = None

    try:
        raw_stream = prepared.agent.stream(
            prepared.state,
            stream_mode=["messages", "updates"],
            version="v2",
        )
        for part in raw_stream:
            part_type = part.get("type")
            data = part.get("data")

            if part_type == "messages" and isinstance(data, tuple):
                chunk = data[0]
                if (
                    isinstance(chunk, AIMessageChunk)
                    and isinstance(chunk.content, str)
                    and chunk.content
                ):
                    buffered_text.append(chunk.content)
                continue

            if part_type != "updates" or not isinstance(data, dict):
                continue

            for node_name, update in data.items():
                if not isinstance(update, dict):
                    continue
                messages = update.get("messages", [])
                if not isinstance(messages, (list, tuple)):
                    continue
                response_messages.extend(messages)

                if node_name == "tools":
                    yield AgentStreamEvent("status", "search_results_received")
                    yield AgentStreamEvent("status", "model_running")
                    continue

                ai_messages = [item for item in messages if isinstance(item, AIMessage)]
                if not ai_messages:
                    continue
                latest = ai_messages[-1]
                if latest.tool_calls:
                    buffered_text.clear()
                    yield AgentStreamEvent("status", "search_running")
                else:
                    for text in buffered_text:
                        yield AgentStreamEvent("delta", text)
                    buffered_text.clear()
    finally:
        close_stream = getattr(raw_stream, "close", None)
        if callable(close_stream):
            close_stream()

    yield AgentStreamEvent("status", "finalizing")
    outcome = _outcome_from_messages(response_messages, prepared.allow_search)
    yield AgentStreamEvent("complete", outcome)


def _outcome_from_messages(
    response_messages: Sequence[BaseMessage],
    allow_search: bool,
) -> AgentOutcome:
    ai_messages = [msg for msg in response_messages if isinstance(msg, AIMessage)]

    if ai_messages:
        latest_message = ai_messages[-1]
        if isinstance(latest_message.content, str) and latest_message.content.strip():
            if len(latest_message.content) > MAX_MESSAGE_CHARACTERS:
                raise InvalidAgentResponseError(
                    "The model provider returned an assistant message that exceeds "
                    f"the {MAX_MESSAGE_CHARACTERS}-character conversation limit."
                )
            return AgentOutcome(
                reply=latest_message.content,
                search=_extract_search_evidence(response_messages, allow_search),
            )

    raise InvalidAgentResponseError(
        "The model provider did not return a usable assistant message."
    )


def _extract_search_evidence(
    messages: Sequence[BaseMessage],
    allowed: bool,
) -> SearchEvidence:
    tool_calls_by_id: dict[str, str] = {}
    executions: list[SearchExecution] = []

    for message in messages:
        if isinstance(message, AIMessage):
            for tool_call in message.tool_calls:
                if tool_call.get("name") != "tavily_search":
                    continue
                tool_call_id = tool_call.get("id")
                query = tool_call.get("args", {}).get("query")
                try:
                    validated_query = SearchInput.model_validate({"query": query}).query
                except ValidationError as exc:
                    raise InvalidAgentResponseError(
                        "The agent returned an invalid web-search query."
                    ) from exc
                if not tool_call_id or tool_call_id in tool_calls_by_id:
                    raise InvalidAgentResponseError(
                        "The agent returned inconsistent web-search tool calls."
                    )
                tool_calls_by_id[tool_call_id] = validated_query

        if not isinstance(message, ToolMessage) or message.name != "tavily_search":
            continue

        query = tool_calls_by_id.pop(message.tool_call_id, None)
        if query is None:
            raise InvalidAgentResponseError(
                "The agent returned an unmatched web-search result."
            )
        executions.append(_normalize_search_execution(query, message))

    if tool_calls_by_id:
        raise InvalidAgentResponseError(
            "The agent returned a web-search call without a result."
        )

    try:
        return SearchEvidence(
            allowed=allowed,
            attempted=bool(executions),
            executions=tuple(executions),
        )
    except ValidationError as exc:
        raise InvalidAgentResponseError(
            "The agent returned inconsistent web-search evidence."
        ) from exc


def _normalize_search_execution(
    query: str,
    message: ToolMessage,
) -> SearchExecution:
    if message.status == "error":
        return SearchExecution(query=query, status="failed")

    try:
        payload = (
            json.loads(message.content) if isinstance(message.content, str) else None
        )
    except (TypeError, json.JSONDecodeError):
        payload = None

    if not isinstance(payload, dict) or payload.get("error"):
        return SearchExecution(query=query, status="failed")

    raw_results = payload.get("results")
    if not isinstance(raw_results, list):
        return SearchExecution(query=query, status="failed")

    sources = []
    seen_urls = set()
    for raw_source in raw_results:
        if not isinstance(raw_source, dict):
            continue
        raw_title = raw_source.get("title")
        raw_snippet = raw_source.get("content")
        candidate = {
            "title": (
                raw_title.strip()[:MAX_SOURCE_TITLE_CHARACTERS]
                if isinstance(raw_title, str)
                else raw_title
            ),
            "url": raw_source.get("url"),
            "snippet": (
                raw_snippet.strip()[:MAX_SOURCE_SNIPPET_CHARACTERS] or None
                if isinstance(raw_snippet, str)
                else None
            ),
        }
        try:
            source = SearchSource.model_validate(candidate)
        except ValidationError:
            continue
        normalized_url = str(source.url)
        if normalized_url in seen_urls:
            continue
        seen_urls.add(normalized_url)
        sources.append(source)
        if len(sources) == 2:
            break

    if not sources:
        return SearchExecution(query=query, status="failed")
    return SearchExecution(query=query, status="succeeded", sources=tuple(sources))
