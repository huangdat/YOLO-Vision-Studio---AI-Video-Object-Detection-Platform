import json
from pathlib import Path

import pytest

from app.config.settings import Settings
from app.core.exceptions import (
    InferenceError, InvalidVideoSourceError, VideoDownloadError, VideoEncodingError, VideoNormalizationError,
)
from app.schemas.detection import DetectionRequest, DetectionStatistics, SourceType
from app.schemas.progress import ProgressEvent, ProgressReporter, ProgressStage
from app.schemas.video import ProcessingResult, VideoMetadata
from app.services.video_input import PreparedVideo, VideoStreamInfo
from app.workers.detection_pipeline import DetectionPipeline


class FakeProcessor:
    def __init__(self, error=None, unknown_total=False):
        self.error = error
        self.unknown_total = unknown_total
        self.requests = []

    def process(self, video_path, output_path, request, on_progress=None):
        self.requests.append(request)
        assert video_path.is_file()
        output_path.write_bytes(b"intermediate video")
        if self.error is not None:
            raise self.error
        if on_progress:
            on_progress(ProgressEvent(stage=ProgressStage.DETECTING, progress=70, processed_frames=4))
            on_progress(ProgressEvent(stage=ProgressStage.DETECTING, progress=45, processed_frames=2))
        return ProcessingResult(
            path=output_path,
            metadata=VideoMetadata(width=320, height=240, fps=12,
                                   total_frames=None if self.unknown_total else 4, duration_seconds=4 / 12),
            statistics=DetectionStatistics(
                model_key=request.model_key, device="cpu", confidence=request.confidence,
                image_size=request.image_size, classes=request.classes,
                total_frames_processed=4, total_detections=3, detections_by_class={"car": 2, "person": 1},
                processing_time_ms=1,
            ),
        )


class FakeEncoder:
    def __init__(self, error=None, empty=False):
        self.error = error
        self.empty = empty

    def encode(self, source, destination):
        if self.error:
            destination.write_bytes(b"partial")
            raise self.error
        destination.write_bytes(b"" if self.empty else b"encoded video")
        return destination


class FakeDownloader:
    def __init__(self, error=None):
        self.error = error

    def download(self, source, working_directory, on_progress=None):
        video = working_directory / "downloaded.webm"
        video.write_bytes(b"downloaded video")
        if self.error:
            raise self.error
        if on_progress:
            on_progress(ProgressEvent(stage=ProgressStage.DOWNLOADING, progress=15))
        return video


class FakePreparer:
    """Pass-through by default; with normalize=True, writes a converted copy into the work directory."""

    def __init__(self, normalize=False, error=None):
        self.normalize, self.error = normalize, error
        self.calls = []

    def prepare(self, source, work_dir):
        self.calls.append((source, work_dir))
        info = VideoStreamInfo(codec="av1" if self.normalize else "h264", container="matroska,webm",
                               width=320, height=240, pixel_format="yuv420p", duration_seconds=1.0)
        if self.normalize:
            converted = work_dir / "normalized-test.mp4"
            converted.write_bytes(b"normalized h264")
            if self.error:
                raise self.error
            return PreparedVideo(path=converted, source=info, normalized=True)
        if self.error:
            raise self.error
        return PreparedVideo(path=source, source=info, normalized=False)


@pytest.fixture
def setup_pipeline(tmp_path):
    settings = Settings(temp_dir=tmp_path / "work", output_dir=tmp_path / "outputs", local_input_dir=tmp_path)
    source = tmp_path / "source.avi"
    source.write_bytes(b"original input")
    processor = FakeProcessor()
    pipeline = DetectionPipeline(settings, processor=processor, downloader=FakeDownloader(), encoder=FakeEncoder(),
                                 input_preparer=FakePreparer())
    return settings, source, processor, pipeline


def local(source, **options):
    return DetectionRequest(source=str(source), source_type=SourceType.LOCAL_FILE, **options)


