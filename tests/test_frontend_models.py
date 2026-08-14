import pytest
import requests

import frontend_catalog
from frontend_catalog import ModelCatalogError, fetch_model_catalog, models_for_provider

VALID_CATALOG = {
    "default_model_key": "groq-gpt-oss-20b",
    "models": [
        {
            "key": "groq-gpt-oss-20b",
            "provider": "groq",
            "model_id": "openai/gpt-oss-20b",
            "display_name": "GPT-OSS 20B",
            "context_window_tokens": 131072,
            "max_output_tokens": 4096,
            "supports_tool_calling": True,
        },
        {
            "key": "openai-gpt-4o-mini",
            "provider": "openai",
            "model_id": "gpt-4o-mini",
            "display_name": "GPT-4o mini",
            "context_window_tokens": 128000,
            "max_output_tokens": 4096,
            "supports_tool_calling": True,
        },
    ],
}


class FakeResponse:
    def __init__(self, payload, error=None):
        self.payload = payload
        self.error = error

    def raise_for_status(self):
        if self.error is not None:
            raise self.error

    def json(self):
        return self.payload


def test_frontend_loads_and_validates_catalog(monkeypatch):
    captured = {}

    def fake_get(url, timeout):
        captured.update(url=url, timeout=timeout)
        return FakeResponse(VALID_CATALOG)

    monkeypatch.setattr(frontend_catalog.requests, "get", fake_get)

    catalog = fetch_model_catalog("http://backend/models", 12.5)

    assert catalog.default_model_key == "groq-gpt-oss-20b"
    assert captured == {"url": "http://backend/models", "timeout": 12.5}
    assert [model.key for model in models_for_provider(catalog, "groq")] == [
        "groq-gpt-oss-20b"
    ]


@pytest.mark.parametrize(
    "error",
    [
        requests.ConnectionError("offline"),
        requests.Timeout("slow backend"),
        requests.HTTPError("backend error"),
    ],
)
def test_frontend_converts_request_failures_to_catalog_error(monkeypatch, error):
    def fake_get(url, timeout):
        if isinstance(error, requests.HTTPError):
            return FakeResponse(VALID_CATALOG, error=error)
        raise error

    monkeypatch.setattr(frontend_catalog.requests, "get", fake_get)

    with pytest.raises(ModelCatalogError, match="catalog request failed"):
        fetch_model_catalog("http://backend/models", 30)


def test_frontend_rejects_invalid_catalog_schema(monkeypatch):
    monkeypatch.setattr(
        frontend_catalog.requests,
        "get",
        lambda url, timeout: FakeResponse({"models": "not-a-list"}),
    )

    with pytest.raises(ModelCatalogError, match="invalid model catalog"):
        fetch_model_catalog("http://backend/models", 30)


def test_frontend_rejects_catalog_with_missing_default(monkeypatch):
    invalid_catalog = {
        **VALID_CATALOG,
        "default_model_key": "model-that-is-not-present",
    }
    monkeypatch.setattr(
        frontend_catalog.requests,
        "get",
        lambda url, timeout: FakeResponse(invalid_catalog),
    )

    with pytest.raises(ModelCatalogError, match="invalid model catalog"):
        fetch_model_catalog("http://backend/models", 30)


def test_frontend_rejects_malformed_json(monkeypatch):
    class MalformedJsonResponse(FakeResponse):
        def json(self):
            raise ValueError("invalid JSON")

    monkeypatch.setattr(
        frontend_catalog.requests,
        "get",
        lambda url, timeout: MalformedJsonResponse(None),
    )

    with pytest.raises(ModelCatalogError, match="invalid model catalog"):
        fetch_model_catalog("http://backend/models", 30)
