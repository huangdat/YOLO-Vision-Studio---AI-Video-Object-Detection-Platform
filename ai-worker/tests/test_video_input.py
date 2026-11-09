"""Codec probing and normalization for inputs OpenCV cannot decode (e.g. YouTube AV1)."""

import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from app.config.settings import Settings
from app.core.exceptions import (
    UnsupportedVideoCodecError, VideoLimitExceededError, VideoNormalizationError, VideoProbeError,
    VideoProcessingError, VideoStreamMissingError,
)
from app.services.video_input import VideoInputPreparer
from app.workers.job_processor import classify


def probe_json(*streams, container="matroska,webm", duration="10.0"):
    return json.dumps({"streams": list(streams), "format": {"format_name": container, "duration": duration}})


def video_stream(codec="av1", width=1280, height=720, **extra):
    return {"codec_type": "video", "codec_name": codec, "width": width, "height": height,
            "pix_fmt": "yuv420p", "disposition": {"attached_pic": 0}, **extra}


AUDIO = {"codec_type": "audio", "codec_name": "opus", "disposition": {"attached_pic": 0}}


class FakeTools:
    """Fake ffprobe/ffmpeg: records argument lists and creates the normalized output."""

    def __init__(self, probe_output="", probe_code=0, ffmpeg_code=0, output_bytes=b"normalized", raise_on=None):
        self.probe_output, self.probe_code = probe_output, probe_code
        self.ffmpeg_code, self.output_bytes, self.raise_on = ffmpeg_code, output_bytes, raise_on
        self.calls: list[tuple[list[str], dict]] = []

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        tool = "probe" if command[0].endswith("ffprobe") else "ffmpeg"
        if self.raise_on == tool:
            raise subprocess.TimeoutExpired(command, kwargs.get("timeout"))
        if tool == "probe":
            return SimpleNamespace(returncode=self.probe_code, stdout=self.probe_output, stderr="")
        output = Path(command[-1])
        if self.output_bytes is not None:
            output.write_bytes(self.output_bytes)
        return SimpleNamespace(returncode=self.ffmpeg_code, stdout="", stderr="error at /data/temp/secret.mkv")


@pytest.fixture
def settings(tmp_path):
    return Settings(temp_dir=tmp_path / "work", output_dir=tmp_path / "out", max_intermediate_size_mb=1,
                    max_video_duration_seconds=300, processing_timeout_seconds=120)


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "source.mkv"
    path.write_bytes(b"downloaded video bytes")
    return path


def preparer_with(monkeypatch, settings, tools, readable):
    """readable: callable(path) -> bool replacing the OpenCV compatibility check."""
    monkeypatch.setattr("app.services.video_input.subprocess.run", tools)
    preparer = VideoInputPreparer(settings)
    monkeypatch.setattr(preparer, "opencv_can_read", readable)
    return preparer


def test_directly_readable_h264_is_used_without_transcoding(monkeypatch, settings, source, tmp_path):
    tools = FakeTools(probe_json(video_stream("h264"), AUDIO, container="mov,mp4,m4a,3gp,3g2,mj2"))
    prepared = preparer_with(monkeypatch, settings, tools, lambda path: True).prepare(source, tmp_path / "w")
    assert prepared.path == source and prepared.normalized is False
    assert prepared.source.codec == "h264" and (prepared.source.width, prepared.source.height) == (1280, 720)
    assert len(tools.calls) == 1  # probe only; no FFmpeg run
    assert all(kwargs["shell"] is False for _, kwargs in tools.calls)


@pytest.mark.parametrize("codec", ["av1", "vp9"])
def test_undecodable_codec_is_normalized_to_h264_with_software_decoding(monkeypatch, settings, source, tmp_path, codec):
    tools = FakeTools(probe_json(video_stream(codec), AUDIO))
    work = tmp_path / "w"
    prepared = preparer_with(monkeypatch, settings, tools, lambda path: path != source).prepare(source, work)
    assert prepared.normalized is True and prepared.source.codec == codec
    assert prepared.path.parent == work and prepared.path.suffix == ".mp4" and prepared.path.is_file()
    command = tools.calls[1][0]
    assert command[command.index("-hwaccel") + 1] == "none"
    assert command[command.index("-c:v") + 1] == "libx264"
    assert command[command.index("-pix_fmt") + 1] == "yuv420p"
    assert command[command.index("-map") + 1] == "0:v:0" and "-an" in command
    assert command[command.index("-fs") + 1] == str(1024 * 1024)
    assert float(command[command.index("-t") + 1]) == 301
    assert tools.calls[1][1]["timeout"] == 120 and tools.calls[1][1]["shell"] is False


