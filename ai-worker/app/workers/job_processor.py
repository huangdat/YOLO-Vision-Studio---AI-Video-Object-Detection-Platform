"""Broker-independent handling of one detection command.

The processor validates the command, runs the existing DetectionPipeline, stores the
artifacts, publishes events through an injected sink, and decides how the command must be
settled. It knows nothing about pika, so it is unit-testable without RabbitMQ.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
import json
import logging
from pathlib import Path
import re
import shutil
import tempfile
import threading
import time
from typing import Any, Protocol
from uuid import UUID, uuid4

from pydantic import ValidationError

from app.config.settings import Settings
from app.core.exceptions import (
    ArtifactStorageError, DetectionEngineError, InferenceError, InvalidVideoSourceError, ModelLoadingError,
    VideoDownloadError, VideoEncodingError, VideoLimitExceededError, VideoProcessingError,
)
from app.schemas.detection import DetectionRequest, SourceType
from app.schemas.messaging import DetectionCommand, DetectionEvent, EventError, EventResult, WorkerJobStatus
from app.schemas.progress import ProgressEvent, ProgressStage
from app.services.artifact_storage import ArtifactStore
from app.services.model_registry import CacheStatus, get_model_spec, inspect_model

logger = logging.getLogger(__name__)

PIPELINE_PROGRESS_CEILING = 95
UPLOADING_PROGRESS = 96


class Disposition(StrEnum):
    ACK = "ACK"                 # handled (completed, or failed permanently with a FAILED event)
    RETRY = "RETRY"             # transient failure: requeue for another attempt
    DEAD_LETTER = "DEAD_LETTER"  # unprocessable or retries exhausted: reject without requeue


@dataclass(frozen=True)
class Settlement:
    disposition: Disposition
    retry_delay_seconds: float = 0.0
    error_code: str | None = None


class EventSink(Protocol):
    def publish(self, event: DetectionEvent, *, required: bool) -> None:
        """Publish one event. Required events raise when the broker did not confirm them."""


class EventPublicationError(Exception):
    """A required event (completion or failure) was not confirmed by the broker."""


@dataclass(frozen=True)
class FailureInfo:
    code: str
    message: str
    retryable: bool


_PATH_PATTERN = re.compile(r"((?<![\w.])/(?:[\w.-]+/)+[\w.-]*|https?://\S+)")
# Windows drive and UNC paths may contain spaces ("C:\Users\First Last\..."), so their end
# cannot be found reliably: everything from such a path to the end of the message is removed.
_WINDOWS_PATH_PATTERN = re.compile(r"(?:(?<![A-Za-z])[A-Za-z]:[\\/]|\\\\[^\s\\/]+[\\/]).*", re.DOTALL)


def sanitize_message(message: str) -> str:
    """Remove filesystem paths and URLs from error text and bound its length."""
    clean = " ".join(str(message).split())
    clean = _WINDOWS_PATH_PATTERN.sub("[redacted]", clean)
    clean = _PATH_PATTERN.sub("[redacted]", clean)
    return (clean or "Detection failed.")[:500]


def classify(error: BaseException) -> FailureInfo:
    """Permanent errors are reported once; transient ones are retried with a bound."""
    if isinstance(error, ArtifactStorageError):
        return FailureInfo("STORAGE_FAILED", "Result artifacts could not be stored.", True)
    if isinstance(error, VideoDownloadError):
        return FailureInfo("VIDEO_DOWNLOAD_FAILED", sanitize_message(str(error)), True)
    if isinstance(error, EventPublicationError):
        return FailureInfo("EVENT_PUBLICATION_FAILED", "A completion event could not be delivered.", True)
    if isinstance(error, InvalidVideoSourceError):
        return FailureInfo("INVALID_SOURCE", sanitize_message(str(error)), False)
    if isinstance(error, VideoLimitExceededError):
        return FailureInfo("VIDEO_LIMIT_EXCEEDED", sanitize_message(str(error)), False)
    if isinstance(error, ModelLoadingError):
        return FailureInfo("MODEL_LOAD_FAILED", sanitize_message(str(error)), True)
    if isinstance(error, InferenceError):
        return FailureInfo("INFERENCE_FAILED", sanitize_message(str(error)), False)
    if isinstance(error, VideoEncodingError):
        # FFmpeg diagnostics can include local paths; report a fixed message.
        return FailureInfo("VIDEO_ENCODING_FAILED", "The annotated video could not be encoded.", False)
    if isinstance(error, VideoProcessingError):
        return FailureInfo("VIDEO_PROCESSING_FAILED", sanitize_message(str(error)), False)
    if isinstance(error, DetectionEngineError):
        return FailureInfo("DETECTION_FAILED", sanitize_message(str(error)), False)
    return FailureInfo("INTERNAL_ERROR", "An unexpected worker error occurred.", True)


class ProgressThrottle:
    """Publish on stage change, a meaningful increase, or after the interval elapsed."""

    def __init__(self, min_step: int, interval_seconds: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.min_step = min_step
        self.interval = interval_seconds
        self.clock = clock
        self.stage: WorkerJobStatus | None = None
        self.progress = -1
        self.published_at = float("-inf")

    def should_publish(self, stage: WorkerJobStatus, progress: int) -> bool:
        now = self.clock()
        if (stage != self.stage or progress >= self.progress + self.min_step
                or (progress > self.progress and now - self.published_at >= self.interval)):
            self.stage, self.progress, self.published_at = stage, progress, now
            return True
        return False


class _JobHeartbeat:
    """Re-publishes the latest state periodically so the backend lease stays fresh."""

    def __init__(self, sink: EventSink, interval: float) -> None:
        self.sink = sink
        self.interval = interval
        self.latest: DetectionEvent | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="job-heartbeat", daemon=True)

    def __enter__(self) -> _JobHeartbeat:
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            latest = self.latest
            if latest is not None:
                try:
                    self.sink.publish(latest.model_copy(update={
                        "event_id": uuid4(), "timestamp": datetime.now(UTC),
                    }), required=False)
                except Exception:
                    logger.warning("Heartbeat event could not be published", exc_info=True)


PipelineFactory = Callable[[Settings], Any]


def _default_pipeline_factory(settings: Settings) -> Any:
    from app.workers.detection_pipeline import DetectionPipeline

    return DetectionPipeline(settings)


def _default_model_preloader(settings: Settings, model_key: str, allow_download: bool) -> None:
    from app.services.model_loader import ModelLoader

    ModelLoader(settings).load(model_key, settings.ai_device, allow_download=allow_download)


class DetectionJobProcessor:
    def __init__(
        self, settings: Settings, store: ArtifactStore, *,
        pipeline_factory: PipelineFactory = _default_pipeline_factory,
        model_preloader: Callable[[Settings, str, bool], None] = _default_model_preloader,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.settings = settings
        self.store = store
        self.pipeline_factory = pipeline_factory
        self.model_preloader = model_preloader
        self.sleep = sleep

    def handle(self, body: bytes, attempt: int, sink: EventSink) -> Settlement:
        try:
            command = DetectionCommand.model_validate_json(body)
        except ValidationError as error:
            return self._reject_invalid(body, error, sink)
        logger.info("Received job %s (model %s, %s, attempt %d)", command.job_id, command.model_key,
                    command.source_type.value, attempt)
        progress: dict[str, int] = {"value": 0}
        try:
            existing = self.store.find_completed(command.job_id)
            if existing is not None:
                logger.info("Job %s already has stored artifacts; republishing completion", command.job_id)
                sink.publish(self._completed_from_manifest(command, existing), required=True)
                return Settlement(Disposition.ACK)
            permanent = self._preflight(command)
            if permanent is not None:
                self._publish_failure(sink, command.job_id, progress["value"], permanent)
                return Settlement(Disposition.ACK, error_code=permanent.code)
            self._run(command, sink, progress)
            return Settlement(Disposition.ACK)
        except Exception as error:
            failure = classify(error)
            logger.warning("Job %s attempt %d failed: %s (%s)", command.job_id, attempt, failure.code,
                           type(error).__name__)
            if failure.retryable and attempt < self.settings.job_max_retries:
                delay = min(self.settings.worker_retry_backoff_seconds * (2 ** (attempt - 1)), 300)
                return Settlement(Disposition.RETRY, retry_delay_seconds=delay, error_code=failure.code)
            final = failure if not failure.retryable else FailureInfo(
                failure.code, f"{failure.message} Gave up after {attempt} attempt(s).", True)
            try:
                self._publish_failure(sink, command.job_id, progress["value"], final)
            except Exception:
                logger.error("FAILED event for job %s could not be published", command.job_id, exc_info=True)
                return Settlement(Disposition.RETRY if attempt < self.settings.job_max_retries
                                  else Disposition.DEAD_LETTER, error_code=final.code)
            return Settlement(Disposition.ACK if not failure.retryable else Disposition.DEAD_LETTER,
                              error_code=final.code)

    def _preflight(self, command: DetectionCommand) -> FailureInfo | None:
        spec = get_model_spec(command.model_key)
        if spec is None:
            return FailureInfo("UNSUPPORTED_MODEL", "The requested model is not supported by this worker.", False)
        status = inspect_model(self.settings.model_cache_dir, spec)
        if status.status == CacheStatus.NOT_CACHED and not self.settings.worker_allow_model_download:
            return FailureInfo("MODEL_NOT_PREPARED",
                               f"{spec.weights_filename} is not prepared on this worker. Run "
                               f"'python -m app.cli models prepare --model {spec.model_key}' on the worker.", False)
        # Load before downloading/decoding the video so model problems fail fast; the
        # pipeline then reuses the process-wide model cache entry.
        self.model_preloader(self.settings, spec.model_key, self.settings.worker_allow_model_download)
        return None

    def _run(self, command: DetectionCommand, sink: EventSink, progress: dict[str, int]) -> None:
        throttle = ProgressThrottle(self.settings.worker_progress_min_step,
                                    self.settings.worker_progress_interval_seconds)
        self.settings.temp_dir.mkdir(parents=True, exist_ok=True)
        work_root = Path(tempfile.mkdtemp(prefix=f"job-{command.job_id}-", dir=self.settings.temp_dir.resolve()))
        try:
            with _JobHeartbeat(sink, self.settings.worker_heartbeat_seconds) as heartbeat:
                def forward(event: ProgressEvent) -> None:
                    stage = {
                        ProgressStage.DOWNLOADING: WorkerJobStatus.DOWNLOADING,
                        ProgressStage.DETECTING: WorkerJobStatus.DETECTING,
                        ProgressStage.ENCODING: WorkerJobStatus.ENCODING,
                    }.get(event.stage)
                    if stage is None:
                        return  # pipeline COMPLETED/FAILED are not job outcomes: storage comes first
                    value = min(event.progress, PIPELINE_PROGRESS_CEILING)
                    progress["value"] = max(progress["value"], value)
                    message = DetectionEvent(
                        job_id=command.job_id, status=stage, progress=progress["value"],
                        processed_frames=event.processed_frames, total_frames=event.total_frames,
                        message=sanitize_message(event.message) if event.message else None,
                    )
                    heartbeat.latest = message
                    if throttle.should_publish(stage, progress["value"]):
                        sink.publish(message, required=False)

                job_settings = self.settings.model_copy(update={"output_dir": work_root / "outputs"})
                result = self.pipeline_factory(job_settings).process_video(
                    self._request(command), on_progress=forward,
                )
                if result.model_key != command.model_key:
                    raise VideoProcessingError("The pipeline loaded a different model than requested.")
                uploading = DetectionEvent(job_id=command.job_id, status=WorkerJobStatus.UPLOADING,
                                           progress=UPLOADING_PROGRESS,
                                           processed_frames=result.statistics.total_frames_processed,
                                           message="Uploading result artifacts")
                progress["value"] = UPLOADING_PROGRESS
                heartbeat.latest = uploading
                sink.publish(uploading, required=False)
                keys = self.store.keys_for(command.job_id)
                manifest = self._manifest(command, result, keys.video, keys.result)
                self.store.store(command.job_id, Path(result.output.video_path), manifest)
            sink.publish(self._completed_from_manifest(command, manifest), required=True)
            logger.info("Job %s completed: %d frames", command.job_id, result.statistics.total_frames_processed)
        finally:
            shutil.rmtree(work_root, ignore_errors=True)

    def _request(self, command: DetectionCommand) -> DetectionRequest:
        source = command.source
        if command.source_type == SourceType.LOCAL_FILE:
            source = str((self.settings.local_input_dir / command.source).resolve())
        return DetectionRequest(
            source=source, source_type=command.source_type, model_key=command.model_key,
            confidence=float(command.confidence), image_size=command.image_size,
            classes=list(command.classes),
        )

    @staticmethod
    def _manifest(command: DetectionCommand, result: Any, video_key: str, result_key: str) -> dict[str, Any]:
        """Stored result.json: actual measured values, object keys, and no local paths."""
        data = json.loads(result.model_dump_json(by_alias=True))
        data.pop("output", None)
        data["schemaVersion"] = 1
        data["jobId"] = str(command.job_id)
        data["artifacts"] = {"outputVideoKey": video_key, "resultJsonKey": result_key}
        data["completedAt"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        return data

    @staticmethod
    def _completed_from_manifest(command: DetectionCommand, manifest: dict[str, Any]) -> DetectionEvent:
        try:
            statistics = manifest["statistics"]
            artifacts = manifest["artifacts"]
            return DetectionEvent(
                job_id=command.job_id, status=WorkerJobStatus.COMPLETED, progress=100,
                processed_frames=statistics["totalFramesProcessed"],
                total_frames=statistics["totalFramesProcessed"],
                message="Annotated video and result metadata are stored",
                model_key=manifest["modelKey"],
                result=EventResult(
                    output_video_key=artifacts["outputVideoKey"], result_json_key=artifacts["resultJsonKey"],
                    total_frames=statistics["totalFramesProcessed"],
                    processing_time_ms=manifest["processingTimeMs"],
                    detection_summary=statistics["detectionsByClass"],
                ),
            )
        except (KeyError, TypeError, ValidationError) as error:
            raise ArtifactStorageError("The stored result manifest is incomplete.") from error

    @staticmethod
    def _publish_failure(sink: EventSink, job_id: UUID, progress: int, failure: FailureInfo) -> None:
        sink.publish(DetectionEvent(
            job_id=job_id, status=WorkerJobStatus.FAILED, progress=min(progress, 99),
            message="Detection failed",
            error=EventError(code=failure.code, message=failure.message, retryable=failure.retryable),
        ), required=True)

    def _reject_invalid(self, body: bytes, error: ValidationError, sink: EventSink) -> Settlement:
        """Malformed commands are dead-lettered; a FAILED event is sent when the job is identifiable."""
        fields = sorted({".".join(str(part) for part in item["loc"]) for item in error.errors()})
        logger.error("Rejecting an invalid detection command (fields: %s)", ", ".join(fields) or "body")
        job_id = _extract_job_id(body)
        if job_id is not None:
            try:
                self._publish_failure(sink, job_id, 0, FailureInfo(
                    "INVALID_COMMAND", "The detection command was invalid: " + ", ".join(fields)[:400], False))
            except Exception:
                logger.warning("FAILED event for invalid command could not be published", exc_info=True)
        return Settlement(Disposition.DEAD_LETTER, error_code="INVALID_COMMAND")


def _extract_job_id(body: bytes) -> UUID | None:
    try:
        value = json.loads(body).get("jobId")
        return UUID(str(value)) if value else None
    except Exception:
        return None
