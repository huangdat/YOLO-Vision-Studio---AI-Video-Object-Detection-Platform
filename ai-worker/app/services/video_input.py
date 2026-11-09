"""Probe source videos and normalize codecs that OpenCV's bundled FFmpeg cannot decode.

The opencv-python wheels ship their own FFmpeg build. It includes FFmpeg's native
``av1`` decoder, which only works with hardware acceleration, but no software AV1
decoder (dav1d or libaom). YouTube often serves AV1, so on CPU hosts OpenCV opens the
file but every ``read()`` fails. The system FFmpeg in the worker image does decode AV1
in software (libdav1d), so such inputs are converted to H.264/yuv420p before inference.
Inputs that OpenCV already reads are used unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib
import json
import logging
import math
from pathlib import Path
import subprocess
from typing import Any
from uuid import uuid4

from app.config.settings import Settings
from app.core.exceptions import (
    UnsupportedVideoCodecError, VideoLimitExceededError, VideoNormalizationError, VideoProbeError,
    VideoProcessingError, VideoStreamMissingError,
)

logger = logging.getLogger(__name__)

_PROBE_TIMEOUT_SECONDS = 60.0
# -fs stops writing at the limit and still exits successfully; treat output that
# reaches the limit as truncated rather than as a complete conversion.
_SIZE_LIMIT_MARGIN = 0.99


@dataclass(frozen=True)
class VideoStreamInfo:
    codec: str
    container: str
    width: int
    height: int
    pixel_format: str | None
    duration_seconds: float | None


@dataclass(frozen=True)
class PreparedVideo:
    path: Path
    source: VideoStreamInfo
    normalized: bool


class VideoInputPreparer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def prepare(self, source: Path, work_dir: Path) -> PreparedVideo:
        """Return a path OpenCV can decode: the source itself, or a normalized copy in work_dir."""
        source = Path(source)
        info = self.probe(source)
        if self.opencv_can_read(source):
            logger.info(
                "Video input is directly decodable (codec %s, container %s, %dx%d)",
                info.codec, info.container, info.width, info.height,
            )
            return PreparedVideo(path=source, source=info, normalized=False)
        logger.info(
            "OpenCV cannot decode codec %s (%s); normalizing to H.264 with software decoding",
            info.codec, info.pixel_format or "unknown pixel format",
        )
        normalized = self.normalize(source, Path(work_dir))
        if not self.opencv_can_read(normalized):
            normalized.unlink(missing_ok=True)
            raise UnsupportedVideoCodecError(
                f"The video codec ({info.codec}) could not be decoded into readable frames."
            )
        return PreparedVideo(path=normalized, source=info, normalized=True)

    def probe(self, path: Path) -> VideoStreamInfo:
        command = [
            self.settings.ffprobe_path, "-v", "error",
            "-show_entries",
            "stream=codec_type,codec_name,width,height,pix_fmt,duration:"
            "stream_disposition=attached_pic:format=format_name,duration",
            "-of", "json", str(path),
        ]
        completed = self._run(
            command, min(_PROBE_TIMEOUT_SECONDS, self.settings.processing_timeout_seconds), "probe",
        )
        if completed.returncode != 0:
            raise VideoProbeError("The input is not a readable media file; it may be corrupt or incomplete.")
        try:
            data = json.loads(completed.stdout or "{}")
            streams = data.get("streams") or []
            container = str((data.get("format") or {}).get("format_name") or "unknown")
            format_duration = (data.get("format") or {}).get("duration")
        except (ValueError, AttributeError) as error:
            raise VideoProbeError("The media inspection returned invalid metadata.") from error
        video = next((
            stream for stream in streams
            if isinstance(stream, dict) and stream.get("codec_type") == "video"
            and not (stream.get("disposition") or {}).get("attached_pic")
        ), None)
        if video is None:
            raise VideoStreamMissingError("The input contains no video stream (audio-only or unsupported file).")
        width, height = self._positive(video.get("width")), self._positive(video.get("height"))
        if not width or not height:
            raise VideoProbeError("The video stream has invalid frame dimensions.")
        if width * height > self.settings.max_frame_pixels:
            raise VideoLimitExceededError("Video dimensions exceed the configured pixel limit.")
        duration = self._positive(video.get("duration")) or self._positive(format_duration)
        if duration and duration > self.settings.max_video_duration_seconds:
            raise VideoLimitExceededError("The video exceeds the configured duration limit.")
        return VideoStreamInfo(
            codec=str(video.get("codec_name") or "unknown"), container=container,
            width=int(width), height=int(height),
            pixel_format=str(video["pix_fmt"]) if video.get("pix_fmt") else None,
            duration_seconds=duration,
        )

    def normalize(self, source: Path, work_dir: Path) -> Path:
        work_dir.mkdir(parents=True, exist_ok=True)
        output = work_dir / f"normalized-{uuid4().hex}.mp4"
        limit_bytes = int(self.settings.max_intermediate_size_mb * 1024 * 1024)
        command = [
            self.settings.ffmpeg_path, "-nostdin", "-v", "error", "-xerror",
            # Software decoding only: no GPU is assumed on the default CPU worker.
            "-hwaccel", "none", "-i", str(source),
            "-map", "0:v:0", "-an", "-sn", "-dn",
            # One second beyond the limit, so an unknown-duration source that is too long
            # is still rejected by the decoded-frame limit instead of being silently cut.
            "-t", f"{self.settings.max_video_duration_seconds + 1:g}",
            "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2,format=yuv420p",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
            "-threads", str(self.settings.cpu_threads), "-fs", str(limit_bytes),
            "-movflags", "+faststart", "-n", str(output),
        ]
        try:
            completed = self._run(command, self.settings.processing_timeout_seconds, "normalization")
            if completed.returncode != 0:
                raise VideoNormalizationError("The video could not be converted into a decodable format.")
            if not output.is_file() or output.stat().st_size == 0:
                raise VideoNormalizationError("Video normalization produced no output.")
            if output.stat().st_size >= limit_bytes * _SIZE_LIMIT_MARGIN:
                raise VideoLimitExceededError("The normalized video exceeds the configured size limit.")
        except BaseException:
            output.unlink(missing_ok=True)
            raise
        logger.info("Video normalization completed (%d bytes)", output.stat().st_size)
        return output

    def opencv_can_read(self, path: Path) -> bool:
        try:
            cv2 = importlib.import_module("cv2")
        except ImportError as error:
            raise VideoProcessingError("OpenCV is unavailable. Install the optional AI dependencies.") from error
        capture: Any = None
        try:
            capture = cv2.VideoCapture(str(path))
            if not capture.isOpened():
                return False
            readable, frame = capture.read()
            return bool(readable) and frame is not None and len(getattr(frame, "shape", ())) >= 2
        except Exception:
            return False
        finally:
            if capture is not None:
                try:
                    capture.release()
                except Exception:
                    logger.warning("Could not release a video compatibility capture", exc_info=True)

    def _run(self, command: list[str], timeout: float, operation: str) -> subprocess.CompletedProcess[str]:
        # Arguments are passed as a list (never a shell); stderr may contain local paths
        # and is deliberately not copied into error messages.
        tool = "FFprobe" if operation == "probe" else "FFmpeg"
        try:
            return subprocess.run(
                command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                encoding="utf-8", errors="replace", timeout=timeout, check=False, shell=False,
            )
        except FileNotFoundError as error:
            raise VideoProcessingError(f"{tool} is required for video {operation}; check its configured path.") from error
        except subprocess.TimeoutExpired as error:
            raise VideoLimitExceededError(f"Video {operation} exceeded the configured time limit.") from error
        except OSError as error:
            raise VideoProcessingError(f"{tool} could not be started for video {operation}.") from error

    @staticmethod
    def _positive(value: Any) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) and number > 0 else None
