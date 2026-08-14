import requests
from pydantic import ValidationError

from model_registry import ModelSpec, ModelsResponse


class ModelCatalogError(RuntimeError):
    """Raised when the frontend cannot load a valid backend model catalog."""


def fetch_model_catalog(url: str, timeout: float) -> ModelsResponse:
    try:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise ModelCatalogError(
            f"The backend model catalog request failed: {exc}"
        ) from exc

    try:
        payload = response.json()
        return ModelsResponse.model_validate(payload)
    except (ValidationError, ValueError) as exc:
        raise ModelCatalogError(
            "The backend returned an invalid model catalog."
        ) from exc


def models_for_provider(
    catalog: ModelsResponse,
    provider: str,
) -> tuple[ModelSpec, ...]:
    return tuple(model for model in catalog.models if model.provider.value == provider)
