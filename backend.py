from typing import List, Literal, Union

from fastapi import FastAPI
from pydantic import BaseModel, Field

from ai_agent import get_response_from_ai_agent
from model_registry import (
    ModelsResponse,
    UnsupportedModelError,
    get_models_response,
    resolve_model,
)


class MessageSchema(BaseModel):
    role: Literal["user", "assistant", "system"] = "user"
    content: str


class RequestState(BaseModel):
    model_name: str
    model_provider: str
    system_prompt: str = "Act as a helpful AI Assistant"
    messages: Union[str, List[MessageSchema], List[str]] = Field(
        default_factory=lambda: ["Hello"]
    )
    allow_search: bool = False


app = FastAPI(title="Langgraph AI Agent")


@app.get("/models", response_model=ModelsResponse)
def models_endpoint():
    """Return the application-owned catalog used by every client."""

    return get_models_response()


@app.post("/chat")
def chat_endpoint(request: RequestState):
    """Run one agent request using a registered provider/model combination."""

    try:
        model = resolve_model(request.model_provider, request.model_name)
    except UnsupportedModelError as exc:
        return {"error": str(exc)}

    if request.allow_search and not model.supports_tool_calling:
        return {"error": f"Model '{model.model_id}' does not support search tools."}

    return get_response_from_ai_agent(
        model,
        request.messages,
        request.allow_search,
        request.system_prompt,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=3003)
