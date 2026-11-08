"""Schema version 1 RabbitMQ contract, mirrored by the backend's dto.messaging records.

JSON uses camelCase. Commands carry no credentials, paths outside the worker's input
directory, or checkpoint locations; ``modelKey`` is resolved through the worker registry.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
import json
import re
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from app.schemas.base import EngineSchema
from app.schemas.detection import SourceType

SCHEMA_VERSION = 1
COMMAND_MESSAGE_TYPE = "detection.execute.v1"
EVENT_MESSAGE_TYPE = "detection.event.v1"
_LOCAL_PATH = re.compile(r"[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*\Z")


class DetectionCommand(EngineSchema):
    schema_version: Literal[1]
    message_id: UUID
    job_id: UUID
    model_key: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    source_type: SourceType
    source: str = Field(min_length=1, max_length=2048)
    confidence: Decimal = Field(ge=0, le=1, max_digits=4, decimal_places=3)
    image_size: int = Field(ge=32, le=4096, multiple_of=32)
    classes: list[Annotated[int, Field(ge=0, le=9999, strict=True)]] = Field(min_length=1, max_length=100)
    created_at: datetime

    @field_validator("classes")
    @classmethod
    def unique_classes(cls, value: list[int]) -> list[int]:
        if len(value) != len(set(value)):
            raise ValueError("Class identifiers must be unique")
        return value

    @model_validator(mode="after")
    def local_paths_are_relative(self) -> DetectionCommand:
        if self.source_type == SourceType.LOCAL_FILE:
            segments = self.source.split("/")
            if not _LOCAL_PATH.match(self.source) or any(part in {".", ".."} for part in segments):
                raise ValueError("Local sources must be relative paths inside the worker input directory")
        return self


class WorkerJobStatus(StrEnum):
    DOWNLOADING = "DOWNLOADING"
    DETECTING = "DETECTING"
    ENCODING = "ENCODING"
    UPLOADING = "UPLOADING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class EventResult(EngineSchema):
    output_video_key: str = Field(min_length=1, max_length=1024)
    result_json_key: str = Field(min_length=1, max_length=1024)
    total_frames: int = Field(ge=0)
    processing_time_ms: int = Field(ge=0)
    detection_summary: dict[Annotated[str, Field(min_length=1, max_length=128)], Annotated[int, Field(ge=0)]]


class EventError(EngineSchema):
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,63}$")
    message: str = Field(min_length=1, max_length=1000)
    retryable: bool = False


class DetectionEvent(EngineSchema):
    schema_version: Literal[1] = SCHEMA_VERSION
    event_id: UUID = Field(default_factory=uuid4)
    job_id: UUID
    status: WorkerJobStatus
    progress: int = Field(ge=0, le=100)
    processed_frames: int | None = Field(default=None, ge=0)
    total_frames: int | None = Field(default=None, ge=0)
    message: str | None = Field(default=None, max_length=500)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    model_key: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    result: EventResult | None = None
    error: EventError | None = None

    @model_validator(mode="after")
    def payload_matches_status(self) -> DetectionEvent:
        completed = self.status == WorkerJobStatus.COMPLETED
        failed = self.status == WorkerJobStatus.FAILED
        if completed != (self.result is not None):
            raise ValueError("result is required for and only allowed on COMPLETED")
        if completed and (self.model_key is None or self.progress != 100):
            raise ValueError("COMPLETED requires modelKey and progress 100")
        if not completed and self.progress == 100:
            raise ValueError("Only COMPLETED may report 100% progress")
        if failed != (self.error is not None):
            raise ValueError("error is required for and only allowed on FAILED")
        return self

    def to_json_bytes(self) -> bytes:
        # Timestamps as ISO-8601 UTC with a Z suffix, accepted by Java's Instant parser.
        data = self.model_dump(mode="json", by_alias=True, exclude_none=True)
        data["timestamp"] = self.timestamp.astimezone(UTC).isoformat().replace("+00:00", "Z")
        return json.dumps(data, separators=(",", ":")).encode("utf-8")