def test_local_pipeline_publishes_actual_statistics_json_and_cleans_working_files(setup_pipeline):
    settings, source, processor, pipeline = setup_pipeline
    events = []
    result = pipeline.process_video(local(source), events.append)

    assert result.output.video_path.read_bytes() == b"encoded video"
    assert result.output.video_path.parent.name == str(result.execution_id)
    assert result.output.metadata_path.name == "result.json"
    payload = json.loads(result.output.metadata_path.read_text())
    assert payload["status"] == "COMPLETED"
    assert payload["statistics"]["detectionsByClass"] == {"car": 2, "person": 1}
    assert payload["statistics"]["totalFramesProcessed"] == 4
    assert payload["input"]["sourceType"] == "LOCAL_FILE"
    assert list(settings.temp_dir.iterdir()) == []
    assert source.read_bytes() == b"original input"
    assert processor.requests[0].classes == [1, 2, 3, 5, 7]
    assert processor.requests[0].confidence == 0.25
    assert processor.requests[0].image_size == 960
    assert [event.progress for event in events] == sorted(event.progress for event in events)
    assert all(event.progress < 100 for event in events[:-1])
    assert events[-1].stage == ProgressStage.COMPLETED and events[-1].progress == 100


def test_youtube_request_uses_downloader_and_retains_source_type(setup_pipeline):
    settings, source, processor, pipeline = setup_pipeline
    events = []
    result = pipeline.process_video(DetectionRequest(
        source="https://youtu.be/abcdefghijk", source_type=SourceType.YOUTUBE_URL,
    ), events.append)
    assert events[0].stage == ProgressStage.DOWNLOADING
    assert result.input.source_type == SourceType.YOUTUBE_URL
    assert list(settings.temp_dir.iterdir()) == []


@pytest.mark.parametrize("error", [InferenceError("Inference failed"), VideoEncodingError("Encoding failed"),
                                  VideoDownloadError("Download failed"), KeyboardInterrupt()])
def test_failures_cleanup_and_never_emit_success(setup_pipeline, error):
    settings, source, processor, pipeline = setup_pipeline
    if isinstance(error, VideoEncodingError):
        pipeline.encoder = FakeEncoder(error=error)
    elif isinstance(error, VideoDownloadError):
        pipeline.downloader = FakeDownloader(error=error)
    else:
        processor.error = error
    request = DetectionRequest(source="https://youtu.be/abcdefghijk", source_type=SourceType.YOUTUBE_URL) \
        if isinstance(error, VideoDownloadError) else local(source)
    events = []
    with pytest.raises(type(error)):
        pipeline.process_video(request, events.append)
    assert not list(settings.temp_dir.iterdir())
    assert not list(settings.output_dir.iterdir())
    assert events[-1].stage == ProgressStage.FAILED
    assert all(event.progress < 100 for event in events)


def test_empty_encoded_output_is_not_success(setup_pipeline):
    settings, source, processor, pipeline = setup_pipeline
    pipeline.encoder = FakeEncoder(empty=True)
    with pytest.raises(Exception, match="nonempty"):
        pipeline.process_video(local(source))
    assert list(settings.output_dir.iterdir()) == []


def test_unknown_frame_count_does_not_prevent_completion(setup_pipeline):
    settings, source, processor, pipeline = setup_pipeline
    processor.unknown_total = True
    events = []
    result = pipeline.process_video(local(source), events.append)
    assert result.input.total_frames is None
    assert result.statistics.total_frames_processed == 4
    assert events[-1].total_frames is None


def test_executions_have_distinct_output_directories(setup_pipeline):
    settings, source, processor, pipeline = setup_pipeline
    first = pipeline.process_video(local(source))
    second = pipeline.process_video(local(source))
    assert first.output.video_path != second.output.video_path
    assert first.output.video_path.exists() and second.output.video_path.exists()


def test_explicit_output_is_published_without_overwriting(setup_pipeline):
    settings, source, processor, pipeline = setup_pipeline
    target = settings.output_dir / "result.mp4"
    result = pipeline.process_video(local(source, output_path=target))
    assert result.output.video_path == target
    assert target.with_suffix(".json").is_file()
    with pytest.raises(InvalidVideoSourceError, match="already exists"):
        pipeline.process_video(local(source, output_path=target))
    assert target.read_bytes() == b"encoded video"


def test_output_paths_cannot_escape_configured_root(setup_pipeline, tmp_path):
    settings, source, processor, pipeline = setup_pipeline
    with pytest.raises(InvalidVideoSourceError, match="AI_OUTPUT_DIR"):
        pipeline.process_video(local(source, output_path=tmp_path / "outside.mp4"))
    assert not (tmp_path / "outside.mp4").exists()


def test_local_paths_cannot_escape_allowed_input_root(setup_pipeline, tmp_path):
    settings, source, processor, pipeline = setup_pipeline
    settings.local_input_dir = tmp_path / "restricted"
    with pytest.raises(InvalidVideoSourceError, match="AI_LOCAL_INPUT_DIR"):
        pipeline.process_video(local(source))


