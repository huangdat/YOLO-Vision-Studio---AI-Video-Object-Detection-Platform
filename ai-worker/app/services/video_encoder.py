"""FFmpeg H.264 export with validation and atomic, non-overwriting publication."""

from __future__ import annotations

import json
import logging
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any
from uuid import uuid4

from app.config.settings import Settings
from app.core.exceptions import VideoEncodingError

logger = logging.getLogger(__name__)


class VideoEncoder:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def encode(self, input_path: Path, output_path: Path) -> Path:
        source = Path(input_path).resolve()
        destination = Path(output_path).resolve()
        if not source.is_file() or source.stat().st_size == 0:
            raise VideoEncodingError("The intermediate video is missing or empty.")
        if destination.exists() or Path(output_path).is_symlink():
            raise VideoEncodingError("The output video already exists; it will not be overwritten.")
        if destination.suffix.lower() != ".mp4":
            raise VideoEncodingError("The final video filename must use the .mp4 extension.")
        ffmpeg = self._executable(self.settings.ffmpeg_path, "FFmpeg")
        ffprobe = self._executable(self.settings.ffprobe_path, "FFprobe")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.parent / f".{destination.stem}.{uuid4().hex}.partial.mp4"
        command = [
            ffmpeg, "-nostdin", "-v", "error", "-xerror", "-n", "-i", str(source),
            "-map", "0:v:0", "-an", "-sn", "-dn",
            # OpenCV MJPEG intermediates use full-range YUV. Convert sample levels
            # as well as the range tag; otherwise H.264 may still probe as yuvj420p.
            "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2,scale=in_range=auto:out_range=tv,format=yuv420p",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-pix_fmt", "yuv420p", "-color_range", "tv",
            "-threads", str(self.settings.cpu_threads),
            "-movflags", "+faststart", str(temporary),
        ]
        try:
            self._run(command, "FFmpeg encoding")
            if not temporary.is_file() or temporary.stat().st_size == 0:
                raise VideoEncodingError("FFmpeg did not create a nonempty output video.")
            self._verify(temporary, ffmpeg, ffprobe)
            # A hard link atomically creates a new destination and fails if another
            # invocation created it meanwhile. Both files reside on the same filesystem.
            try:
                os.link(temporary, destination)
            except FileExistsError as error:
                raise VideoEncodingError("The output video already exists; it will not be overwritten.") from error
            except OSError as error:
                raise VideoEncodingError("The filesystem could not publish the output video atomically.") from error
            logger.info("H.264 video encoding completed (%d bytes)", destination.stat().st_size)
            return destination
        except (KeyboardInterrupt, SystemExit, VideoEncodingError):
            raise
        except Exception as error:
            raise VideoEncodingError("The video could not be encoded.") from error
        finally:
            temporary.unlink(missing_ok=True)

    def _verify(self, video: Path, ffmpeg: str, ffprobe: str) -> None:
        probe = self._run([
            ffprobe, "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=codec_name,pix_fmt,width,height,nb_frames,duration:format=duration",
            "-of", "json", str(video),
        ], "FFprobe output verification")
        try:
            metadata = json.loads(probe.stdout)
            stream = metadata["streams"][0]
            duration = stream.get("duration") or metadata.get("format", {}).get("duration")
            frame_count = stream.get("nb_frames")
            readable_frames = self._positive_float(frame_count) or self._positive_float(duration)
            if (stream.get("codec_name") != "h264" or stream.get("pix_fmt") != "yuv420p"
                    or int(stream.get("width", 0)) <= 0 or int(stream.get("height", 0)) <= 0
                    or not readable_frames):
                raise ValueError("invalid output stream")
        except (ValueError, TypeError, KeyError, IndexError, AttributeError) as error:
            raise VideoEncodingError("The encoded file is not a readable H.264/yuv420p video.") from error
        # Probe metadata alone does not prove that the encoded frames decode. Fail
        # on a decoding error anywhere in the video, rather than checking only a header.
        self._run([
            ffmpeg, "-nostdin", "-v", "error", "-xerror", "-i", str(video),
            "-map", "0:v:0", "-an", "-f", "null", "-",
        ], "FFmpeg decoding verification")

    def _run(self, command: list[str], operation: str) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(
                command, capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=self.settings.processing_timeout_seconds, check=False, shell=False,
            )
        except subprocess.TimeoutExpired as error:
            raise VideoEncodingError(f"{operation} exceeded its configured timeout.") from error
        except OSError as error:
            raise VideoEncodingError(f"{operation} could not start.") from error
        if result.returncode != 0:
            detail = re.sub(r"https?://\S+", "[remote URL]", result.stderr or "")
            detail = " ".join(detail.split())[-1200:]
            raise VideoEncodingError(f"{operation} failed" + (f": {detail}" if detail else "."))
        return result

    @staticmethod
    def _executable(configured_path: str, display_name: str) -> str:
        executable = shutil.which(configured_path)
        if executable is None:
            raise VideoEncodingError(f"{display_name} is unavailable; configure its executable path or PATH.")
        return executable

    @staticmethod
    def _positive_float(value: Any) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) and number > 0 else None
