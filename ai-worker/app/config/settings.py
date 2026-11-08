"""Validated process settings; credentials never belong in source files."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AI_WORKER_", extra="ignore", populate_by_name=True
    )

    host: str = Field(default="0.0.0.0", min_length=1)
    port: int = Field(default=8000, ge=1, le=65535)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO", validation_alias="LOG_LEVEL"
    )
    ai_device: str = Field(default="auto", pattern=r"^(auto|cpu|cuda:0)$", validation_alias="AI_DEVICE")
    model_cache_dir: Path = Field(default=Path("model-cache"), validation_alias="AI_MODEL_CACHE_DIR")
    temp_dir: Path = Field(default=Path("temp"), validation_alias="AI_TEMP_DIR")
    output_dir: Path = Field(default=Path("outputs"), validation_alias="AI_OUTPUT_DIR")
    local_input_dir: Path = Field(default=Path("."), validation_alias="AI_LOCAL_INPUT_DIR")
    default_confidence: float = Field(
        default=0.25, ge=0, le=1, allow_inf_nan=False, validation_alias="AI_DEFAULT_CONFIDENCE"
    )
    default_image_size: int = Field(default=960, gt=0, validation_alias="AI_DEFAULT_IMAGE_SIZE")
    max_video_duration_seconds: float = Field(
        default=300, gt=0, allow_inf_nan=False, validation_alias="AI_MAX_VIDEO_DURATION_SECONDS"
    )
    max_video_size_mb: float = Field(
        default=200, gt=0, allow_inf_nan=False, validation_alias="AI_MAX_VIDEO_SIZE_MB"
    )
    max_download_height: int = Field(default=720, gt=0, validation_alias="AI_MAX_DOWNLOAD_HEIGHT")
    ffmpeg_path: str = Field(default="ffmpeg", min_length=1, validation_alias="AI_FFMPEG_PATH")
    ffprobe_path: str = Field(default="ffprobe", min_length=1, validation_alias="AI_FFPROBE_PATH")
    youtube_js_runtime: Literal["deno", "node", "bun", "quickjs"] = Field(
        default="deno", validation_alias="AI_YOUTUBE_JS_RUNTIME"
    )
    youtube_js_runtime_path: str | None = Field(
        default=None, validation_alias="AI_YOUTUBE_JS_RUNTIME_PATH"
    )
    cpu_threads: int = Field(default=4, ge=1, le=32, validation_alias="AI_CPU_THREADS")
    max_frame_pixels: int = Field(default=8_294_400, gt=0, validation_alias="AI_MAX_FRAME_PIXELS")
    fallback_fps: float = Field(
        default=30, gt=0, le=240, allow_inf_nan=False, validation_alias="AI_FALLBACK_FPS"
    )
    processing_timeout_seconds: float = Field(
        default=1800, gt=0, allow_inf_nan=False, validation_alias="AI_PROCESSING_TIMEOUT_SECONDS"
    )

    @field_validator("log_level", mode="before")
    @classmethod
    def normalize_log_level(cls, value: object) -> object:
        # Spring Boot uses WARN; normalize the shared setting for Python logging.
        return "WARNING" if value == "WARN" else value

    @field_validator("model_cache_dir", "temp_dir", "output_dir", "local_input_dir", mode="before")
    @classmethod
    def nonempty_directory(cls, value: object) -> object:
        if isinstance(value, str) and (not value.strip() or "\x00" in value):
            raise ValueError("Directory settings must be nonempty paths without null characters")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