def test_remote_url_cannot_be_interpreted_as_local_file(setup_pipeline):
    settings, source, processor, pipeline = setup_pipeline
    with pytest.raises(InvalidVideoSourceError, match="Local sources"):
        pipeline.process_video(local("https://evil.example/video.mp4"))


def test_observer_failure_is_logged_without_faking_processing_failure(setup_pipeline, caplog):
    settings, source, processor, pipeline = setup_pipeline
    def broken(event):
        raise RuntimeError("observer unavailable")
    result = pipeline.process_video(local(source), broken)
    assert result.output.video_path.is_file()
    assert "observer failed" in caplog.text


def test_progress_is_clamped_until_completion_and_never_regresses():
    events = []
    reporter = ProgressReporter(events.append)
    reporter.emit(ProgressEvent(stage=ProgressStage.DETECTING, progress=100, processed_frames=3))
    reporter.emit(ProgressEvent(stage=ProgressStage.ENCODING, progress=85, processed_frames=2))
    assert [event.progress for event in events] == [99, 99]
    assert [event.processed_frames for event in events] == [3, 3]


@pytest.mark.parametrize("model_key, version, size", [
    ("yolov8n", "YOLOv8", "n"), ("yolo11s", "YOLO11", "s"), ("yolo12m", "YOLO12", "m"), ("yolo26s", "YOLO26", "s"),
])
def test_result_json_identifies_the_loaded_model(setup_pipeline, model_key, version, size):
    _, source, processor, pipeline = setup_pipeline

    result = pipeline.process_video(local(source, model_key=model_key))

    payload = json.loads(result.output.metadata_path.read_text())
    assert processor.requests[0].model_key == model_key
    assert payload["modelKey"] == payload["statistics"]["modelKey"] == model_key
    assert payload["modelVersion"] == version and payload["modelSize"] == size
    assert payload["weightsFilename"] == f"{model_key}.pt"


def test_result_metadata_reports_the_actually_loaded_model_not_the_request(setup_pipeline):
    _, source, processor, pipeline = setup_pipeline
    original = processor.process

    def loaded_other_model(video_path, output_path, request, on_progress=None):
        result = original(video_path, output_path, request, on_progress)
        return result.model_copy(update={
            "statistics": result.statistics.model_copy(update={"model_key": "yolo11n"})
        })

    processor.process = loaded_other_model
    result = pipeline.process_video(local(source, model_key="yolov8n"))

    assert result.model_key == "yolo11n" and result.weights_filename == "yolo11n.pt"


def youtube():
    return DetectionRequest(source="https://youtu.be/abcdefghijk", source_type=SourceType.YOUTUBE_URL)


def test_youtube_av1_download_is_normalized_before_processing_and_cleaned(setup_pipeline):
    settings, source, processor, pipeline = setup_pipeline
    pipeline.input_preparer = preparer = FakePreparer(normalize=True)
    seen = []
    original = processor.process

    def record(video_path, output_path, request, on_progress=None):
        seen.append((video_path.name, video_path.read_bytes()))
        return original(video_path, output_path, request, on_progress)
    processor.process = record
    result = pipeline.process_video(youtube())
    downloaded, work_dir = preparer.calls[0]
    assert downloaded.name == "downloaded.webm" and downloaded.parent == work_dir
    assert seen == [("normalized-test.mp4", b"normalized h264")]
    assert result.output.video_path.read_bytes() == b"encoded video"
    assert list(settings.temp_dir.iterdir()) == []


def test_local_sources_are_prepared_without_modifying_the_original(setup_pipeline):
    settings, source, processor, pipeline = setup_pipeline
    pipeline.input_preparer = preparer = FakePreparer(normalize=True)
    pipeline.process_video(local(source))
    assert preparer.calls[0][0] == source
    assert source.read_bytes() == b"original input"
    assert list(settings.temp_dir.iterdir()) == []


def test_normalization_failure_fails_the_job_without_publishing(setup_pipeline):
    settings, source, processor, pipeline = setup_pipeline
    pipeline.input_preparer = FakePreparer(normalize=True, error=VideoNormalizationError("conversion failed"))
    events = []
    with pytest.raises(VideoNormalizationError):
        pipeline.process_video(youtube(), events.append)
    assert processor.requests == []
    assert not list(settings.temp_dir.iterdir())
    assert not list(settings.output_dir.iterdir())
    assert events[-1].stage == ProgressStage.FAILED
