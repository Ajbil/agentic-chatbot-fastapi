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
- An API key for each service you choose to use

## Local setup

1. Install the dependencies:

   ```powershell
   python -m pipenv sync --dev
   ```

2. Create a local environment file from the template:

   ```powershell
   Copy-Item .env.example .env
   ```

3. Add the keys needed for the features you use. Never commit `.env`:

   - Groq models require `GROQ_API_KEY`.
   - OpenAI models require `OPENAI_API_KEY`.
   - Web search requires `TAVILY_API_KEY`.

4. Start the FastAPI backend:

   ```powershell
   python -m pipenv run python backend.py
   ```

5. In a second terminal, start the Streamlit frontend:

   ```powershell
   python -m pipenv run streamlit run frontend.py
   ```

6. Open the Streamlit URL shown in the terminal. FastAPI's interactive API documentation is available at `http://127.0.0.1:3003/docs` while the backend is running.

## Configuration

Configuration is loaded from environment variables and the local `.env` file.

| Variable | Required when | Default |
|---|---|---|
| `GROQ_API_KEY` | A Groq model is selected | None |
| `OPENAI_API_KEY` | An OpenAI model is selected | None |
| `TAVILY_API_KEY` | Web search is enabled | None |
| `BACKEND_API_URL` | Optional frontend override | `http://127.0.0.1:3003/chat` |
| `BACKEND_REQUEST_TIMEOUT_SECONDS` | Optional frontend override | `30` |

Settings are validated centrally. Missing credentials fail only when a request uses the corresponding provider or tool.

## Tests

Run the offline test suite with:

```powershell
python -m pipenv run python -m pytest
```

The tests use fake providers and do not make Groq, OpenAI, or Tavily requests.

## Current capabilities

- Choose between supported Groq and OpenAI models.
- Define a custom system prompt.
- Ask the agent a question through the Streamlit interface.
- Optionally allow the agent to search the web using Tavily.

## Current limitations

This repository is intentionally still a learning prototype. It does not yet provide conversation memory, streaming, source display, comprehensive test coverage, persistent storage, production-grade error handling, or an explicit custom LangGraph workflow.

## Learning roadmap

The next checkpoints will centralize the model registry and API contracts, expand test coverage, introduce real chat history, expose search evidence, and eventually build an explicit LangGraph workflow with evaluation and observability.

## Security

- Keep secrets only in `.env` or your deployment platform's secret manager.
- Use `.env.example` to document required variable names without real values.
- If a secret is ever committed, revoke and replace it; deleting it from the latest commit is not sufficient.
