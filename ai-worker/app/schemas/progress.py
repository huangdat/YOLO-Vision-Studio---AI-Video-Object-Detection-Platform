"""Queue-independent, monotonic overall progress events."""

from collections.abc import Callable
from enum import StrEnum
import logging

from pydantic import Field

from app.schemas.base import EngineSchema

logger = logging.getLogger(__name__)


class ProgressStage(StrEnum):
    DOWNLOADING = "DOWNLOADING"
    DETECTING = "DETECTING"
    ENCODING = "ENCODING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ProgressEvent(EngineSchema):
    stage: ProgressStage
    progress: int = Field(ge=0, le=100)
    processed_frames: int = Field(default=0, ge=0)
    total_frames: int | None = Field(default=None, gt=0)
    message: str = ""


ProgressCallback = Callable[[ProgressEvent], None]


class ProgressReporter:
    """Callbacks are best-effort observers and cannot invalidate a completed video."""

    def __init__(self, callback: ProgressCallback | None = None) -> None:
        self.callback = callback
        self.progress = 0
        self.processed_frames = 0
        self.total_frames: int | None = None

    def emit(self, event: ProgressEvent) -> None:
        progress = min(event.progress, 99) if event.stage != ProgressStage.COMPLETED else 100
        self.progress = max(self.progress, progress)
        self.processed_frames = max(self.processed_frames, event.processed_frames)
        if event.total_frames is not None:
            self.total_frames = event.total_frames
        normalized = event.model_copy(update={
            "progress": self.progress,
            "processed_frames": self.processed_frames,
            "total_frames": self.total_frames,
        })
        if self.callback is not None:
            try:
                self.callback(normalized)
            except Exception as error:
                # Future message delivery needs its own retry policy, not repeated inference.
                logger.warning("A progress observer failed to accept an event (%s)", type(error).__name__)
