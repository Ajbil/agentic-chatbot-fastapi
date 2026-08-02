# step 1 : set up pydantic model (schema validations)
from pydantic import BaseModel, Field
from typing import List, Literal, Union

class MessageSchema(BaseModel):
    role: Literal["user", "assistant", "system"] = "user"
    content: str

class RequestState(BaseModel):
    model_name: str
    model_provider: str
    system_prompt: str = "Act as a helpful AI Assistant"
    messages: Union[str, List[MessageSchema], List[str]] = Field(default_factory=lambda: ["Hello"])
    allow_search: bool = False

#step 2 : set up AI agent from Frotend request

from fastapi import FastAPI
from ai_agent import get_response_from_ai_agent

ALLOWED_MODEL_NAMES=["llama3-70b-8192", "mixtral-8x7b-32768", "llama-3.3-70b-versatile", "gpt-4o-mini"]

app = FastAPI(title="Langgraph AI Agent")

@app.post("/chat")
def chat_endpoint(request : RequestState):
    """
    API Endpoint to interact with the chatbot using Langgraph and search tool.
    It dynamically selects the mode specified in the request.
    """

    if request.model_name not in ALLOWED_MODEL_NAMES:
        return {"error": f"Model '{request.model_name}' is not allowed. Allowed models: {ALLOWED_MODEL_NAMES}"}
    
    llm_id = request.model_name
    query = request.messages
    allow_search = request.allow_search
    system_prompt = request.system_prompt
    provider = request.model_provider

    # create AI agent and get response from it
    response = get_response_from_ai_agent(llm_id, query, allow_search, system_prompt, provider)
    return response

#step 3: run app and explore swagger UI docs
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port =3003)