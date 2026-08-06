# Agentic Chatbot with FastAPI

[![CI](https://github.com/Ajbil/agentic-chatbot-fastapi/actions/workflows/ci.yml/badge.svg)](https://github.com/Ajbil/agentic-chatbot-fastapi/actions/workflows/ci.yml)

A learning-focused AI agent application built with a Streamlit frontend, a FastAPI backend, and LangChain's agent abstraction. It supports Groq and OpenAI models and can optionally give the agent access to Tavily web search.

## Architecture

```text
User
  -> Streamlit UI
  -> FastAPI /models catalog
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
| `BACKEND_BASE_URL` | Optional frontend override | `http://127.0.0.1:3003` |
| `BACKEND_REQUEST_TIMEOUT_SECONDS` | Optional frontend override | `30` |

Settings are validated centrally. Missing credentials fail only when a request uses the corresponding provider or tool.

If you created `.env` before Checkpoint 03, replace `BACKEND_API_URL=http://127.0.0.1:3003/chat` with `BACKEND_BASE_URL=http://127.0.0.1:3003`. The frontend derives both `/models` and `/chat` from that base URL.

## Supported models

The backend owns the model catalog and exposes it through `GET /models`. The Streamlit UI loads this endpoint instead of maintaining its own model constants.

| Provider | Model | Application key | Tool calling |
|---|---|---|---|
| Groq | GPT-OSS 20B | `groq-gpt-oss-20b` | Yes |
| Groq | GPT-OSS 120B | `groq-gpt-oss-120b` | Yes |
| OpenAI | GPT-4o mini | `openai-gpt-4o-mini` | Yes |

GPT-OSS 20B is the default because it is the lower-cost Groq option in this curated learning catalog. Model availability changes over time, so catalog updates should be reviewed as operational changes.

## Chat API contract

`POST /chat` accepts one canonical request shape. Clients identify a model through the stable application key returned by `GET /models`; provider names and provider-facing model IDs are backend implementation details.

```json
{
  "model_key": "groq-gpt-oss-20b",
  "system_prompt": "Act as a helpful AI Assistant",
  "messages": [
    {
      "role": "user",
      "content": "Explain dependency injection."
    }
  ],
  "allow_search": false
}
```

A successful request returns HTTP `200` with a typed response:

```json
{
  "model_key": "groq-gpt-oss-20b",
  "reply": "Dependency injection means..."
}
```

Handled failures return a non-`200` status and a consistent error envelope:

```json
{
  "error": {
    "code": "unsupported_model",
    "message": "Unsupported model key: unknown-model",
    "details": []
  }
}
```

FastAPI's interactive documentation at `http://127.0.0.1:3003/docs` contains the complete request, response, validation, and status-code schemas.

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

This repository is intentionally still a learning prototype. It does not yet provide conversation memory, streaming, source display, provider-specific failure normalization, persistent storage, production-grade observability, or an explicit custom LangGraph workflow.

## Learning roadmap

The next checkpoints will introduce real chat history, expose search evidence, and eventually build an explicit LangGraph workflow with evaluation and observability.

## Learning journal

The project's plans, decision reasoning, implementation outcomes, and transferable senior-engineering lessons are recorded in [the learning journal](docs/learning/README.md). Each checkpoint is documented before its pull request is merged so the repository preserves both the code and the reasoning behind it.

## Security

- Keep secrets only in `.env` or your deployment platform's secret manager.
- Use `.env.example` to document required variable names without real values.
- If a secret is ever committed, revoke and replace it; deleting it from the latest commit is not sufficient.
