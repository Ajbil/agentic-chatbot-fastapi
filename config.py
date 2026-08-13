from functools import lru_cache
from pathlib import Path

from pydantic import Field, HttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parent


class Settings(BaseSettings):
    """Application configuration loaded from environment variables or .env."""

    groq_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    tavily_api_key: SecretStr | None = None
    backend_base_url: HttpUrl = HttpUrl("http://127.0.0.1:3003")
    backend_request_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    backend_stream_read_timeout_seconds: float = Field(default=120.0, gt=0, le=600)

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def backend_chat_url(self) -> str:
        return self._backend_endpoint_url("chat")

    @property
    def backend_chat_stream_url(self) -> str:
        return self._backend_endpoint_url("chat/stream")

    @property
    def backend_models_url(self) -> str:
        return self._backend_endpoint_url("models")

    def _backend_endpoint_url(self, path: str) -> str:
        return f"{str(self.backend_base_url).rstrip('/')}/{path.lstrip('/')}"


@lru_cache
def get_settings() -> Settings:
    """Return one immutable-by-convention settings snapshot per process."""

    return Settings()
