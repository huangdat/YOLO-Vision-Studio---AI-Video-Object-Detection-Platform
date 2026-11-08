import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from app.config.settings import Settings
from app.core.exceptions import VideoEncodingError
from app.services.video_encoder import VideoEncoder


@pytest.fixture
def encoding(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> SimpleNamespace:
    state = SimpleNamespace(
        source=tmp_path / "input.avi", destination=tmp_path / "detected.mp4", calls=[],
        encode_failure=False, decode_failure=False, empty=False, missing=False,
        probe={"streams": [{"codec_name": "h264", "pix_fmt": "yuv420p", "width": 64,
                             "height": 48, "nb_frames": "2", "duration": "1.0"}]},
        timeout=False,
    )
    state.source.write_bytes(b"intermediate")
    monkeypatch.setattr("app.services.video_encoder.shutil.which", lambda value: value)

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        state.calls.append((command, kwargs))
        if command[0] == "ffprobe":
            value = state.probe if isinstance(state.probe, str) else json.dumps(state.probe)
            return subprocess.CompletedProcess(command, 0, value, "")
        if command[-1] == "-":
            return subprocess.CompletedProcess(command, int(state.decode_failure), "", "corrupt frame")
        if not state.missing:
            Path(command[-1]).write_bytes(b"" if state.empty else b"encoded")
        if state.timeout:
            raise subprocess.TimeoutExpired(command, 1)
        return subprocess.CompletedProcess(command, int(state.encode_failure), "", "codec failure")

    monkeypatch.setattr("app.services.video_encoder.subprocess.run", run)
    return state


def test_encoding_uses_safe_h264_arguments_and_publishes_only_after_validation(
    encoding: SimpleNamespace,
) -> None:
    result = VideoEncoder(Settings()).encode(encoding.source, encoding.destination)

    assert result == encoding.destination
    assert result.read_bytes() == b"encoded"
    assert len(encoding.calls) == 3
    command, options = encoding.calls[0]
    assert command[command.index("-c:v") + 1] == "libx264"
    assert command[command.index("-pix_fmt") + 1] == "yuv420p"
    assert command[command.index("-color_range") + 1] == "tv"
    assert "scale=in_range=auto:out_range=tv" in command[command.index("-vf") + 1]
    assert command[command.index("-movflags") + 1] == "+faststart"
    assert command[command.index("-preset") + 1] == "fast"
    assert command[command.index("-crf") + 1] == "23"
    assert "-an" in command and "-n" in command and "-nostdin" in command
    assert options["shell"] is False
    assert options["timeout"] == 1800
    assert command[-1].endswith(".partial.mp4")
    assert encoding.calls[1][0][0] == "ffprobe"
    assert encoding.calls[2][0][-3:] == ["-f", "null", "-"]
    assert not list(result.parent.glob(".*.partial.mp4"))


def test_existing_destination_is_never_overwritten(encoding: SimpleNamespace) -> None:
    encoding.destination.write_bytes(b"unrelated")

    with pytest.raises(VideoEncodingError, match="already exists"):
        VideoEncoder(Settings()).encode(encoding.source, encoding.destination)

    assert encoding.destination.read_bytes() == b"unrelated"
    assert not encoding.calls


def test_missing_ffmpeg_is_reported_before_encoding(
    encoding: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.services.video_encoder.shutil.which", lambda value: None)

    with pytest.raises(VideoEncodingError, match="FFmpeg is unavailable"):
        VideoEncoder(Settings()).encode(encoding.source, encoding.destination)

    assert not encoding.destination.exists()


@pytest.mark.parametrize("failure", ["encode_failure", "decode_failure", "empty", "missing", "timeout"])
def test_failed_or_empty_encoding_never_leaves_a_final_video(
    encoding: SimpleNamespace, failure: str,
) -> None:
    setattr(encoding, failure, True)

    with pytest.raises(VideoEncodingError):
        VideoEncoder(Settings()).encode(encoding.source, encoding.destination)

    assert not encoding.destination.exists()
    assert not list(encoding.destination.parent.glob(".*.partial.mp4"))


@pytest.mark.parametrize("probe", [
    "invalid JSON", {}, {"streams": []},
    {"streams": [{"codec_name": "vp9", "pix_fmt": "yuv420p", "width": 64,
                  "height": 48, "duration": "1"}]},
    {"streams": [{"codec_name": "h264", "pix_fmt": "yuv444p", "width": 64,
                  "height": 48, "duration": "1"}]},
    {"streams": [{"codec_name": "h264", "pix_fmt": "yuvj420p", "width": 64,
                  "height": 48, "duration": "1"}]},
    {"streams": [{"codec_name": "h264", "pix_fmt": "yuv420p", "width": 0,
                  "height": 48, "duration": "1"}]},
    {"streams": [{"codec_name": "h264", "pix_fmt": "yuv420p", "width": 64,
                  "height": 48, "nb_frames": "0", "duration": "0"}]},
])
def test_invalid_probe_output_is_rejected_and_removed(
    encoding: SimpleNamespace, probe: object,
) -> None:
    encoding.probe = probe

    with pytest.raises(VideoEncodingError, match="readable H.264"):
        VideoEncoder(Settings()).encode(encoding.source, encoding.destination)

    assert not encoding.destination.exists()
    assert not list(encoding.destination.parent.glob(".*.partial.mp4"))


def test_atomic_publication_preserves_a_concurrently_created_file(
    encoding: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def competing_link(source: Path, destination: Path) -> None:
        destination.write_bytes(b"another execution")
        raise FileExistsError()

    monkeypatch.setattr("app.services.video_encoder.os.link", competing_link)

    with pytest.raises(VideoEncodingError, match="already exists"):
        VideoEncoder(Settings()).encode(encoding.source, encoding.destination)

    assert encoding.destination.read_bytes() == b"another execution"
    assert not list(encoding.destination.parent.glob(".*.partial.mp4"))


def test_encoder_error_diagnostics_do_not_expose_remote_url_signatures(
    encoding: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failed(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1, "", "Failed https://cdn.example/video?token=secret")

    monkeypatch.setattr("app.services.video_encoder.subprocess.run", failed)

    with pytest.raises(VideoEncodingError) as captured:
        VideoEncoder(Settings()).encode(encoding.source, encoding.destination)

    assert "secret" not in str(captured.value)
    assert "[remote URL]" in str(captured.value)


def test_missing_input_does_not_start_subprocesses(encoding: SimpleNamespace) -> None:
    encoding.source.unlink()

    with pytest.raises(VideoEncodingError, match="missing or empty"):
        VideoEncoder(Settings()).encode(encoding.source, encoding.destination)

    assert not encoding.calls
