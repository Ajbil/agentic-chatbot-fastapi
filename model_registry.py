from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Provider(StrEnum):
    GROQ = "groq"
    OPENAI = "openai"


class ModelSpec(BaseModel):
    """Immutable metadata for one model supported by this application."""

    model_config = ConfigDict(frozen=True)

    key: str
    provider: Provider
    model_id: str
    display_name: str
    context_window_tokens: int = Field(gt=0)
    max_output_tokens: int = Field(gt=0)
    supports_tool_calling: bool

    @model_validator(mode="after")
    def validate_token_budget(self) -> Self:
        if self.max_output_tokens >= self.context_window_tokens:
            raise ValueError(
                "max_output_tokens must be smaller than context_window_tokens."
            )
        return self


class ModelsResponse(BaseModel):
    default_model_key: str
    models: tuple[ModelSpec, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_catalog(self) -> Self:
        model_keys = [model.key for model in self.models]
        provider_and_ids = [(model.provider, model.model_id) for model in self.models]

        if len(set(model_keys)) != len(model_keys):
            raise ValueError("Model keys must be unique.")
        if len(set(provider_and_ids)) != len(provider_and_ids):
            raise ValueError("Provider/model pairs must be unique.")
        if self.default_model_key not in model_keys:
            raise ValueError("The default model key must identify a catalog model.")

        return self


class UnsupportedModelError(ValueError):
    """Raised when a provider/model combination is not in the registry."""


MODEL_CATALOG: tuple[ModelSpec, ...] = (
    ModelSpec(
        key="groq-gpt-oss-20b",
        provider=Provider.GROQ,
        model_id="openai/gpt-oss-20b",
        display_name="GPT-OSS 20B",
        context_window_tokens=131_072,
        max_output_tokens=4_096,
        supports_tool_calling=True,
    ),
    ModelSpec(
        key="groq-gpt-oss-120b",
        provider=Provider.GROQ,
        model_id="openai/gpt-oss-120b",
        display_name="GPT-OSS 120B",
        context_window_tokens=131_072,
        max_output_tokens=4_096,
        supports_tool_calling=True,
    ),
    ModelSpec(
        key="openai-gpt-4o-mini",
        provider=Provider.OPENAI,
        model_id="gpt-4o-mini",
        display_name="GPT-4o mini",
        context_window_tokens=128_000,
        max_output_tokens=4_096,
        supports_tool_calling=True,
    ),
)

DEFAULT_MODEL_KEY = "groq-gpt-oss-20b"


def _build_indexes() -> tuple[
    dict[str, ModelSpec],
    dict[tuple[Provider, str], ModelSpec],
]:
    models_by_key: dict[str, ModelSpec] = {}
    models_by_provider_and_id: dict[tuple[Provider, str], ModelSpec] = {}

    for model in MODEL_CATALOG:
        provider_and_id = (model.provider, model.model_id)
        if model.key in models_by_key:
            raise RuntimeError(f"Duplicate model key in registry: {model.key}")
        if provider_and_id in models_by_provider_and_id:
            raise RuntimeError(
                "Duplicate provider/model pair in registry: "
                f"{model.provider.value}/{model.model_id}"
            )

        models_by_key[model.key] = model
        models_by_provider_and_id[provider_and_id] = model

    if DEFAULT_MODEL_KEY not in models_by_key:
        raise RuntimeError("The default model key must identify a registered model.")

    return models_by_key, models_by_provider_and_id


_MODELS_BY_KEY, _MODELS_BY_PROVIDER_AND_ID = _build_indexes()


def list_models() -> tuple[ModelSpec, ...]:
    return MODEL_CATALOG


def get_default_model() -> ModelSpec:
    return _MODELS_BY_KEY[DEFAULT_MODEL_KEY]


def get_model_by_key(model_key: str) -> ModelSpec:
    try:
        return _MODELS_BY_KEY[model_key.strip()]
    except KeyError as exc:
        raise UnsupportedModelError(f"Unsupported model key: {model_key}") from exc


def resolve_model(provider: str | Provider, model_id: str) -> ModelSpec:
    provider_value = str(provider).strip().lower()
    model_id_value = model_id.strip()

    try:
        canonical_provider = Provider(provider_value)
    except ValueError as exc:
        supported_providers = ", ".join(item.value for item in Provider)
        raise UnsupportedModelError(
            f"Unsupported provider '{provider}'. Supported providers: {supported_providers}."
        ) from exc

    try:
        return _MODELS_BY_PROVIDER_AND_ID[(canonical_provider, model_id_value)]
    except KeyError as exc:
        allowed_models = ", ".join(
            model.model_id
            for model in MODEL_CATALOG
            if model.provider == canonical_provider
        )
        raise UnsupportedModelError(
            f"Model '{model_id}' is not supported by provider "
            f"'{canonical_provider.value}'. Allowed models: {allowed_models}."
        ) from exc


def get_models_response() -> ModelsResponse:
    return ModelsResponse(
        default_model_key=DEFAULT_MODEL_KEY,
        models=MODEL_CATALOG,
    )
