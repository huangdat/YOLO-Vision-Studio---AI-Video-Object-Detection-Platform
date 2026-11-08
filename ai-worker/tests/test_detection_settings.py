from pathlib import Path

from pydantic import ValidationError
import pytest

from app.config.settings import Settings
from app.schemas.detection import DetectionRequest, SourceType


def test_engine_environment_settings_use_the_documented_ai_names(monkeypatch, tmp_path):
    monkeypatch.setenv("AI_DEVICE", "cpu")
    monkeypatch.setenv("AI_MODEL_CACHE_DIR", str(tmp_path / "models"))
    monkeypatch.setenv("AI_TEMP_DIR", str(tmp_path / "work"))
    monkeypatch.setenv("AI_OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.setenv("AI_DEFAULT_CONFIDENCE", "0.4")
    monkeypatch.setenv("AI_DEFAULT_IMAGE_SIZE", "640")
    monkeypatch.setenv("AI_MAX_VIDEO_DURATION_SECONDS", "30")
    monkeypatch.setenv("AI_MAX_VIDEO_SIZE_MB", "10")
    monkeypatch.setenv("AI_MAX_DOWNLOAD_HEIGHT", "480")
    monkeypatch.setenv("AI_FFMPEG_PATH", "configured-ffmpeg")
    monkeypatch.setenv("AI_FFPROBE_PATH", "configured-ffprobe")
    settings = Settings()
    assert settings.ai_device == "cpu"
    assert settings.model_cache_dir == tmp_path / "models"
    assert settings.temp_dir == tmp_path / "work"
    assert settings.output_dir == tmp_path / "output"
    assert settings.default_confidence == 0.4 and settings.default_image_size == 640
    assert settings.max_video_duration_seconds == 30 and settings.max_video_size_mb == 10
    assert settings.max_download_height == 480
    assert settings.ffmpeg_path == "configured-ffmpeg" and settings.ffprobe_path == "configured-ffprobe"


@pytest.mark.parametrize("name,value", [
    ("AI_DEVICE", "cuda:9"), ("AI_DEFAULT_CONFIDENCE", "1.1"),
    ("AI_DEFAULT_CONFIDENCE", "nan"), ("AI_DEFAULT_IMAGE_SIZE", "0"),
    ("AI_MAX_VIDEO_DURATION_SECONDS", "-1"), ("AI_MAX_VIDEO_SIZE_MB", "0"),
    ("AI_MODEL_CACHE_DIR", ""),
])
def test_unsafe_engine_configuration_is_rejected(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.parametrize("classes", [[], [1, 1], [-1], [True], [1.1]])
def test_invalid_class_identifiers_are_rejected_before_inference(classes):
    with pytest.raises(ValidationError):
        DetectionRequest(source="sample.mp4", source_type=SourceType.LOCAL_FILE, classes=classes)


def test_source_type_must_be_explicit_and_model_identifier_is_not_a_file_path():
    with pytest.raises(ValidationError):
        DetectionRequest(source="sample.mp4")
    with pytest.raises(ValidationError):
        DetectionRequest(source="sample.mp4", source_type="HTTP_URL")
    with pytest.raises(ValidationError):
        DetectionRequest(source="sample.mp4", source_type=SourceType.LOCAL_FILE, model_key="../private.pt")
