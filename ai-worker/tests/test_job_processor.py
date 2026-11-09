import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.config.settings import Settings
from app.core.exceptions import (
    ArtifactStorageError, InvalidVideoSourceError, ModelLoadingError, VideoDownloadError, VideoEncodingError,
)
from app.schemas.messaging import DetectionEvent, WorkerJobStatus
from app.schemas.progress import ProgressEvent, ProgressStage
from app.services.artifact_storage import ArtifactKeys
from app.workers.job_processor import (
    DetectionJobProcessor, Disposition, EventPublicationError, ProgressThrottle, classify, sanitize_message,
)

JOB = UUID("3f1d2a4e-8a7b-4c1d-9e2f-0123456789ab")


def command_bytes(**overrides):
    data = {
        "schemaVersion": 1, "messageId": str(uuid4()), "jobId": str(JOB), "modelKey": "yolo11n",
        "sourceType": "LOCAL_FILE", "source": "clips/clip.mp4", "confidence": 0.25, "imageSize": 320,
        "classes": [2, 5], "createdAt": "2026-11-08T00:00:00Z",
    }
    data.update(overrides)
    return json.dumps(data).encode()


class RecordingSink:
    def __init__(self, fail_required=False):
        self.events: list[DetectionEvent] = []
        self.fail_required = fail_required

    def publish(self, event, *, required):
        if required and self.fail_required:
            raise EventPublicationError("not confirmed")
        self.events.append(event)

    def statuses(self):
        return [event.status.value for event in self.events]


class FakeStore:
    def __init__(self):
        self.manifests = {}
        self.uploads = []
        self.fail = False

    def keys_for(self, job_id):
        return ArtifactKeys(f"detections/{job_id}/detected.mp4", f"detections/{job_id}/result.json")

    def find_completed(self, job_id):
        return self.manifests.get(job_id)

    def store(self, job_id, video, manifest):
        if self.fail:
            raise ArtifactStorageError("down")
        assert Path(video).read_bytes() == b"encoded video"
        self.uploads.append((job_id, manifest))
        self.manifests[job_id] = manifest
        return self.keys_for(job_id)


class FakePipeline:
    def __init__(self, settings, error=None, model_key=None):
        self.settings = settings
        self.error = error
        self.model_key = model_key
        self.requests = []

    def process_video(self, request, on_progress=None):
        self.requests.append(request)
        for stage, value in [(ProgressStage.DETECTING, 15), (ProgressStage.DETECTING, 16), (ProgressStage.DETECTING, 50),
                             (ProgressStage.ENCODING, 85), (ProgressStage.ENCODING, 99), (ProgressStage.COMPLETED, 100)]:
            on_progress(ProgressEvent(stage=stage, progress=value, processed_frames=value, total_frames=100,
                                      message=f"Working in {self.settings.output_dir}"))
        if self.error:
            raise self.error
        out = self.settings.output_dir / "exec"
        out.mkdir(parents=True)
        video = out / "detected.mp4"
        video.write_bytes(b"encoded video")
        return SimpleNamespace(
            model_key=self.model_key or request.model_key,
            output=SimpleNamespace(video_path=video),
            statistics=SimpleNamespace(total_frames_processed=36),
            model_dump_json=lambda by_alias: json.dumps({
                "executionId": "e", "modelKey": self.model_key or request.model_key, "modelVersion": "YOLO11",
                "processingTimeMs": 7058, "output": {"videoPath": str(video), "metadataPath": "x"},
                "statistics": {"totalFramesProcessed": 36, "detectionsByClass": {"bus": 36},
                               "modelKey": request.model_key},
            }),
        )


@pytest.fixture
def environment(tmp_path):
    settings = Settings(AI_MODEL_CACHE_DIR=tmp_path / "models", AI_TEMP_DIR=tmp_path / "temp",
                        AI_LOCAL_INPUT_DIR=tmp_path / "inputs", JOB_MAX_RETRIES=3,
                        WORKER_RETRY_BACKOFF_SECONDS=2, WORKER_HEARTBEAT_SECONDS=60)
    (settings.model_cache_dir).mkdir(parents=True)
    (settings.model_cache_dir / "yolo11n.pt").write_bytes(b"weights")
    store = FakeStore()
    pipelines = []
    preloads = []

    def factory(job_settings, **kwargs):
        pipeline = FakePipeline(job_settings, **environment_options)
        pipelines.append(pipeline)
        return pipeline

    environment_options = {}
    processor = DetectionJobProcessor(
        settings, store, pipeline_factory=factory,
        model_preloader=lambda s, key, allow: preloads.append((key, allow)),
    )
    return SimpleNamespace(settings=settings, store=store, pipelines=pipelines, preloads=preloads,
                           processor=processor, options=environment_options)


