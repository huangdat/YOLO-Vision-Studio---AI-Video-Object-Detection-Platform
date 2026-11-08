import logging

import pytest
from pydantic import ValidationError

from app.config.settings import Settings


def test_settings_read_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_WORKER_HOST", "127.0.0.1")
    monkeypatch.setenv("AI_WORKER_PORT", "8100")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

    settings = Settings()

    assert settings.host == "127.0.0.1"
    assert settings.port == 8100
    assert settings.log_level == "DEBUG"


@pytest.mark.parametrize("port", ["0", "65536", "invalid"])
def test_invalid_port_fails_at_startup(
    monkeypatch: pytest.MonkeyPatch, port: str
) -> None:
    monkeypatch.setenv("AI_WORKER_PORT", port)

    with pytest.raises(ValidationError):
        Settings()


def test_unknown_log_level_fails_at_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "VERBOSE")

    with pytest.raises(ValidationError):
        Settings()


def test_shared_warn_level_maps_to_python_warning_priority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOG_LEVEL", "WARN")

    settings = Settings()
    handler = logging.NullHandler()
    handler.setLevel(settings.log_level)

    assert settings.log_level == "WARNING"
    assert handler.level == logging.WARNING
