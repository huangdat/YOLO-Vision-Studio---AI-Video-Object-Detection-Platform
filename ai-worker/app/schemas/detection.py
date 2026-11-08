"""Validated detection requests and bounded aggregate statistics."""

from enum import StrEnum
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator

from app.schemas.base import EngineSchema

DEFAULT_VEHICLE_CLASSES = (1, 2, 3, 5, 7)


class SourceType(StrEnum):
    LOCAL_FILE = "LOCAL_FILE"
    YOUTUBE_URL = "YOUTUBE_URL"


class DetectionRequest(EngineSchema):
    source: str = Field(min_length=1, max_length=8192)
    source_type: SourceType
    model_key: str = Field(default="yolo26s", pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    confidence: float | None = Field(default=None, ge=0, le=1)
    image_size: int | None = Field(default=None, gt=0)
    classes: list[Annotated[int, Field(ge=0, strict=True)]] | None = None
    device: str | None = Field(default=None, pattern=r"^(auto|cpu|cuda:0)$")
    output_path: Path | None = None

    @field_validator("source")
    @classmethod
    def nonempty_source(cls, value: str) -> str:
        value = value.strip()
        if not value or "\x00" in value:
            raise ValueError("A nonempty video source without null characters is required")
        return value

    @field_validator("classes")
    @classmethod
    def unique_classes(cls, value: list[int] | None) -> list[int] | None:
        if value is not None:
            if not value:
                raise ValueError("Select at least one class")
            if len(value) != len(set(value)):
                raise ValueError("Class identifiers must be unique")
        return value


class DetectionBox(EngineSchema):
    class_id: int = Field(ge=0)
    label: str
    confidence: float = Field(ge=0, le=1)
    xyxy: tuple[float, float, float, float]


class DetectionStatistics(EngineSchema):
    model_key: str
    device: str
    confidence: float = Field(ge=0, le=1)
    image_size: int = Field(gt=0)
    classes: list[int]
    total_frames_processed: int = Field(ge=0)
    total_detections: int = Field(ge=0)
    detections_by_class: dict[str, Annotated[int, Field(ge=0)]]
    processing_time_ms: int = Field(ge=0)
    average_inference_time_ms: float | None = Field(default=None, ge=0)
