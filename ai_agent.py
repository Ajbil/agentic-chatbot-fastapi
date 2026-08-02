# Step 1: load API keys
import os

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_groq import ChatGroq
from langchain_tavily import TavilySearch
from langchain_openai import ChatOpenAI

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

if not GROQ_API_KEY:
    raise RuntimeError("GROQ_API_KEY is missing. Add it to your .env file or environment.")

if not TAVILY_API_KEY:
    raise RuntimeError("TAVILY_API_KEY is missing. Add it to your .env file or environment.")

if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY is missing. Add it to your .env file or environment.")

    
def _convert_messages_to_langchain(query):
    if isinstance(query, str):
        return [HumanMessage(content=query)]

    if isinstance(query, list) and query and all(isinstance(item, str) for item in query):
        return [HumanMessage(content=item) for item in query]

    langchain_messages = []
    for item in query or []:
        if hasattr(item, "role") and hasattr(item, "content"):
            role = item.role
            content = item.content
        elif isinstance(item, dict):
            role = item.get("role", "user")
            content = item.get("content", "")
        else:
            continue

        if role == "user":
            langchain_messages.append(HumanMessage(content=content))
        elif role == "assistant":
            langchain_messages.append(AIMessage(content=content))
        elif role == "system":
            langchain_messages.append(SystemMessage(content=content))

    return langchain_messages or [HumanMessage(content="Hello")]


# Step 2: create the agent
system_prompt = "act as an AI agent who is smart and friendly"


def get_response_from_ai_agent(llm_id, query, allow_search, system_prompt, provider):
    provider_name = (provider or "").strip().lower()

    if provider_name == "groq":
        llm = ChatGroq(model=llm_id, groq_api_key=GROQ_API_KEY)
    elif provider_name == "openai":
        llm = ChatOpenAI(model=llm_id, api_key=OPENAI_API_KEY)
    else:
        raise ValueError(f"Unsupported provider: {provider}")

    tools = [TavilySearch(max_results=2, api_key=TAVILY_API_KEY)] if allow_search else []

    agent = create_agent(
        model=llm,
        tools=tools,
        system_prompt=system_prompt or "act as an AI agent who is smart and friendly",
    )

    state = {"messages": _convert_messages_to_langchain(query)}
    response = agent.invoke(state)
    messages = response.get("messages", [])
    ai_messages = [msg for msg in messages if isinstance(msg, AIMessage)]

    if ai_messages:
        latest_message = ai_messages[-1]
        return {"reply": latest_message.content}

    return {"reply": ""}
