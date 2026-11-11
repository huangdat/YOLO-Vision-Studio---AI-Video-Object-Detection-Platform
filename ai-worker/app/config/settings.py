"""Validated process settings; credentials never belong in source files."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
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
    # Disk budget for the worker's own temporary files (normalized input, annotated MJPG
    # intermediate). MJPG is large: about 180 KB per 720p frame, about 1.6 GB for 300 s at 30 fps.
    max_intermediate_size_mb: float = Field(
        default=4096, gt=0, allow_inf_nan=False, validation_alias="AI_MAX_INTERMEDIATE_SIZE_MB"
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

    # RabbitMQ: names are shared with the Spring Boot backend so both declare identical topology.
    rabbitmq_host: str = Field(default="localhost", min_length=1, validation_alias="RABBITMQ_HOST")
    rabbitmq_port: int = Field(default=5672, ge=1, le=65535, validation_alias="RABBITMQ_PORT")
    rabbitmq_username: str = Field(default="yolovision", min_length=1, validation_alias="RABBITMQ_USERNAME")
    rabbitmq_password: SecretStr | None = Field(default=None, validation_alias="RABBITMQ_PASSWORD")
    rabbitmq_vhost: str = Field(default="/", min_length=1, validation_alias="RABBITMQ_VHOST")
    rabbitmq_heartbeat_seconds: int = Field(default=60, ge=10, le=600, validation_alias="RABBITMQ_HEARTBEAT_SECONDS")
    command_exchange: str = Field(default="vision.detection.commands", validation_alias="RABBITMQ_COMMAND_EXCHANGE")
    command_queue: str = Field(default="vision.detection.jobs", validation_alias="RABBITMQ_COMMAND_QUEUE")
    command_routing_key: str = Field(default="detection.execute", validation_alias="RABBITMQ_COMMAND_ROUTING_KEY")
    event_exchange: str = Field(default="vision.detection.events", validation_alias="RABBITMQ_EVENT_EXCHANGE")
    event_queue: str = Field(default="vision.detection.events.backend", validation_alias="RABBITMQ_EVENT_QUEUE")
    event_routing_key: str = Field(default="detection.status", validation_alias="RABBITMQ_EVENT_ROUTING_KEY")
    dead_letter_exchange: str = Field(
        default="vision.detection.dead-letter.exchange", validation_alias="RABBITMQ_DEAD_LETTER_EXCHANGE"
    )
    dead_letter_queue: str = Field(default="vision.detection.dead-letter", validation_alias="RABBITMQ_DEAD_LETTER_QUEUE")
    dead_letter_routing_key: str = Field(
        default="detection.dead-letter", validation_alias="RABBITMQ_DEAD_LETTER_ROUTING_KEY"
    )
    delivery_limit: int = Field(default=5, ge=1, le=100, validation_alias="RABBITMQ_DELIVERY_LIMIT")

    # Worker execution. One inference at a time per process by default (CPU/GPU memory).
    worker_concurrency: int = Field(default=1, ge=1, le=16, validation_alias="WORKER_CONCURRENCY")
    worker_prefetch_count: int | None = Field(default=None, ge=1, le=64, validation_alias="WORKER_PREFETCH_COUNT")
    job_max_retries: int = Field(default=3, ge=1, le=20, validation_alias="JOB_MAX_RETRIES")
    worker_retry_backoff_seconds: float = Field(
        default=5, ge=0, le=300, allow_inf_nan=False, validation_alias="WORKER_RETRY_BACKOFF_SECONDS"
    )
    worker_progress_interval_seconds: float = Field(
        default=5, gt=0, le=300, allow_inf_nan=False, validation_alias="WORKER_PROGRESS_INTERVAL_SECONDS"
    )
    worker_progress_min_step: int = Field(default=5, ge=1, le=50, validation_alias="WORKER_PROGRESS_MIN_STEP")
    worker_heartbeat_seconds: float = Field(
        default=30, gt=0, le=600, allow_inf_nan=False, validation_alias="WORKER_HEARTBEAT_SECONDS"
    )
    worker_shutdown_timeout_seconds: float = Field(
        default=60, ge=0, le=3600, allow_inf_nan=False, validation_alias="WORKER_SHUTDOWN_TIMEOUT_SECONDS"
    )
    worker_allow_model_download: bool = Field(default=False, validation_alias="WORKER_ALLOW_MODEL_DOWNLOAD")
    worker_health_file: Path | None = Field(default=None, validation_alias="WORKER_HEALTH_FILE")

    # Minimal artifact storage for completed jobs (MinIO, S3-compatible).
    minio_endpoint: str = Field(default="http://localhost:9000", min_length=1, validation_alias="MINIO_ENDPOINT")
    minio_access_key: str = Field(default="yolovision", min_length=1, validation_alias="MINIO_ACCESS_KEY")
    minio_secret_key: SecretStr | None = Field(default=None, validation_alias="MINIO_SECRET_KEY")
    minio_bucket: str = Field(default="videos", pattern=r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$",
                              validation_alias="MINIO_BUCKET")
    minio_object_prefix: str = Field(default="detections", pattern=r"^[a-z0-9][a-z0-9/_-]{0,62}[a-z0-9]$",
                                     validation_alias="MINIO_OBJECT_PREFIX")
    minio_region: str | None = Field(default=None, validation_alias="MINIO_REGION")

    # Live (webcam) inference: an internal HTTP API served by the dedicated ai-live-worker.
    live_max_frame_bytes: int = Field(
        default=512 * 1024, ge=1024, le=8 * 1024 * 1024, validation_alias="LIVE_MAX_FRAME_BYTES"
    )
    live_max_frame_pixels: int = Field(default=1280 * 720, gt=0, le=8_294_400, validation_alias="LIVE_MAX_FRAME_PIXELS")
    live_max_frame_side: int = Field(default=1280, ge=32, le=4096, validation_alias="LIVE_MAX_FRAME_SIDE")
    live_max_image_size: int = Field(default=640, ge=32, le=1280, validation_alias="LIVE_MAX_IMAGE_SIZE")
    live_model_sizes: str = Field(default="n", pattern=r"^[nslmx](,[nslmx])*$", validation_alias="LIVE_MODEL_SIZES")
    live_max_loaded_models: int = Field(default=1, ge=1, le=4, validation_alias="LIVE_MAX_LOADED_MODELS")
    live_max_concurrent_inferences: int = Field(
        default=1, ge=1, le=4, validation_alias="LIVE_MAX_CONCURRENT_INFERENCES"
    )

    @property
    def live_allowed_model_sizes(self) -> frozenset[str]:
        return frozenset(self.live_model_sizes.split(","))

    @property
    def effective_prefetch_count(self) -> int:
        return max(self.worker_prefetch_count or self.worker_concurrency, self.worker_concurrency)

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
