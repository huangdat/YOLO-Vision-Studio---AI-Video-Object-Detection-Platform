"""Bounded, one-frame-at-a-time annotation and intermediate video generation."""

from collections import Counter
import importlib
import logging
import math
from pathlib import Path
import subprocess
from time import perf_counter
from typing import Any

from app.config.settings import Settings
from app.core.exceptions import (
    DetectionEngineError, InvalidVideoSourceError, VideoLimitExceededError, VideoProcessingError,
)
from app.schemas.detection import DetectionRequest, DetectionStatistics
from app.schemas.progress import ProgressCallback, ProgressEvent, ProgressStage
from app.schemas.video import ProcessingResult, VideoMetadata
from app.services.detection_service import DetectionService
from app.services.model_loader import ModelLoader

logger = logging.getLogger(__name__)
DEFAULT_CLASSES = [1, 2, 3, 5, 7]


class VideoProcessor:
    def __init__(
        self, settings: Settings, model_loader: ModelLoader | None = None,
        detection_service: DetectionService | None = None,
    ) -> None:
        self.settings = settings
        self.model_loader = model_loader or ModelLoader(settings)
        self.detection_service = detection_service or DetectionService()

    @staticmethod
    def _opencv() -> Any:
        try:
            return importlib.import_module("cv2")
        except ImportError as error:
            raise VideoProcessingError("OpenCV is unavailable. Install the optional AI dependencies.") from error

    def inspect(self, path: Path) -> VideoMetadata:
        path = Path(path)
        if not path.is_file():
            raise InvalidVideoSourceError("The local video file does not exist or is not a regular file.")
        try:
            size = path.stat().st_size
        except OSError as error:
            raise InvalidVideoSourceError("The local video file is not accessible.") from error
        if size <= 0:
            raise InvalidVideoSourceError("The video file is empty.")
        if size > self.settings.max_video_size_mb * 1024 * 1024:
            raise VideoLimitExceededError("The input video exceeds the configured size limit.")
        cv2 = self._opencv()
        capture: Any = None
        try:
            capture = cv2.VideoCapture(str(path))
            if not capture.isOpened():
                raise VideoProcessingError("The video could not be opened by the video decoder.")
            width = self._positive_number(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = self._positive_number(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
            if width and height and width * height > self.settings.max_frame_pixels:
                raise VideoLimitExceededError("Video dimensions exceed the configured pixel limit.")
            readable, frame = capture.read()
            if not readable or frame is None:
                raise VideoProcessingError("The video contains no readable frames.")
            if not hasattr(frame, "shape") or len(frame.shape) < 2:
                raise VideoProcessingError("The video decoder returned an invalid frame.")
            height, width = (int(value) for value in frame.shape[:2])
            if min(width, height) <= 0:
                raise VideoProcessingError("The video has invalid frame dimensions.")
            if width * height > self.settings.max_frame_pixels:
                raise VideoLimitExceededError("Video dimensions exceed the configured pixel limit.")
            raw_fps = self._positive_number(capture.get(cv2.CAP_PROP_FPS))
            fps = raw_fps or self.settings.fallback_fps
            raw_count = self._positive_number(capture.get(cv2.CAP_PROP_FRAME_COUNT))
            frame_count = int(raw_count) if raw_count and raw_count >= 1 else None
            duration = frame_count / fps if frame_count else None
            if duration and duration > self.settings.max_video_duration_seconds:
                raise VideoLimitExceededError("The video exceeds the configured duration limit.")
            return VideoMetadata(
                width=width, height=height, fps=fps, total_frames=frame_count,
                duration_seconds=duration, frame_count_estimated=True,
                fps_estimated=raw_fps is None,
            )
        except DetectionEngineError:
            raise
        except Exception as error:
            raise VideoProcessingError("Video metadata could not be read.") from error
        finally:
            if capture is not None:
                try:
                    capture.release()
                except Exception:
                    logger.warning("Could not release a video metadata capture", exc_info=True)

    def process(
        self, video_path: Path, output_path: Path, request: DetectionRequest,
        on_progress: ProgressCallback | None = None,
    ) -> ProcessingResult:
        started = perf_counter()
        video_path, output_path = Path(video_path), Path(output_path)
        if video_path.resolve() == output_path.resolve() or output_path.exists() or output_path.is_symlink():
            raise VideoProcessingError("The intermediate output must be a new file distinct from the input.")
        metadata = self.inspect(video_path)
        self._validate_source(video_path)
        confidence = request.confidence if request.confidence is not None else self.settings.default_confidence
        image_size = request.image_size if request.image_size is not None else self.settings.default_image_size
        classes = request.classes if request.classes is not None else DEFAULT_CLASSES.copy()
        device = request.device or self.settings.ai_device
        loaded = self.model_loader.load(request.model_key, device)
        cv2 = self._opencv()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        # MJPG and yuv420p output both need even dimensions; padding preserves edge pixels.
        writer_width = metadata.width + metadata.width % 2
        writer_height = metadata.height + metadata.height % 2
        writer: Any = None
        frames: Any = None
        processed = 0
        summary: Counter[str] = Counter()
        measured_time = 0.0
        measured_frames = 0
        last_progress = 14
        try:
            writer = cv2.VideoWriter(
                str(output_path), cv2.VideoWriter_fourcc(*"MJPG"), metadata.fps,
                (writer_width, writer_height),
            )
            if not writer.isOpened():
                raise VideoProcessingError("The intermediate video writer could not be initialized.")
            frames = self.detection_service.iter_frames(
                video_path, loaded, confidence, image_size, classes,
            )
            for detected in frames:
                if perf_counter() - started > self.settings.processing_timeout_seconds:
                    raise VideoLimitExceededError("Video processing exceeded the configured time limit.")
                processed += 1
                if processed / metadata.fps > self.settings.max_video_duration_seconds + 1e-6:
                    raise VideoLimitExceededError("Decoded frames exceed the configured duration limit.")
                image = detected.image
                if (getattr(image, "shape", None) != (metadata.height, metadata.width, 3)
                        or str(getattr(image, "dtype", "")) != "uint8"):
                    raise VideoProcessingError("Annotated frame dimensions or color format changed unexpectedly.")
                if writer_width != metadata.width or writer_height != metadata.height:
                    image = cv2.copyMakeBorder(
                        image, 0, writer_height - metadata.height, 0, writer_width - metadata.width,
                        cv2.BORDER_CONSTANT, value=(0, 0, 0),
                    )
                writer.write(image)
                summary.update(box.label for box in detected.boxes)
                if detected.inference_time_ms is not None:
                    measured_time += detected.inference_time_ms
                    measured_frames += 1
                if output_path.exists() and output_path.stat().st_size > self.settings.max_video_size_mb * 1024 * 1024:
                    raise VideoLimitExceededError("The intermediate video exceeds the configured size limit.")
                if metadata.total_frames:
                    fraction = min(processed / metadata.total_frames, 1.0)
                else:
                    fraction = processed / (processed + max(metadata.fps * 10, 1))
                progress = 15 + min(69, int(69 * fraction))
                if on_progress is not None and progress != last_progress:
                    on_progress(ProgressEvent(
                        stage=ProgressStage.DETECTING, progress=progress,
                        processed_frames=processed, total_frames=metadata.total_frames,
                        message="Processing video frames",
                    ))
                    last_progress = progress
            if not processed:
                raise VideoProcessingError("Inference produced no readable video frames.")
            writer.release()
            writer = None
            if not output_path.is_file() or output_path.stat().st_size <= 0:
                raise VideoProcessingError("The video writer produced no valid output file.")
            if output_path.stat().st_size > self.settings.max_video_size_mb * 1024 * 1024:
                raise VideoLimitExceededError("The intermediate video exceeds the configured size limit.")
            check = cv2.VideoCapture(str(output_path))
            try:
                readable, first = check.read() if check.isOpened() else (False, None)
                if not readable or first is None:
                    raise VideoProcessingError("The intermediate video cannot be decoded.")
            finally:
                check.release()
            if metadata.total_frames and processed != metadata.total_frames:
                logger.warning(
                    "Processed %d frames; the container estimate was %d",
                    processed, metadata.total_frames,
                )
            if on_progress is not None:
                on_progress(ProgressEvent(
                    stage=ProgressStage.DETECTING, progress=85,
                    processed_frames=processed, total_frames=metadata.total_frames,
                    message="Video annotation finished",
                ))
            return ProcessingResult(
                path=output_path, metadata=metadata,
                statistics=DetectionStatistics(
                    model_key=loaded.model_key, device=loaded.device, confidence=confidence,
                    image_size=image_size, classes=classes, total_frames_processed=processed,
                    total_detections=sum(summary.values()), detections_by_class=dict(summary),
                    processing_time_ms=max(0, round((perf_counter() - started) * 1000)),
                    average_inference_time_ms=(measured_time / measured_frames if measured_frames else None),
                ),
            )
        except BaseException as error:
            if writer is not None:
                self._release_writer(writer)
                writer = None
            try:
                output_path.unlink(missing_ok=True)
            except OSError:
                logger.warning("Could not remove an incomplete intermediate video", exc_info=True)
            if isinstance(error, (DetectionEngineError, KeyboardInterrupt, SystemExit)):
                raise
            raise VideoProcessingError("Video frame processing failed.") from error
        finally:
            if frames is not None and callable(getattr(frames, "close", None)):
                try:
                    frames.close()
                except Exception:
                    logger.warning("Could not close the frame processing iterator", exc_info=True)
            if writer is not None:
                self._release_writer(writer)

    @staticmethod
    def _release_writer(writer: Any) -> None:
        try:
            writer.release()
        except Exception:
            logger.warning("Could not release the intermediate video writer", exc_info=True)

    def _validate_source(self, path: Path) -> None:
        """Decode the source once so codec errors are not mistaken for clean inference EOF."""
        command = [
            self.settings.ffmpeg_path, "-nostdin", "-v", "error", "-xerror",
            "-err_detect", "explode", "-threads", str(self.settings.cpu_threads),
            "-i", str(path), "-map", "0:v:0", "-an", "-f", "null", "-",
        ]
        try:
            completed = subprocess.run(
                command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                text=True, check=False, timeout=self.settings.processing_timeout_seconds,
            )
        except FileNotFoundError as error:
            raise VideoProcessingError("FFmpeg is required to validate video input; check AI_FFMPEG_PATH.") from error
        except subprocess.TimeoutExpired as error:
            raise VideoLimitExceededError("Source video validation exceeded the configured time limit.") from error
        except OSError as error:
            raise VideoProcessingError("The source video decoder could not be started.") from error
        if completed.returncode != 0:
            error = subprocess.CalledProcessError(
                completed.returncode, command, stderr=completed.stderr,
            )
            raise VideoProcessingError("The input video is corrupt or unsupported by FFmpeg.") from error

    @staticmethod
    def _positive_number(value: Any) -> float | None:
        try:
            number = float(value)
            return number if math.isfinite(number) and number > 0 else None
        except (TypeError, ValueError):
            return None
