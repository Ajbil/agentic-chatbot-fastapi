import pytest
from pydantic import ValidationError

from config import Settings

API_KEY_VARIABLES = ("GROQ_API_KEY", "OPENAI_API_KEY", "TAVILY_API_KEY")


@pytest.fixture
def empty_environment(monkeypatch):
    for variable_name in API_KEY_VARIABLES + (
        "BACKEND_BASE_URL",
        "BACKEND_REQUEST_TIMEOUT_SECONDS",
        "BACKEND_STREAM_READ_TIMEOUT_SECONDS",
        "APP_LOG_LEVEL",
        "APP_LOG_FORMAT",
    ):
        monkeypatch.delenv(variable_name, raising=False)


def test_settings_have_safe_defaults_without_credentials(empty_environment):
    settings = Settings(_env_file=None)

    assert settings.groq_api_key is None
    assert settings.openai_api_key is None
    assert settings.tavily_api_key is None
    assert str(settings.backend_base_url) == "http://127.0.0.1:3003/"
    assert settings.backend_chat_url == "http://127.0.0.1:3003/chat"
    assert settings.backend_chat_stream_url == "http://127.0.0.1:3003/chat/stream"
    assert settings.backend_models_url == "http://127.0.0.1:3003/models"
    assert settings.backend_request_timeout_seconds == 30.0
    assert settings.backend_stream_read_timeout_seconds == 120.0
    assert settings.app_log_level == "INFO"
    assert settings.app_log_format == "json"


def test_environment_overrides_defaults(monkeypatch, empty_environment):
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-secret")
    monkeypatch.setenv("BACKEND_BASE_URL", "http://localhost:9000/api/")
    monkeypatch.setenv("BACKEND_REQUEST_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("BACKEND_STREAM_READ_TIMEOUT_SECONDS", "180")
    monkeypatch.setenv("APP_LOG_LEVEL", "WARNING")
    monkeypatch.setenv("APP_LOG_FORMAT", "console")

    settings = Settings(_env_file=None)

    assert settings.groq_api_key is not None
    assert settings.groq_api_key.get_secret_value() == "test-groq-secret"
    assert str(settings.backend_base_url) == "http://localhost:9000/api/"
    assert settings.backend_chat_url == "http://localhost:9000/api/chat"
    assert settings.backend_chat_stream_url == "http://localhost:9000/api/chat/stream"
    assert settings.backend_models_url == "http://localhost:9000/api/models"
    assert settings.backend_request_timeout_seconds == 45.0
    assert settings.backend_stream_read_timeout_seconds == 180.0
    assert settings.app_log_level == "WARNING"
    assert settings.app_log_format == "console"


def test_secret_values_are_masked():
    settings = Settings(_env_file=None, groq_api_key="do-not-log-this")

    assert "do-not-log-this" not in repr(settings)
    assert "**********" in repr(settings.groq_api_key)


@pytest.mark.parametrize("timeout", [0, -1, 301])
def test_invalid_timeout_is_rejected(timeout):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, backend_request_timeout_seconds=timeout)


@pytest.mark.parametrize("timeout", [0, -1, 601])
def test_invalid_stream_read_timeout_is_rejected(timeout):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, backend_stream_read_timeout_seconds=timeout)


def test_invalid_backend_base_url_is_rejected():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, backend_base_url="not-a-url")


@pytest.mark.parametrize(
    ("field", "value"),
    [("app_log_level", "TRACE"), ("app_log_format", "xml")],
)
def test_invalid_logging_configuration_is_rejected(field, value):
    with pytest.raises(ValidationError):
        Settings.model_validate({field: value})
