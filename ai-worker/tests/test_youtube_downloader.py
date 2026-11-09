from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any

import pytest

from app.config.settings import Settings
from app.core.exceptions import InvalidVideoSourceError, VideoDownloadError, VideoLimitExceededError
from app.services.youtube_downloader import YouTubeDownloader


URL = "https://www.youtube.com/watch?v=abcdefghijk"


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    state = SimpleNamespace(
        metadata={"id": "abcdefghijk", "duration": 12, "ext": "webm"},
        options=None, calls=[], extension="webm", hooks=[], failure=None,
        final_size=20, reported_path=None, call_final_hook=True,
    )

    class FakeYoutubeDL:
        def __init__(self, options: dict[str, Any]) -> None:
            state.options = options

        def __enter__(self) -> "FakeYoutubeDL":
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def extract_info(self, url: str, *, download: bool) -> dict[str, Any]:
            state.calls.append((url, download))
            if not download:
                return state.metadata.copy()
            parent = Path(state.options["outtmpl"]).parent
            parent.joinpath("partial.webm.part").write_bytes(b"unfinished")
            if state.failure:
                raise state.failure
            for hook_event in state.hooks:
                state.options["progress_hooks"][0](hook_event)
            final = parent / f"source.{state.extension}"
            final.write_bytes(b"v" * state.final_size)
            if state.call_final_hook:
                state.options["post_hooks"][0](str(final))
            return {**state.metadata, "filepath": state.reported_path or str(final)}

        def prepare_filename(self, info: dict[str, Any]) -> str:
            return state.options["outtmpl"].replace("%(ext)s", info["ext"])

    monkeypatch.setitem(sys.modules, "yt_dlp", SimpleNamespace(YoutubeDL=FakeYoutubeDL))
    return state


@pytest.mark.parametrize("url", [
    URL,
    "http://youtube.com/watch?v=abcdefghijk&t=5",
    "https://youtu.be/abcdefghijk",
    "https://m.youtube.com/shorts/abcdefghijk",
    "https://www.youtube.com/embed/abcdefghijk",
])
def test_supported_urls_are_canonicalized_to_one_video(url: str) -> None:
    assert YouTubeDownloader.validate_url(url) == URL


@pytest.mark.parametrize("url", [
    "not a URL", "ftp://youtube.com/watch?v=abcdefghijk",
    "https://example.com/watch?v=abcdefghijk", "https://youtube.com.example.org/watch?v=abcdefghijk",
    "https://user:secret@youtube.com/watch?v=abcdefghijk",
    "https://youtube.com:8080/watch?v=abcdefghijk", "https://youtube.com/watch?v=short",
    "https://youtube.com/watch?v=abcdefghijk&v=lmnopqrstuv",
    "https://youtube.com/watch?v=abcdefghijk&list=PLexample",
    "https://youtube.com/playlist?list=PLexample", "https://youtube.com/live/abcdefghijk",
    "https://youtu.be/abcdefghijk/extra", "https://youtube.com/watch?v=abcdefghijk\n&other=bad",
])
def test_invalid_or_unsupported_sources_are_rejected(url: str) -> None:
    with pytest.raises(InvalidVideoSourceError):
        YouTubeDownloader.validate_url(url)


def test_download_returns_final_mkv_path_after_postprocessing(
    provider: SimpleNamespace, tmp_path: Path,
) -> None:
    provider.extension = "mkv"
    # A previous container name must not defeat the explicit final-file hook.
    provider.reported_path = str(tmp_path / "missing.webm")
    downloader = YouTubeDownloader(Settings())

    result = downloader.download("https://youtu.be/abcdefghijk", tmp_path)

    assert result.name == "source.mkv"
    assert result.is_relative_to(tmp_path)
    assert result.stat().st_size == provider.final_size
    assert provider.calls == [(URL, False), (URL, True)]
    assert provider.options["format"] == "bv[height<=720][vcodec!=none]+ba/b[height<=720][vcodec!=none]"
    # H.264 is preferred at the best allowed resolution: OpenCV cannot decode AV1 on CPU.
    assert provider.options["format_sort"] == ["res:720", "vcodec:h264"]
    assert provider.options["noplaylist"] is True
    assert provider.options["geo_bypass"] is False
    assert provider.options["overwrites"] is False


