"""Bounded, single-video YouTube downloads through yt-dlp's Python API."""

from __future__ import annotations

import logging
import math
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any
from urllib.parse import parse_qs, urlsplit

from app.config.settings import Settings
from app.core.exceptions import (
    InvalidVideoSourceError,
    VideoDownloadError,
    VideoLimitExceededError,
)
from app.schemas.progress import ProgressCallback, ProgressEvent, ProgressStage

logger = logging.getLogger(__name__)

_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}
_VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}\Z")
_VIDEO_SUFFIXES = {".mp4", ".webm", ".mkv"}


class _ProviderLogger:
    """Do not forward provider URLs, signatures, or request headers to application logs."""

    def debug(self, message: str) -> None:
        pass

    def warning(self, message: str) -> None:
        logger.warning("yt-dlp reported a download warning")

    def error(self, message: str) -> None:
        logger.warning("yt-dlp reported a download error")


class YouTubeDownloader:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @staticmethod
    def validate_url(url: str) -> str:
        """Return a canonical watch URL; never pass arbitrary remote URLs to yt-dlp."""
        if not isinstance(url, str):
            raise InvalidVideoSourceError("A YouTube video URL is required.")
        value = url.strip()
        if not value or any(character.isspace() or ord(character) < 32 for character in value):
            raise InvalidVideoSourceError("The YouTube URL is malformed.")
        try:
            parsed = urlsplit(value)
            port = parsed.port
        except ValueError as error:
            raise InvalidVideoSourceError("The YouTube URL is malformed.") from error
        if parsed.scheme not in {"http", "https"}:
            raise InvalidVideoSourceError("Only HTTP or HTTPS YouTube URLs are supported.")
        if parsed.username is not None or parsed.password is not None:
            raise InvalidVideoSourceError("Credentials in video URLs are not supported.")
        if port is not None and port != (443 if parsed.scheme == "https" else 80):
            raise InvalidVideoSourceError("The YouTube URL uses an unsupported port.")
        host = parsed.hostname or ""
        query = parse_qs(parsed.query, keep_blank_values=True)
        if "list" in query or "playlist" in parsed.path.lower().split("/"):
            raise InvalidVideoSourceError("Playlists are not supported; use a single-video URL.")
        if host == "youtu.be":
            segments = parsed.path.strip("/").split("/")
            identifier = segments[0] if len(segments) == 1 else ""
        elif host in _YOUTUBE_HOSTS:
            if parsed.path in {"/watch", "/watch/"}:
                identifiers = query.get("v", [])
                identifier = identifiers[0] if len(identifiers) == 1 else ""
            else:
                segments = parsed.path.strip("/").split("/")
                identifier = segments[1] if len(segments) == 2 and segments[0] in {"shorts", "embed"} else ""
        else:
            raise InvalidVideoSourceError("Only supported YouTube hostnames are accepted.")
        if not _VIDEO_ID.fullmatch(identifier):
            raise InvalidVideoSourceError("The URL must identify one valid YouTube video.")
        return f"https://www.youtube.com/watch?v={identifier}"

    def download(
        self,
        url: str,
        working_directory: Path,
        on_progress: ProgressCallback | None = None,
    ) -> Path:
        canonical_url = self.validate_url(url)
        try:
            from yt_dlp import YoutubeDL
        except ImportError as error:
            raise VideoDownloadError("YouTube support requires requirements-ai.txt to be installed.") from error

        root = Path(working_directory).resolve()
        root.mkdir(parents=True, exist_ok=True)
        directory = Path(tempfile.mkdtemp(prefix="youtube-", dir=root)).resolve()
        limit_bytes = int(self.settings.max_video_size_mb * 1024 * 1024)
        final_paths: list[Path] = []
        downloaded: dict[str, int] = {}
        expected_bytes = 0
        reported_progress = 0

        def emit(progress: int, message: str) -> None:
            nonlocal reported_progress
            reported_progress = max(reported_progress, min(15, max(0, progress)))
            if on_progress:
                on_progress(ProgressEvent(
                    stage=ProgressStage.DOWNLOADING,
                    progress=reported_progress,
                    message=message,
                ))

        def check_metadata(info: dict[str, Any], *, incomplete: bool = False) -> None:
            if not incomplete:
                self._validate_metadata(info, limit_bytes)

        def progress_hook(event: dict[str, Any]) -> None:
            if event.get("status") not in {"downloading", "finished"}:
                return
            filename = str(event.get("filename", "video")).removesuffix(".part")
            stream_info = event.get("info_dict") or {}
            key = str(stream_info.get("format_id") or filename)
            amount = self._positive_number(event.get("downloaded_bytes")) or 0
            downloaded[key] = max(downloaded.get(key, 0), int(amount))
            total_downloaded = sum(downloaded.values())
            advertised_total = self._positive_number(event.get("total_bytes"))
            if total_downloaded > limit_bytes or advertised_total is not None and advertised_total > limit_bytes:
                raise VideoLimitExceededError("The YouTube download exceeds the configured size limit.")
            denominator = expected_bytes or limit_bytes
            emit(int(14 * total_downloaded / max(1, denominator)), "Downloading the authorized YouTube video")

        def final_hook(filename: str) -> None:
            final_paths.append(Path(filename))

        options: dict[str, Any] = {
            **self.format_options(self.settings.max_download_height),
            "outtmpl": str(directory / "source.%(ext)s"),
            "merge_output_format": "mkv",
            "noplaylist": True,
            "overwrites": False,
            "quiet": True,
            "logger": _ProviderLogger(),
            "progress_hooks": [progress_hook],
            "post_hooks": [final_hook],
            "match_filter": check_metadata,
            "max_filesize": limit_bytes,
            "socket_timeout": 20,
            "retries": 2,
            "fragment_retries": 2,
            "concurrent_fragment_downloads": 1,
            "skip_unavailable_fragments": False,
            "cachedir": False,
            "geo_bypass": False,
            "js_runtimes": {
                self.settings.youtube_js_runtime: (
                    {"path": self.settings.youtube_js_runtime_path}
                    if self.settings.youtube_js_runtime_path else {}
                )
            },
        }
        if Path(self.settings.ffmpeg_path).is_file():
            options["ffmpeg_location"] = str(Path(self.settings.ffmpeg_path).resolve())
        try:
            emit(0, "Inspecting the authorized YouTube video")
            with YoutubeDL(options) as client:
                metadata = client.extract_info(canonical_url, download=False)
                self._validate_metadata(metadata, limit_bytes)
                expected_bytes = int(self._estimated_size(metadata) or 0)
                info = client.extract_info(canonical_url, download=True)
                self._validate_metadata(info, limit_bytes)
                # post_hooks run after every postprocessor and final file move. Prefer
                # their exact filename, then the final info dictionary; never glob a directory.
                candidates = [*reversed(final_paths)]
                if isinstance(info.get("filepath"), str):
                    candidates.append(Path(info["filepath"]))
                if not candidates:
                    candidates.append(Path(client.prepare_filename(info)))
                result = self._resolve_final_file(candidates, directory, limit_bytes)
            emit(15, "YouTube download completed")
            logger.info("YouTube video download completed (%d bytes)", result.stat().st_size)
            return result
        except BaseException as error:
            self._remove_incomplete(directory, root)
            if isinstance(error, (KeyboardInterrupt, SystemExit, InvalidVideoSourceError,
                                  VideoDownloadError, VideoLimitExceededError)):
                raise
            logger.warning("YouTube download failed (%s)", type(error).__name__)
            raise VideoDownloadError(
                "YouTube download failed. The video may be unavailable or restricted; "
                "check FFmpeg and the configured JavaScript runtime."
            ) from error

    @staticmethod
    def format_options(height: int) -> dict[str, Any]:
        """yt-dlp format selection: a real video stream, H.264 preferred at the best allowed height.

        By default yt-dlp ranks AV1 > VP9 > H.264 at equal resolution. OpenCV's bundled FFmpeg
        has no software AV1 decoder, so H.264 is preferred; resolution still ranks first, so
        quality is never lowered just to avoid AV1. Other codecs are normalized after download.
        """
        return {
            # [vcodec!=none] keeps audio-only formats from ever being selected as the input.
            "format": f"bv[height<={height}][vcodec!=none]+ba/b[height<={height}][vcodec!=none]",
            "format_sort": [f"res:{height}", "vcodec:h264"],
        }

    def _validate_metadata(self, info: Any, limit_bytes: int) -> None:
        if not isinstance(info, dict):
            raise VideoDownloadError("YouTube returned no usable video metadata.")
        if "entries" in info or info.get("_type") in {"playlist", "multi_video"}:
            raise InvalidVideoSourceError("Playlists are not supported.")
        if info.get("is_live") or info.get("was_live") or info.get("live_status") in {
            "is_live", "is_upcoming", "was_live", "post_live"
        }:
            raise InvalidVideoSourceError("Live streams and live-stream recordings are not supported.")
        if info.get("has_drm") or info.get("availability") in {
            "private", "premium_only", "subscriber_only", "needs_auth"
        }:
            raise VideoDownloadError("This video is restricted and cannot be downloaded by the worker.")
        duration = self._positive_number(info.get("duration"))
        if duration is None:
            raise VideoDownloadError("The video duration is unavailable; the download cannot be bounded safely.")
        if duration > self.settings.max_video_duration_seconds:
            raise VideoLimitExceededError("The YouTube video exceeds the configured duration limit.")
        estimate = self._estimated_size(info)
        if estimate is not None and estimate > limit_bytes:
            raise VideoLimitExceededError("The YouTube video exceeds the configured download-size limit.")

    @classmethod
    def _estimated_size(cls, info: dict[str, Any]) -> float | None:
        direct = cls._positive_number(info.get("filesize")) or cls._positive_number(info.get("filesize_approx"))
        formats = info.get("requested_formats") or []
        stream_sizes = [cls._positive_number(stream.get("filesize"))
                        or cls._positive_number(stream.get("filesize_approx"))
                        for stream in formats if isinstance(stream, dict)]
        known_total = sum(size for size in stream_sizes if size is not None)
        return max(direct or 0, known_total) or None

    @staticmethod
    def _positive_number(value: Any) -> float | None:
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0:
            return float(value)
        return None

    @staticmethod
    def _resolve_final_file(candidates: list[Path], directory: Path, limit_bytes: int) -> Path:
        for candidate in candidates:
            try:
                path = candidate.resolve(strict=True)
            except (OSError, RuntimeError):
                continue
            if not path.is_relative_to(directory):
                raise VideoDownloadError("The downloader returned a path outside its working directory.")
            if not path.is_file() or path.suffix.lower() not in _VIDEO_SUFFIXES:
                continue
            size = path.stat().st_size
            if size > limit_bytes:
                raise VideoLimitExceededError("The downloaded video exceeds the configured size limit.")
            if size > 0:
                return path
        raise VideoDownloadError("The download did not produce a finalized MP4, WebM, or MKV video.")

    @staticmethod
    def _remove_incomplete(directory: Path, root: Path) -> None:
        # Both paths come from our own mkdtemp operation; verify containment before
        # recursive removal so a provider path can never select a cleanup target.
        try:
            target = directory.resolve()
            if target == root or not target.is_relative_to(root):
                logger.error("Refused cleanup of a download directory outside the working root")
                return
            shutil.rmtree(directory)
        except OSError:
            logger.warning("Incomplete YouTube download files could not be removed")