def test_audio_only_input_reports_missing_video_stream(monkeypatch, settings, source, tmp_path):
    tools = FakeTools(probe_json(AUDIO, container="ogg"))
    with pytest.raises(VideoStreamMissingError):
        preparer_with(monkeypatch, settings, tools, lambda path: True).prepare(source, tmp_path / "w")
    assert classify(VideoStreamMissingError("x")).code == "VIDEO_STREAM_MISSING"


def test_cover_art_alone_is_not_a_video_stream(monkeypatch, settings, source, tmp_path):
    cover = video_stream("mjpeg", disposition={"attached_pic": 1})
    tools = FakeTools(probe_json(AUDIO, cover, container="mp3"))
    with pytest.raises(VideoStreamMissingError):
        preparer_with(monkeypatch, settings, tools, lambda path: True).prepare(source, tmp_path / "w")


def test_ffprobe_failure_reports_invalid_content(monkeypatch, settings, source, tmp_path):
    tools = FakeTools("", probe_code=1)
    with pytest.raises(VideoProbeError) as caught:
        preparer_with(monkeypatch, settings, tools, lambda path: True).prepare(source, tmp_path / "w")
    failure = classify(caught.value)
    assert failure.code == "INVALID_VIDEO_CONTENT" and failure.retryable is False


@pytest.mark.parametrize("output", ["not json", json.dumps({"streams": [video_stream(width=0)]})])
def test_malformed_probe_metadata_is_rejected(monkeypatch, settings, source, tmp_path, output):
    with pytest.raises(VideoProbeError):
        preparer_with(monkeypatch, settings, FakeTools(output), lambda path: True).prepare(source, tmp_path / "w")


def test_missing_ffprobe_is_reported_clearly(monkeypatch, settings, source, tmp_path):
    def missing(command, **kwargs):
        raise FileNotFoundError(command[0])
    monkeypatch.setattr("app.services.video_input.subprocess.run", missing)
    with pytest.raises(VideoProcessingError, match="FFprobe is required"):
        VideoInputPreparer(settings).prepare(source, tmp_path / "w")


def test_ffmpeg_normalization_failure_is_classified_and_cleans_up(monkeypatch, settings, source, tmp_path):
    tools = FakeTools(probe_json(video_stream("av1")), ffmpeg_code=1, output_bytes=b"partial")
    work = tmp_path / "w"
    with pytest.raises(VideoNormalizationError) as caught:
        preparer_with(monkeypatch, settings, tools, lambda path: False).prepare(source, work)
    assert list(work.iterdir()) == []
    failure = classify(caught.value)
    assert failure.code == "VIDEO_NORMALIZATION_FAILED" and failure.retryable is False
    assert "/data" not in failure.message and "secret" not in failure.message


def test_normalized_output_that_is_still_unreadable_is_rejected_and_removed(monkeypatch, settings, source, tmp_path):
    tools = FakeTools(probe_json(video_stream("av1")))
    work = tmp_path / "w"
    with pytest.raises(UnsupportedVideoCodecError, match="av1") as caught:
        preparer_with(monkeypatch, settings, tools, lambda path: False).prepare(source, work)
    assert list(work.iterdir()) == []
    assert classify(caught.value).code == "UNSUPPORTED_VIDEO_CODEC"


def test_empty_normalized_output_is_a_failure(monkeypatch, settings, source, tmp_path):
    tools = FakeTools(probe_json(video_stream("av1")), output_bytes=b"")
    with pytest.raises(VideoNormalizationError):
        preparer_with(monkeypatch, settings, tools, lambda path: False).prepare(source, tmp_path / "w")


def test_normalized_output_reaching_the_size_limit_is_rejected(monkeypatch, settings, source, tmp_path):
    tools = FakeTools(probe_json(video_stream("av1")), output_bytes=b"x" * (1024 * 1024))
    work = tmp_path / "w"
    with pytest.raises(VideoLimitExceededError):
        preparer_with(monkeypatch, settings, tools, lambda path: False).prepare(source, work)
    assert list(work.iterdir()) == []


@pytest.mark.parametrize("stream, probe_extra", [
    (video_stream(width=7680, height=4320), {}),
    (video_stream(), {"duration": "301"}),
    (video_stream(duration="999"), {"duration": None}),
])
def test_probe_enforces_pixel_and_duration_limits(monkeypatch, settings, source, tmp_path, stream, probe_extra):
    tools = FakeTools(probe_json(stream, **probe_extra))
    with pytest.raises(VideoLimitExceededError):
        preparer_with(monkeypatch, settings, tools, lambda path: True).prepare(source, tmp_path / "w")
    assert len(tools.calls) == 1


