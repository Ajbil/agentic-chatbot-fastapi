import pytest
from pydantic import ValidationError

from model_registry import (
    DEFAULT_MODEL_KEY,
    MODEL_CATALOG,
    Provider,
    UnsupportedModelError,
    get_default_model,
    get_model_by_key,
    get_models_response,
    resolve_model,
)


EXPECTED_MODEL_KEYS = (
    "groq-gpt-oss-20b",
    "groq-gpt-oss-120b",
    "openai-gpt-4o-mini",
)


def test_catalog_is_deterministic_and_has_unique_identifiers():
    assert tuple(model.key for model in MODEL_CATALOG) == EXPECTED_MODEL_KEYS
    assert len({model.key for model in MODEL_CATALOG}) == len(MODEL_CATALOG)
    assert len({(model.provider, model.model_id) for model in MODEL_CATALOG}) == len(
        MODEL_CATALOG
    )


def test_default_model_is_registered():
    default_model = get_default_model()

    assert DEFAULT_MODEL_KEY == "groq-gpt-oss-20b"
    assert default_model == get_model_by_key(DEFAULT_MODEL_KEY)
    assert default_model.provider == Provider.GROQ
    assert default_model.model_id == "openai/gpt-oss-20b"


def test_catalog_response_exposes_required_capabilities():
    response = get_models_response()

    assert response.default_model_key == DEFAULT_MODEL_KEY
    assert response.models == MODEL_CATALOG
    assert all(model.supports_tool_calling for model in response.models)
    assert [model.context_window_tokens for model in response.models] == [
        131_072,
        131_072,
        128_000,
    ]


def test_provider_lookup_normalizes_provider_but_not_model_id():
    model = resolve_model("  GrOq  ", "openai/gpt-oss-120b")

    assert model.key == "groq-gpt-oss-120b"


@pytest.mark.parametrize(
    ("provider", "model_id", "message"),
    [
        ("unknown", "model", "Unsupported provider"),
        ("groq", "gpt-4o-mini", "not supported by provider 'groq'"),
        ("openai", "openai/gpt-oss-20b", "not supported by provider 'openai'"),
        ("groq", "mixtral-8x7b-32768", "not supported by provider 'groq'"),
    ],
)
def test_invalid_or_mismatched_model_is_rejected(provider, model_id, message):
    with pytest.raises(UnsupportedModelError, match=message):
        resolve_model(provider, model_id)


def test_model_definitions_are_immutable():
    with pytest.raises(ValidationError):
        get_default_model().model_id = "changed-model"
