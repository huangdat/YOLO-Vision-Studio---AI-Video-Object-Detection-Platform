from pathlib import Path
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.config.settings import Settings
from app.core.exceptions import InferenceError, VideoLimitExceededError, VideoProcessingError
from app.schemas.detection import DetectionBox, DetectionRequest, SourceType
from app.services.detection_service import DetectedFrame
from app.services.video_processor import VideoProcessor


class Frame:
    shape = (2, 4, 3)
    dtype = "uint8"


class Capture:
    def __init__(self, properties, *, opened=True, readable=True):
        self.properties = properties
        self.opened = opened
        self.readable = readable
        self.released = False

    def isOpened(self):
        return self.opened

    def get(self, key):
        return self.properties[key]

    def read(self):
        return (True, Frame()) if self.readable else (False, None)

    def release(self):
        self.released = True


class Writer:
    def __init__(self, path, *, opened=True):
        self.path = Path(path)
        self.opened = opened
        self.released = False
        self.frames = []
        self.path.write_bytes(b"header")

    def isOpened(self):
        return self.opened

    def write(self, image):
        self.frames.append(image)
        with self.path.open("ab") as output:
            output.write(b"frame")

    def release(self):
        self.released = True


class ClosingFrames:
    def __init__(self, frames, error=None):
        self.frames = iter(frames)
        self.error = error
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        try:
            return next(self.frames)
        except StopIteration:
            if self.error is not None:
                raise self.error
            raise

    def close(self):
        self.closed = True


@pytest.fixture
def environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    source = tmp_path / "input.mp4"
    source.write_bytes(b"generated-video-fixture")
    properties = {1: 4, 2: 2, 3: 10.0, 4: 3}
    captures = []
    writers = []

    def capture(path):
        instance = Capture(properties.copy())
        captures.append(instance)
        return instance

    def writer(path, codec, fps, dimensions):
        instance = Writer(path)
        instance.fps, instance.dimensions = fps, dimensions
        writers.append(instance)
        return instance

    cv2 = SimpleNamespace(
        CAP_PROP_FRAME_WIDTH=1, CAP_PROP_FRAME_HEIGHT=2, CAP_PROP_FPS=3,
        CAP_PROP_FRAME_COUNT=4, VideoCapture=capture, VideoWriter=writer,
        VideoWriter_fourcc=lambda *letters: 123,
    )
    loaded = SimpleNamespace(model_key="yolo26s", device="cpu")
    loader = SimpleNamespace(load=Mock(return_value=loaded))
    frames = ClosingFrames([DetectedFrame(Frame(), [], 2.0) for _ in range(3)])
    detection = SimpleNamespace(iter_frames=Mock(return_value=frames))
    settings = Settings(temp_dir=tmp_path, model_cache_dir=tmp_path / "models")
    processor = VideoProcessor(settings, loader, detection)
    monkeypatch.setattr(processor, "_opencv", lambda: cv2)
    monkeypatch.setattr(processor, "_validate_source", Mock())
    request = DetectionRequest(source_type=SourceType.LOCAL_FILE, source=str(source))
    return SimpleNamespace(
        processor=processor, source=source, output=tmp_path / "intermediate.avi", properties=properties,
        captures=captures, writers=writers, frames=frames, detection=detection, loader=loader,
        cv2=cv2, request=request, loaded=loaded,
    )


def test_inspects_dimensions_fps_estimated_count_and_duration(environment) -> None:
    context = environment

    metadata = context.processor.inspect(context.source)

    assert (metadata.width, metadata.height, metadata.fps) == (4, 2, 10)
    assert metadata.total_frames == 3
    assert metadata.duration_seconds == pytest.approx(0.3)
    assert metadata.frame_count_estimated
    assert not metadata.fps_estimated
    assert context.captures[0].released


def test_missing_fps_and_frame_count_are_handled_without_dividing_by_zero(environment) -> None:
    context = environment
    context.properties.update({3: float("nan"), 4: 0})

    metadata = context.processor.inspect(context.source)

    assert metadata.fps == 30
    assert metadata.fps_estimated
    assert metadata.total_frames is None
    assert metadata.duration_seconds is None


def test_unreadable_video_is_rejected_and_capture_is_released(environment) -> None:
    context = environment
    capture = Capture(context.properties, readable=False)
    context.cv2.VideoCapture = lambda path: capture

    with pytest.raises(VideoProcessingError, match="no readable frames"):
        context.processor.inspect(context.source)

    assert capture.released


def test_decoder_initialization_failure_is_wrapped_as_a_processing_error(environment) -> None:
    context = environment
    context.cv2.VideoCapture = Mock(side_effect=RuntimeError("decoder initialization failed"))

    with pytest.raises(VideoProcessingError, match="metadata could not be read") as failure:
        context.processor.inspect(context.source)

    assert isinstance(failure.value.__cause__, RuntimeError)


def test_video_duration_and_size_limits_are_enforced_before_loading_a_model(environment) -> None:
    context = environment
    context.processor.settings.max_video_duration_seconds = 0.1

    with pytest.raises(VideoLimitExceededError, match="duration"):
        context.processor.process(context.source, context.output, context.request)

    context.loader.load.assert_not_called()
    context.processor.settings.max_video_duration_seconds = 300
    context.processor.settings.max_video_size_mb = 0.000001
    with pytest.raises(VideoLimitExceededError, match="size"):
        context.processor.inspect(context.source)