def test_successful_downloads_have_independent_working_directories(
    provider: SimpleNamespace, tmp_path: Path,
) -> None:
    downloader = YouTubeDownloader(Settings())
    first = downloader.download(URL, tmp_path)
    second = downloader.download(URL, tmp_path)

    assert first.parent != second.parent
    assert first.is_file() and second.is_file()


@pytest.mark.parametrize("metadata, expected", [
    ({"_type": "playlist", "entries": [], "duration": 20}, InvalidVideoSourceError),
    ({"is_live": True, "duration": 20}, InvalidVideoSourceError),
    ({"live_status": "is_upcoming", "duration": 20}, InvalidVideoSourceError),
    ({"was_live": True, "duration": 20}, InvalidVideoSourceError),
    ({"duration": 301}, VideoLimitExceededError),
    ({"duration": None}, VideoDownloadError),
    ({"duration": float("nan")}, VideoDownloadError),
    ({"duration": 20, "availability": "private"}, VideoDownloadError),
    ({"duration": 20, "has_drm": True}, VideoDownloadError),
    ({"duration": 20, "filesize": 201 * 1024 * 1024}, VideoLimitExceededError),
    ({"duration": 20, "requested_formats": [{"filesize": 110 * 1024 * 1024},
                                            {"filesize": 100 * 1024 * 1024}]}, VideoLimitExceededError),
])
def test_preflight_limits_and_restrictions_prevent_downloads(
    provider: SimpleNamespace, tmp_path: Path, metadata: dict[str, Any], expected: type[Exception],
) -> None:
    provider.metadata = metadata

    with pytest.raises(expected):
        YouTubeDownloader(Settings()).download(URL, tmp_path)

    assert provider.calls == [(URL, False)]
    assert list(tmp_path.iterdir()) == []


