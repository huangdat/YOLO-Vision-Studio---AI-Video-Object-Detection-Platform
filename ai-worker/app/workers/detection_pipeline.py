"""Standalone orchestration with no HTTP, database, or message-broker dependency."""

from __future__ import annotations

import logging
import os
from pathlib import Path
import tempfile
from time import perf_counter
from typing import TYPE_CHECKING
from uuid import uuid4

from app.config.settings import Settings, get_settings
from app.core.exceptions import DetectionEngineError, InvalidVideoSourceError, VideoProcessingError
from app.schemas.detection import DEFAULT_VEHICLE_CLASSES, DetectionRequest, SourceType
from app.schemas.progress import ProgressCallback, ProgressEvent, ProgressReporter, ProgressStage
from app.schemas.video import DetectionResult, InputVideoMetadata, VideoOutput
from app.services.model_registry import get_model_spec

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.services.video_encoder import VideoEncoder
    from app.services.video_input import VideoInputPreparer
    from app.services.video_processor import VideoProcessor
    from app.services.youtube_downloader import YouTubeDownloader


class DetectionPipeline:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        processor: VideoProcessor | None = None,
        downloader: YouTubeDownloader | None = None,
        encoder: VideoEncoder | None = None,
        input_preparer: VideoInputPreparer | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        # Construction is inexpensive. Optional AI imports happen only during execution.
        if processor is None:
            from app.services.video_processor import VideoProcessor

            processor = VideoProcessor(self.settings)
        if downloader is None:
            from app.services.youtube_downloader import YouTubeDownloader

            downloader = YouTubeDownloader(self.settings)
        if encoder is None:
            from app.services.video_encoder import VideoEncoder

            encoder = VideoEncoder(self.settings)
        if input_preparer is None:
            from app.services.video_input import VideoInputPreparer

            input_preparer = VideoInputPreparer(self.settings)
        self.processor = processor
        self.downloader = downloader
        self.encoder = encoder
        self.input_preparer = input_preparer

    def process_video(
        self, request: DetectionRequest, on_progress: ProgressCallback | None = None
    ) -> DetectionResult:
        request = DetectionRequest.model_validate(request)
        request = request.model_copy(update={
            "confidence": request.confidence if request.confidence is not None else self.settings.default_confidence,
            "image_size": request.image_size if request.image_size is not None else self.settings.default_image_size,
            "classes": request.classes if request.classes is not None else list(DEFAULT_VEHICLE_CLASSES),
            "device": request.device or self.settings.ai_device,
        })
        reporter = ProgressReporter(on_progress)
        execution_id = uuid4()
        started = perf_counter()
        published: list[Path] = []
        try:
            output_root = self.settings.output_dir.expanduser().resolve()
            temp_root = self.settings.temp_dir.expanduser().resolve()
            output_root.mkdir(parents=True, exist_ok=True)
            temp_root.mkdir(parents=True, exist_ok=True)
            output_path, metadata_path = self._output_paths(request, output_root, str(execution_id))
            local_source = self._local_source(request.source) if request.source_type == SourceType.LOCAL_FILE else None

            # Encode beside the final output so final publication never crosses filesystems.
            with tempfile.TemporaryDirectory(prefix=f".{execution_id}-", dir=output_root) as staging:
                stage_dir = Path(staging)
                with tempfile.TemporaryDirectory(prefix=f"detect-{execution_id}-", dir=temp_root) as working:
                    work_dir = Path(working)
                    if request.source_type == SourceType.YOUTUBE_URL:
                        reporter.emit(ProgressEvent(
                            stage=ProgressStage.DOWNLOADING, progress=0, message="Downloading authorized YouTube video"
                        ))
                        source_path = self.downloader.download(request.source, work_dir, on_progress=reporter.emit)
                        source_path = Path(source_path).resolve(strict=True)
                        if not source_path.is_relative_to(work_dir.resolve()):
                            raise InvalidVideoSourceError("The downloader returned a file outside its working directory")
                    else:
                        source_path = local_source
                    reporter.emit(ProgressEvent(
                        stage=ProgressStage.DETECTING, progress=15, message="Inspecting video and preparing detection"
                    ))
                    # Probe the codec and, only when OpenCV cannot decode it (for example AV1),
                    # convert it to H.264 inside the temporary working directory.
                    prepared = self.input_preparer.prepare(source_path, work_dir)
                    processed = self.processor.process(
                        prepared.path, work_dir / "annotated.avi", request, on_progress=reporter.emit
                    )
                    if processed.statistics.total_frames_processed == 0:
                        raise VideoProcessingError("No video frames were processed")
                    reporter.emit(ProgressEvent(
                        stage=ProgressStage.ENCODING, progress=85,
                        processed_frames=processed.statistics.total_frames_processed,
                        total_frames=processed.metadata.total_frames,
                        message="Encoding and verifying H.264 MP4",
                    ))
                    staged_video = stage_dir / output_path.name
                    self.encoder.encode(processed.path, staged_video)
                    if not staged_video.is_file() or staged_video.stat().st_size == 0:
                        raise VideoProcessingError("The encoder did not produce a nonempty output video")
                    duration_ms = max(0, round((perf_counter() - started) * 1000))
                    statistics = processed.statistics.model_copy(update={"processing_time_ms": duration_ms})
                    # Describe the model that was actually loaded, not merely the one requested.
                    spec = get_model_spec(statistics.model_key)
                    if spec is None:
                        raise VideoProcessingError("The loaded model is not in the approved registry")
                    result = DetectionResult(
                        execution_id=execution_id,
                        model_key=spec.model_key,
                        model_version=spec.version,
                        model_size=spec.model_size,
                        weights_filename=spec.weights_filename,
                        device=statistics.device,
                        input=InputVideoMetadata(
                            **processed.metadata.model_dump(), source_type=request.source_type
                        ),
                        output=VideoOutput(
                            video_filename=output_path.name, video_path=output_path, metadata_path=metadata_path
                        ),
                        statistics=statistics,
                        processing_time_ms=duration_ms,
                    )
                    (stage_dir / metadata_path.name).write_text(
                        result.model_dump_json(by_alias=True, indent=2), encoding="utf-8"
                    )
                    reporter.emit(ProgressEvent(
                        stage=ProgressStage.ENCODING, progress=99,
                        processed_frames=statistics.total_frames_processed,
                        total_frames=processed.metadata.total_frames,
                        message="Video verified; finalizing result metadata",
                    ))
                # Input/intermediate resources are closed and cleaned before publication.
                if request.output_path is None:
                    if output_path.parent.exists():
                        raise InvalidVideoSourceError("The execution output directory already exists")
                    stage_dir.rename(output_path.parent)
                else:
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    for staged, destination in (
                        (staged_video, output_path), (stage_dir / metadata_path.name, metadata_path)
                    ):
                        # Atomic create-if-absent on the same filesystem; never replace user files.
                        os.link(staged, destination)
                        published.append(destination)
            reporter.emit(ProgressEvent(
                stage=ProgressStage.COMPLETED, progress=100,
                processed_frames=result.statistics.total_frames_processed,
                total_frames=result.input.total_frames,
                message="Annotated video and JSON metadata are ready",
            ))
            logger.info("Detection execution %s completed: %s frames", execution_id, result.statistics.total_frames_processed)
            return result
        except BaseException as error:
            for path in published:
                path.unlink(missing_ok=True)
            reporter.emit(ProgressEvent(
                stage=ProgressStage.FAILED, progress=min(reporter.progress, 99),
                processed_frames=reporter.processed_frames,
                total_frames=reporter.total_frames,
                message="Detection execution failed; no successful output was published",
            ))
            logger.error("Detection execution %s failed (%s)", execution_id, type(error).__name__)
            if isinstance(error, (DetectionEngineError, KeyboardInterrupt, SystemExit)):
                raise
            raise VideoProcessingError("The detection execution could not be completed") from error

    def _local_source(self, source: str) -> Path:
        if source.lower().startswith(("http:", "https:", "file:", "ftp:")) or source.startswith(("\\\\", "//")):
            raise InvalidVideoSourceError("Local sources must be regular files inside AI_LOCAL_INPUT_DIR")
        try:
            path = Path(source).expanduser().resolve(strict=True)
        except (OSError, ValueError) as error:
            raise InvalidVideoSourceError("The local video file does not exist or cannot be opened") from error
        allowed_root = self.settings.local_input_dir.expanduser().resolve()
        if not path.is_relative_to(allowed_root) or not path.is_file():
            raise InvalidVideoSourceError("The local video must be a regular file inside AI_LOCAL_INPUT_DIR")
        return path

    @staticmethod
    def _output_paths(request: DetectionRequest, root: Path, execution_id: str) -> tuple[Path, Path]:
        if request.output_path is None:
            directory = root / execution_id
            return directory / "detected.mp4", directory / "result.json"
        candidate = request.output_path.expanduser()
        candidate = root / candidate if not candidate.is_absolute() and len(candidate.parts) == 1 else candidate
        output = candidate.resolve()
        if not output.is_relative_to(root) or output.suffix.lower() != ".mp4":
            raise InvalidVideoSourceError("Output must be an MP4 path inside AI_OUTPUT_DIR")
        metadata = output.with_suffix(".json")
        if output.exists() or metadata.exists():
            raise InvalidVideoSourceError("The requested output or metadata file already exists")
        return output, metadata