def test_rejects_excessive_dimensions_before_reading_a_frame(environment) -> None:
    context = environment
    context.properties.update({1: 10000, 2: 10000})

    with pytest.raises(VideoLimitExceededError, match="pixel limit"):
        context.processor.inspect(context.source)

    assert context.captures[0].released


def test_processes_all_frames_and_accumulates_detections_without_tracking(environment) -> None:
    context = environment
    car = DetectionBox(class_id=2, label="car", confidence=0.9, xyxy=(0, 0, 2, 2))
    bus = DetectionBox(class_id=5, label="bus", confidence=0.8, xyxy=(0, 0, 2, 2))
    context.frames.frames = iter([
        DetectedFrame(Frame(), [car], 2), DetectedFrame(Frame(), [], None),
        DetectedFrame(Frame(), [car, bus], 4),
    ])
    events = []

    processed = context.processor.process(context.source, context.output, context.request, events.append)

    assert processed.path == context.output
    assert processed.statistics.total_frames_processed == 3
    assert processed.statistics.total_detections == 3
    assert processed.statistics.detections_by_class == {"car": 2, "bus": 1}
    assert processed.statistics.average_inference_time_ms == 3
    assert processed.statistics.classes == [1, 2, 3, 5, 7]
    assert processed.statistics.device == "cpu"
    assert len(context.writers[0].frames) == 3
    assert context.writers[0].fps == 10
    assert context.writers[0].dimensions == (4, 2)
    assert context.writers[0].released and context.frames.closed
    assert all(capture.released for capture in context.captures)
    assert [event.progress for event in events] == sorted(event.progress for event in events)
    assert events[-1].progress == 85
    assert all(event.progress < 100 for event in events)


def test_zero_detections_still_produce_a_video(environment) -> None:
    context = environment

    processed = context.processor.process(context.source, context.output, context.request)

    assert processed.statistics.total_frames_processed == 3
    assert processed.statistics.total_detections == 0
    assert processed.statistics.detections_by_class == {}
    assert context.output.is_file()


def test_writer_initialization_failure_removes_partial_output(environment) -> None:
    context = environment
    writer = Writer(context.output, opened=False)
    context.cv2.VideoWriter = lambda *arguments: writer
    # The fixture writer reserves the path; production initialization starts from a new path.
    context.output.unlink()

    with pytest.raises(VideoProcessingError, match="writer could not be initialized"):
        context.processor.process(context.source, context.output, context.request)

    assert writer.released
    assert not context.output.exists()


@pytest.mark.parametrize("failure", [InferenceError("inference failed"), KeyboardInterrupt()])
def test_failed_or_interrupted_inference_closes_resources_and_removes_partial_video(environment, failure) -> None:
    context = environment
    context.frames.error = failure

    with pytest.raises(type(failure)):
        context.processor.process(context.source, context.output, context.request)

    assert context.writers[0].released
    assert context.frames.closed
    assert not context.output.exists()


def test_unknown_frame_count_still_enforces_actual_decoded_duration(environment) -> None:
    context = environment
    context.properties.update({4: 0})
    context.processor.settings.max_video_duration_seconds = 0.15

    with pytest.raises(VideoLimitExceededError, match="Decoded frames"):
        context.processor.process(context.source, context.output, context.request)

    assert not context.output.exists()
    assert context.frames.closed


def test_ffmpeg_preflight_uses_an_argument_list_and_rejects_decode_errors(environment, monkeypatch) -> None:
    context = environment
    monkeypatch.setattr(
        "app.services.video_processor.subprocess.run",
        Mock(return_value=subprocess.CompletedProcess([], 1, stderr="corrupt packet")),
    )

    with pytest.raises(VideoProcessingError, match="corrupt or unsupported") as failure:
        VideoProcessor._validate_source(context.processor, context.source)

    assert isinstance(failure.value.__cause__, subprocess.CalledProcessError)
    from app.services.video_processor import subprocess as process_module
    arguments, options = process_module.run.call_args
    assert isinstance(arguments[0], list)
    assert "-xerror" in arguments[0]
    assert str(context.source) in arguments[0]
    assert options.get("shell", False) is False
    assert options["timeout"] == context.processor.settings.processing_timeout_seconds


def test_intermediate_larger_than_the_source_limit_uses_its_own_disk_budget(environment) -> None:
    # Regression: a 137 s 720p YouTube video failed because the MJPG intermediate (~177 KB/frame)
    # was checked against the 200 MB source limit instead of a dedicated intermediate budget.
    context = environment
    context.source.write_bytes(b"small")
    context.processor.settings.max_video_size_mb = 15 / (1024 * 1024)

    result = context.processor.process(context.source, context.output, context.request)

    assert result.path.stat().st_size > 15
    assert result.statistics.total_frames_processed == 3


def test_intermediate_exceeding_its_disk_budget_fails_and_is_removed(environment) -> None:
    context = environment
    context.processor.settings.max_intermediate_size_mb = 15 / (1024 * 1024)

    with pytest.raises(VideoLimitExceededError, match="intermediate"):
        context.processor.process(context.source, context.output, context.request)

    assert not context.output.exists()