def test_successful_job_publishes_progress_uploading_and_completion_then_acks(environment):
    sink = RecordingSink()

    settlement = environment.processor.handle(command_bytes(), 1, sink)

    assert settlement.disposition == Disposition.ACK
    assert sink.statuses()[-2:] == ["UPLOADING", "COMPLETED"]
    assert "DETECTING" in sink.statuses() and "ENCODING" in sink.statuses()
    completion = sink.events[-1]
    assert completion.model_key == "yolo11n" and completion.progress == 100
    assert completion.result.output_video_key == f"detections/{JOB}/detected.mp4"
    assert completion.result.result_json_key == f"detections/{JOB}/result.json"
    assert completion.result.total_frames == 36 and completion.result.processing_time_ms == 7058
    assert completion.result.detection_summary == {"bus": 36}
    assert environment.preloads == [("yolo11n", False)]


def test_progress_is_monotonic_below_completion_and_throttled(environment):
    sink = RecordingSink()
    environment.processor.handle(command_bytes(), 1, sink)

    progress = [event.progress for event in sink.events if event.status != WorkerJobStatus.COMPLETED]
    assert progress == sorted(progress) and max(progress) <= 96
    # 15 and 16 are within one step of each other: only the first is published.
    assert [e.progress for e in sink.events if e.status == WorkerJobStatus.DETECTING] == [15, 50]


def test_pipeline_completed_stage_is_not_forwarded_before_storage(environment):
    environment.store.fail = True
    sink = RecordingSink()

    environment.processor.handle(command_bytes(), 1, sink)

    assert "COMPLETED" not in sink.statuses()


def test_manifest_contains_object_keys_and_no_local_paths(environment):
    environment.processor.handle(command_bytes(), 1, RecordingSink())

    _, manifest = environment.store.uploads[0]
    text = json.dumps(manifest)
    assert manifest["artifacts"] == {"outputVideoKey": f"detections/{JOB}/detected.mp4",
                                     "resultJsonKey": f"detections/{JOB}/result.json"}
    assert manifest["jobId"] == str(JOB) and "output" not in manifest
    assert str(environment.settings.temp_dir) not in text


def test_progress_messages_do_not_leak_local_paths(environment):
    sink = RecordingSink()
    environment.processor.handle(command_bytes(), 1, sink)

    assert all(str(environment.settings.temp_dir) not in (event.message or "") for event in sink.events)


def test_local_source_is_resolved_inside_the_input_directory(environment):
    environment.processor.handle(command_bytes(), 1, RecordingSink())

    request = environment.pipelines[0].requests[0]
    assert Path(request.source) == (environment.settings.local_input_dir / "clips/clip.mp4").resolve()
    assert request.model_key == "yolo11n" and request.image_size == 320 and request.classes == [2, 5]


def test_working_files_are_removed_after_the_job(environment):
    environment.processor.handle(command_bytes(), 1, RecordingSink())

    assert list(environment.settings.temp_dir.iterdir()) == []


def test_redelivered_completed_job_republishes_completion_without_inference(environment):
    environment.processor.handle(command_bytes(), 1, RecordingSink())
    sink = RecordingSink()

    settlement = environment.processor.handle(command_bytes(messageId=str(uuid4())), 2, sink)

    assert settlement.disposition == Disposition.ACK
    assert sink.statuses() == ["COMPLETED"]
    assert len(environment.pipelines) == 1


def test_unsupported_model_fails_permanently_and_acks(environment):
    sink = RecordingSink()

    settlement = environment.processor.handle(command_bytes(modelKey="yolov5s"), 1, sink)

    assert settlement.disposition == Disposition.ACK
    assert sink.events[-1].error.code == "UNSUPPORTED_MODEL"
    assert environment.pipelines == []


def test_unprepared_model_fails_permanently_without_downloading(environment):
    sink = RecordingSink()

    settlement = environment.processor.handle(command_bytes(modelKey="yolov8n"), 1, sink)

    assert settlement.disposition == Disposition.ACK
    assert sink.events[-1].error.code == "MODEL_NOT_PREPARED"
    assert "models prepare --model yolov8n" in sink.events[-1].error.message
    assert environment.preloads == []


def test_permanent_pipeline_errors_publish_failed_and_ack(environment):
    environment.options["error"] = InvalidVideoSourceError("The local video file does not exist or cannot be opened")
    sink = RecordingSink()

    settlement = environment.processor.handle(command_bytes(), 1, sink)

    assert settlement.disposition == Disposition.ACK
    failed = sink.events[-1]
    assert failed.status == WorkerJobStatus.FAILED and failed.error.code == "INVALID_SOURCE"
    assert failed.error.retryable is False and failed.progress < 100


def test_transient_errors_are_retried_with_backoff_without_a_failed_event(environment):
    environment.options["error"] = VideoDownloadError("YouTube download failed.")
    sink = RecordingSink()

    first = environment.processor.handle(command_bytes(), 1, sink)
    second = environment.processor.handle(command_bytes(), 2, sink)

    assert (first.disposition, first.retry_delay_seconds) == (Disposition.RETRY, 2)
    assert (second.disposition, second.retry_delay_seconds) == (Disposition.RETRY, 4)
    assert "FAILED" not in sink.statuses()


