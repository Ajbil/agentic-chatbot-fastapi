import pytest
from pydantic import ValidationError

from config import Settings


API_KEY_VARIABLES = ("GROQ_API_KEY", "OPENAI_API_KEY", "TAVILY_API_KEY")


@pytest.fixture
def empty_environment(monkeypatch):
    for variable_name in API_KEY_VARIABLES + (
        "BACKEND_API_URL",
        "BACKEND_REQUEST_TIMEOUT_SECONDS",
    ):
        monkeypatch.delenv(variable_name, raising=False)


def test_settings_have_safe_defaults_without_credentials(empty_environment):
    settings = Settings(_env_file=None)

    assert settings.groq_api_key is None
    assert settings.openai_api_key is None
    assert settings.tavily_api_key is None
    assert str(settings.backend_api_url) == "http://127.0.0.1:3003/chat"
    assert settings.backend_request_timeout_seconds == 30.0


def test_environment_overrides_defaults(monkeypatch, empty_environment):
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-secret")
    monkeypatch.setenv("BACKEND_API_URL", "http://localhost:9000/chat")
    monkeypatch.setenv("BACKEND_REQUEST_TIMEOUT_SECONDS", "45")

    settings = Settings(_env_file=None)

    assert settings.groq_api_key is not None
    assert settings.groq_api_key.get_secret_value() == "test-groq-secret"
    assert str(settings.backend_api_url) == "http://localhost:9000/chat"
    assert settings.backend_request_timeout_seconds == 45.0


def test_secret_values_are_masked():
    settings = Settings(_env_file=None, groq_api_key="do-not-log-this")

    assert "do-not-log-this" not in repr(settings)
    assert "**********" in repr(settings.groq_api_key)


@pytest.mark.parametrize("timeout", [0, -1, 301])
def test_invalid_timeout_is_rejected(timeout):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, backend_request_timeout_seconds=timeout)