def test_downloaded_bytes_enforce_combined_stream_size(
    provider: SimpleNamespace, tmp_path: Path,
) -> None:
    provider.hooks = [
        {"status": "downloading", "downloaded_bytes": 60, "info_dict": {"format_id": "video"}},
        {"status": "downloading", "downloaded_bytes": 60, "info_dict": {"format_id": "audio"}},
    ]

    with pytest.raises(VideoLimitExceededError):
        YouTubeDownloader(Settings(max_video_size_mb=0.0001)).download(URL, tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_final_size_is_checked_even_without_progress_totals(
    provider: SimpleNamespace, tmp_path: Path,
) -> None:
    provider.final_size = 200

    with pytest.raises(VideoLimitExceededError):
        YouTubeDownloader(Settings(max_video_size_mb=0.0001)).download(URL, tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_progress_is_bounded_and_monotonic(provider: SimpleNamespace, tmp_path: Path) -> None:
    provider.metadata["filesize"] = 20
    provider.hooks = [
        {"status": "downloading", "filename": "source.webm.part", "downloaded_bytes": 10},
        {"status": "downloading", "filename": "source.webm.part", "downloaded_bytes": 5},
        {"status": "finished", "filename": "source.webm", "downloaded_bytes": 20},
    ]
    events = []

    YouTubeDownloader(Settings()).download(URL, tmp_path, events.append)

    assert [event.progress for event in events] == sorted(event.progress for event in events)
    assert all(event.stage == "DOWNLOADING" and 0 <= event.progress <= 15 for event in events)
    assert events[-1].progress == 15


def test_provider_failures_are_sanitized_and_partial_downloads_are_removed(
    provider: SimpleNamespace, tmp_path: Path,
) -> None:
    sentinel = tmp_path / "unrelated.txt"
    sentinel.write_text("preserve")
    provider.failure = RuntimeError("private provider URL with signature=secret")

    with pytest.raises(VideoDownloadError) as captured:
        YouTubeDownloader(Settings()).download(URL, tmp_path)

    assert "secret" not in str(captured.value)
    assert captured.value.__cause__ is provider.failure
    assert list(tmp_path.iterdir()) == [sentinel]


def test_interrupted_download_cleans_up_and_keeps_interrupt_semantics(
    provider: SimpleNamespace, tmp_path: Path,
) -> None:
    provider.failure = KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        YouTubeDownloader(Settings()).download(URL, tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_provider_cannot_return_a_path_outside_its_directory(
    provider: SimpleNamespace, tmp_path: Path,
) -> None:
    external = tmp_path / "unrelated.mp4"
    external.write_bytes(b"preserve")
    provider.call_final_hook = False
    provider.reported_path = str(external)

    with pytest.raises(VideoDownloadError, match="outside"):
        YouTubeDownloader(Settings()).download(URL, tmp_path)

    assert external.read_bytes() == b"preserve"
    assert list(tmp_path.iterdir()) == [external]


def test_unknown_or_empty_final_container_is_not_reported_as_success(
    provider: SimpleNamespace, tmp_path: Path,
) -> None:
    provider.extension = "part"

    with pytest.raises(VideoDownloadError, match="finalized"):
        YouTubeDownloader(Settings()).download(URL, tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_javascript_runtime_configuration_is_passed_without_shell_commands(
    provider: SimpleNamespace, tmp_path: Path,
) -> None:
    settings = Settings(youtube_js_runtime="deno", youtube_js_runtime_path="/tools/deno")

    YouTubeDownloader(settings).download(URL, tmp_path)

    assert provider.options["js_runtimes"] == {"deno": {"path": "/tools/deno"}}
    assert "exec_cmd" not in provider.options


def _select(formats: list[dict[str, Any]], height: int = 720) -> dict[str, Any]:
    """Run yt-dlp's real format selection offline with the downloader's options."""
    yt_dlp = pytest.importorskip("yt_dlp")
    info = {"id": "abcdefghijk", "title": "t", "formats": formats, "extractor": "youtube",
            "extractor_key": "Youtube", "webpage_url": "https://www.youtube.com/watch?v=abcdefghijk",
            "duration": 10}
    options = {**YouTubeDownloader.format_options(height), "quiet": True, "simulate": True}
    with yt_dlp.YoutubeDL(options) as client:
        return client.process_ie_result(info, download=False)


def _fmt(format_id: str, vcodec: str, acodec: str, height: int | None, ext: str, tbr: int = 1000) -> dict[str, Any]:
    entry: dict[str, Any] = {"format_id": format_id, "vcodec": vcodec, "acodec": acodec, "ext": ext,
                             "url": f"https://example.invalid/{format_id}", "protocol": "https", "tbr": tbr}
    if height:
        entry.update(height=height, width=height * 16 // 9, fps=30)
    return entry


_AUDIO = [_fmt("140", "none", "mp4a.40.2", None, "m4a", tbr=128), _fmt("251", "none", "opus", None, "webm", tbr=140)]


def test_format_selection_prefers_h264_over_av1_and_vp9_at_the_same_resolution() -> None:
    selected = _select([*_AUDIO,
                        _fmt("399", "av01.0.05M.08", "none", 720, "mp4", tbr=900),
                        _fmt("247", "vp9", "none", 720, "webm", tbr=1100),
                        _fmt("136", "avc1.4d401f", "none", 720, "mp4", tbr=1500),
                        _fmt("137", "avc1.640028", "none", 1080, "mp4", tbr=3000),
                        _fmt("160", "avc1.4d400c", "none", 144, "mp4", tbr=100)])
    assert selected["format_id"].split("+")[0] == "136"
    assert selected["height"] == 720 and selected["vcodec"].startswith("avc1")


def test_format_selection_keeps_resolution_instead_of_downgrading_to_h264() -> None:
    selected = _select([*_AUDIO, _fmt("399", "av01.0.05M.08", "none", 720, "mp4"),
                        _fmt("135", "avc1.4d401e", "none", 480, "mp4")])
    # AV1 at 720p is kept; the worker normalizes it after download instead of losing quality.
    assert selected["format_id"].split("+")[0] == "399"


def test_format_selection_never_accepts_audio_only_formats() -> None:
    with pytest.raises(Exception, match="not available"):
        _select(list(_AUDIO))