@pytest.mark.parametrize("stage", ["probe", "ffmpeg"])
def test_probe_and_normalization_timeouts_are_limit_errors(monkeypatch, settings, source, tmp_path, stage):
    tools = FakeTools(probe_json(video_stream("av1")), raise_on=stage)
    work = tmp_path / "w"
    with pytest.raises(VideoLimitExceededError, match="time limit"):
        preparer_with(monkeypatch, settings, tools, lambda path: False).prepare(source, work)
    assert not work.exists() or list(work.iterdir()) == []


def test_interrupt_during_normalization_removes_partial_output(monkeypatch, settings, source, tmp_path):
    work = tmp_path / "w"

    def interrupted(command, **kwargs):
        if command[0].endswith("ffprobe"):
            return SimpleNamespace(returncode=0, stdout=probe_json(video_stream("av1")), stderr="")
        Path(command[-1]).write_bytes(b"partial")
        raise KeyboardInterrupt
    monkeypatch.setattr("app.services.video_input.subprocess.run", interrupted)
    preparer = VideoInputPreparer(settings)
    monkeypatch.setattr(preparer, "opencv_can_read", lambda path: False)
    with pytest.raises(KeyboardInterrupt):
        preparer.prepare(source, work)
    assert list(work.iterdir()) == []


# --- Real media: small fixtures generated locally with FFmpeg (no network) -------------

FFMPEG, FFPROBE = shutil.which("ffmpeg"), shutil.which("ffprobe")
real_media = pytest.mark.skipif(FFMPEG is None or FFPROBE is None, reason="FFmpeg/FFprobe are not installed")


def encoders() -> str:
    return subprocess.run([FFMPEG, "-hide_banner", "-encoders"], capture_output=True, text=True,
                          check=False).stdout if FFMPEG else ""


def make_fixture(path: Path, *codec_args: str, audio: bool = True, video: bool = True) -> Path:
    inputs = []
    if video:
        inputs += ["-f", "lavfi", "-i", "testsrc2=size=320x240:rate=10:duration=1"]
    if audio:
        inputs += ["-f", "lavfi", "-i", "sine=duration=1"]
    subprocess.run([FFMPEG, "-nostdin", "-v", "error", *inputs, *codec_args, str(path)], check=True, timeout=120)
    return path


@pytest.fixture
def real_preparer(tmp_path):
    pytest.importorskip("cv2")
    return VideoInputPreparer(Settings(temp_dir=tmp_path / "work", output_dir=tmp_path / "out",
                                       ffmpeg_path=FFMPEG or "ffmpeg", ffprobe_path=FFPROBE or "ffprobe"))


@real_media
@pytest.mark.parametrize("name, codec, args, encoder", [
    ("h264.mp4", "h264", ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac"], "libx264"),
    ("av1.mkv", "av1", ["-c:v", "libaom-av1", "-cpu-used", "8", "-crf", "50", "-b:v", "0",
                        "-pix_fmt", "yuv420p", "-c:a", "libopus"], "libaom-av1"),
    ("vp9.webm", "vp9", ["-c:v", "libvpx-vp9", "-deadline", "realtime", "-b:v", "200k", "-c:a", "libopus"],
     "libvpx-vp9"),
])
def test_real_fixture_is_prepared_into_readable_frames(real_preparer, tmp_path, name, codec, args, encoder):
    if encoder not in encoders():
        pytest.skip(f"FFmpeg lacks the {encoder} encoder needed to build this fixture")
    source = make_fixture(tmp_path / name, *args)
    directly_readable = real_preparer.opencv_can_read(source)
    work = tmp_path / "w"
    prepared = real_preparer.prepare(source, work)
    assert prepared.source.codec == codec and (prepared.source.width, prepared.source.height) == (320, 240)
    # Transcode only when OpenCV cannot read the source; never otherwise.
    assert prepared.normalized is (not directly_readable)
    assert real_preparer.opencv_can_read(prepared.path)
    if prepared.normalized:
        assert real_preparer.probe(prepared.path).codec == "h264"
        assert prepared.path.parent == work
    if codec == "h264":
        assert prepared.path == source


@real_media
def test_real_audio_only_file_is_rejected(real_preparer, tmp_path):
    source = make_fixture(tmp_path / "audio.m4a", "-c:a", "aac", video=False)
    with pytest.raises(VideoStreamMissingError):
        real_preparer.prepare(source, tmp_path / "w")


@real_media
def test_real_corrupt_file_is_rejected(real_preparer, tmp_path):
    valid = make_fixture(tmp_path / "valid.mp4", "-c:v", "libx264", "-pix_fmt", "yuv420p", audio=False)
    corrupt = tmp_path / "corrupt.mp4"
    corrupt.write_bytes(b"\x00\x00\x00\x18ftypmp42" + bytes(64) + valid.read_bytes()[-512:])
    with pytest.raises(VideoProbeError):
        real_preparer.prepare(corrupt, tmp_path / "w")
