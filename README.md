# Agentic Chatbot with FastAPI

A learning-focused AI agent application built with a Streamlit frontend, a FastAPI backend, and LangChain's agent abstraction. It supports Groq and OpenAI models and can optionally give the agent access to Tavily web search.

## Architecture

```text
User
  -> Streamlit UI
  -> FastAPI /chat endpoint
  -> LangChain agent
     -> Groq or OpenAI
     -> optional Tavily search
  -> response
```

## Technology stack

- Python 3.12
- Streamlit for the user interface
- FastAPI and Uvicorn for the API
- Pydantic for request validation
- LangChain/LangGraph for agent orchestration
- Groq and OpenAI as model providers
- Tavily for optional web search
- Pipenv for dependency and environment management

## Prerequisites

- Python 3.12
- Pipenv
- API keys for Groq, OpenAI, and Tavily

The current prototype validates all three API keys when the backend starts, even if a request uses only one model provider or does not use search.

## Local setup

1. Install the dependencies:

   ```powershell
   pipenv install
   ```

2. Create a local environment file from the template:

   ```powershell
   Copy-Item .env.example .env
   ```

3. Add your API keys to `.env`. Never commit this file.

4. Start the FastAPI backend:

   ```powershell
   pipenv run python backend.py
   ```

5. In a second terminal, start the Streamlit frontend:

   ```powershell
   pipenv run streamlit run frontend.py
   ```

6. Open the Streamlit URL shown in the terminal. FastAPI's interactive API documentation is available at `http://127.0.0.1:3003/docs` while the backend is running.

## Current capabilities

- Choose between supported Groq and OpenAI models.
- Define a custom system prompt.
- Ask the agent a question through the Streamlit interface.
- Optionally allow the agent to search the web using Tavily.

## Current limitations

This repository is intentionally still a learning prototype. It does not yet provide conversation memory, streaming, source display, automated tests, persistent storage, production-grade error handling, or an explicit custom LangGraph workflow.

## Learning roadmap

The next checkpoints will stabilize configuration and API contracts, add tests with fake providers, introduce real chat history, expose search evidence, and eventually build an explicit LangGraph workflow with evaluation and observability.

## Security

- Keep secrets only in `.env` or your deployment platform's secret manager.
- Use `.env.example` to document required variable names without real values.
- If a secret is ever committed, revoke and replace it; deleting it from the latest commit is not sufficient.

