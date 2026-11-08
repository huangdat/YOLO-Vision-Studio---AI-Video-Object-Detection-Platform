"""Metadata estimates remain distinct from actual processed-frame statistics."""

from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.base import EngineSchema
from app.schemas.detection import DetectionStatistics, SourceType


class VideoMetadata(EngineSchema):
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    fps: float = Field(gt=0)
    total_frames: int | None = Field(default=None, gt=0)
    duration_seconds: float | None = Field(default=None, gt=0)
    frame_count_estimated: bool = True
    fps_estimated: bool = False


class ProcessingResult(EngineSchema):
    path: Path
    metadata: VideoMetadata
    statistics: DetectionStatistics


class InputVideoMetadata(VideoMetadata):
    source_type: SourceType


class VideoOutput(EngineSchema):
    video_filename: str
    video_path: Path
    metadata_path: Path


class DetectionResult(EngineSchema):
    execution_id: UUID
    model_key: str
    model_version: str
    model_size: str
    weights_filename: str
    device: str
    status: Literal["COMPLETED"] = "COMPLETED"
    input: InputVideoMetadata
    output: VideoOutput
    statistics: DetectionStatistics
    processing_time_ms: int = Field(ge=0)
