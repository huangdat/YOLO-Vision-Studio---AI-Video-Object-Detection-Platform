"""Metadata estimates remain distinct from actual processed-frame statistics."""

from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.base import EngineSchema
from app.schemas.detection import (
    DetectionStatistics, InferencePrecision, InferenceRuntime, ProcessingMode, SourceType,
)
from app.schemas.tracking import TrackingStatistics


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
    processing_mode: ProcessingMode = ProcessingMode.DETECTION_ONLY
    tracking: TrackingStatistics | None = None
    effective_precision: InferencePrecision | None = None
    inference_runtime: InferenceRuntime | None = None


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
    processing_mode: ProcessingMode = ProcessingMode.DETECTION_ONLY
    # Present only in tracking mode; legacy result files have neither field.
    tracking: TrackingStatistics | None = None
    # What actually ran (never the request echoed back); absent in results written before Phase 3.
    effective_precision: InferencePrecision | None = None
    inference_runtime: InferenceRuntime | None = None
