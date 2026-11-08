from collections.abc import Iterator
import os

import pytest

from app.config.settings import get_settings

# Host configuration (for example AI_FFPROBE_PATH pointing at a real executable)
# must not change unit-test behavior. Tests that need a setting use monkeypatch.setenv.
_SETTINGS_PREFIXES = ("AI_", "YOLO_", "RABBITMQ_", "MINIO_", "WORKER_", "JOB_")
_SETTINGS_NAMES = {"LOG_LEVEL", "OMP_NUM_THREADS"}


@pytest.fixture(autouse=True)
def isolated_settings_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name in list(os.environ):
        if name.upper().startswith(_SETTINGS_PREFIXES) or name.upper() in _SETTINGS_NAMES:
            monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