def test_exhausted_retries_publish_failed_and_dead_letter(environment):
    environment.options["error"] = VideoDownloadError("YouTube download failed.")
    sink = RecordingSink()

    settlement = environment.processor.handle(command_bytes(), 3, sink)

    assert settlement.disposition == Disposition.DEAD_LETTER
    assert sink.events[-1].error.code == "VIDEO_DOWNLOAD_FAILED"
    assert "Gave up after 3 attempt(s)" in sink.events[-1].error.message


def test_storage_failure_is_transient_and_never_reports_completion(environment):
    environment.store.fail = True
    sink = RecordingSink()

    assert environment.processor.handle(command_bytes(), 1, sink).disposition == Disposition.RETRY
    assert environment.processor.handle(command_bytes(), 3, sink).disposition == Disposition.DEAD_LETTER
    assert sink.events[-1].error.code == "STORAGE_FAILED"
    assert "COMPLETED" not in sink.statuses()


def test_unconfirmed_completion_is_retried_and_later_answered_from_storage(environment):
    settlement = environment.processor.handle(command_bytes(), 1, RecordingSink(fail_required=True))
    assert settlement.disposition == Disposition.RETRY

    sink = RecordingSink()
    assert environment.processor.handle(command_bytes(), 2, sink).disposition == Disposition.ACK
    assert sink.statuses() == ["COMPLETED"] and len(environment.pipelines) == 1


def test_model_mismatch_is_never_reported_as_completed(environment):
    environment.options["model_key"] = "yolov8n"
    sink = RecordingSink()

    assert environment.processor.handle(command_bytes(), 1, sink).disposition == Disposition.ACK
    assert sink.events[-1].error.code == "VIDEO_PROCESSING_FAILED"
    assert environment.store.uploads == []


def test_model_load_failure_is_transient(environment):
    def failing(*_):
        raise ModelLoadingError("yolo11n.pt could not be loaded.")

    environment.processor.model_preloader = failing

    assert environment.processor.handle(command_bytes(), 1, RecordingSink()).disposition == Disposition.RETRY


@pytest.mark.parametrize("body", [b"not json", b"{}", command_bytes(schemaVersion=2),
                                  command_bytes(modelKey="../x.pt"), command_bytes(imageSize=-1)])
def test_invalid_commands_are_dead_lettered(environment, body):
    sink = RecordingSink()

    assert environment.processor.handle(body, 1, sink).disposition == Disposition.DEAD_LETTER
    assert environment.pipelines == []


def test_invalid_command_with_a_job_id_reports_failure(environment):
    sink = RecordingSink()

    environment.processor.handle(command_bytes(classes=[]), 1, sink)

    assert sink.events[-1].error.code == "INVALID_COMMAND" and sink.events[-1].job_id == JOB


def test_encoding_errors_never_expose_ffmpeg_output():
    failure = classify(VideoEncodingError("FFmpeg encoding failed: C:\\Users\\me\\temp\\annotated.avi broken"))

    assert failure.message == "The annotated video could not be encoded." and not failure.retryable


def test_unknown_errors_are_generic_and_transient():
    failure = classify(RuntimeError("secret token=abc /home/me/.aws/credentials"))

    assert failure.code == "INTERNAL_ERROR" and "secret" not in failure.message and failure.retryable


@pytest.mark.parametrize("text", [
    "failed at C:\\Users\\me\\video.mp4 now", "failed at /data/temp/job-1/x.mp4 now",
    "see https://example.com/v?sig=SECRET",
])
def test_sanitize_message_removes_paths_and_urls(text):
    clean = sanitize_message(text)

    assert "[redacted]" in clean and "me" not in clean.split("[redacted]")[0][-3:] and "SECRET" not in clean


@pytest.mark.parametrize(("text", "expected"), [
    # Windows paths can contain spaces; nothing after the drive prefix may leak.
    ("Cannot open C:\\Users\\First Last\\AppData\\Local\\Temp\\x\\source.mp4", "Cannot open [redacted]"),
    ("C:/Users/First Last/video.mp4 is corrupt", "[redacted]"),
    ("\\\\fileserver\\share name\\clip.mp4 missing", "[redacted]"),
    ("Reading /data/temp/job-1/source.mp4 failed", "Reading [redacted] failed"),
    ("Video exceeds the 300 s limit (ratio 1:2)", "Video exceeds the 300 s limit (ratio 1:2)"),
])
def test_sanitize_message_never_leaks_any_part_of_a_path(text, expected):
    assert sanitize_message(text) == expected


def test_throttle_publishes_on_stage_change_step_or_interval():
    now = [0.0]
    throttle = ProgressThrottle(min_step=5, interval_seconds=10, clock=lambda: now[0])

    assert throttle.should_publish(WorkerJobStatus.DETECTING, 15)
    assert not throttle.should_publish(WorkerJobStatus.DETECTING, 16)
    assert throttle.should_publish(WorkerJobStatus.DETECTING, 20)
    assert throttle.should_publish(WorkerJobStatus.ENCODING, 20)
    now[0] = 11
    assert throttle.should_publish(WorkerJobStatus.ENCODING, 21)
    now[0] = 30
    assert not throttle.should_publish(WorkerJobStatus.ENCODING, 21)
