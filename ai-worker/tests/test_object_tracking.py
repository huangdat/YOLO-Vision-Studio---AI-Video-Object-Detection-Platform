"""ByteTrack integration: real Ultralytics BYTETracker driven by synthetic detections (no weights)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from app.config.settings import Settings
from app.core.exceptions import InferenceError
from app.schemas.detection import DetectionBox, DetectionRequest, ProcessingMode, SourceType
from app.services.detection_service import DetectedFrame, DetectionService
from app.services.model_loader import LoadedModel
from app.services.object_tracking import (
    ByteTrackParameters, ObjectTracker, TrackingAccumulator, TrajectoryHistory, annotate_tracked, track_label,
)
from app.services.video_processor import VideoProcessor

NAMES = {0: "person", 2: "car", 5: "bus"}


def car(x: float, confidence: float = 0.9, y: float = 10.0) -> DetectionBox:
    return DetectionBox(class_id=2, label="car", confidence=confidence, xyxy=(x, y, x + 50, y + 40))


def person(y: float, confidence: float = 0.8) -> DetectionBox:
    return DetectionBox(class_id=0, label="person", confidence=confidence, xyxy=(300, y, 340, y + 80))


def tracker(confidence: float = 0.25, **options) -> ObjectTracker:
    return ObjectTracker(ByteTrackParameters.for_confidence(confidence, options.pop("track_buffer", None)), **options)


def ids(frame) -> list[int | None]:
    return [box.track_id for box in frame.objects]


# Parameters ---------------------------------------------------------------------------------

def test_parameters_follow_bytetrack_yaml_and_the_user_confidence() -> None:
    parameters = ByteTrackParameters.for_confidence(0.4)
    args = parameters.tracker_args()

    assert parameters.inference_confidence == pytest.approx(0.1)
    assert args.track_high_thresh == args.new_track_thresh == 0.4
    assert args.track_low_thresh == pytest.approx(0.1)
    assert (args.track_buffer, args.match_thresh, args.fuse_score) == (30, 0.8, True)
    assert parameters.to_schema().inference_confidence == pytest.approx(0.1)


def test_a_confidence_below_the_low_floor_is_never_raised() -> None:
    parameters = ByteTrackParameters.for_confidence(0.05)

    assert parameters.inference_confidence == 0.05
    assert parameters.tracker_args().track_low_thresh == 0.05


@pytest.mark.parametrize("confidence", [-0.1, 1.5])
def test_invalid_confidence_is_rejected(confidence: float) -> None:
    with pytest.raises(ValueError):
        ByteTrackParameters.for_confidence(confidence)


# Association --------------------------------------------------------------------------------

def test_consecutive_frames_keep_the_same_id_and_objects_get_different_ids() -> None:
    stream = tracker()
    frames = [stream.update([car(10 + 6 * index), person(100 + 4 * index)]) for index in range(5)]

    assert all(ids(frame) == [1, 2] for frame in frames)
    assert all(frame.active_tracks == 2 for frame in frames)
    assert [frame.frame_index for frame in frames] == [0, 1, 2, 3, 4]


def test_a_new_object_is_unconfirmed_on_its_first_frame_and_keeps_its_box() -> None:
    stream = tracker()
    stream.update([car(10)])

    first = stream.update([car(16), person(100)])
    second = stream.update([car(22), person(104)])

    # Not invented: the second detection has no Track ID until ByteTrack confirms it.
    assert ids(first) == [1, None]
    assert first.objects[1].xyxy == person(100).xyxy
    assert first.active_tracks == 1
    assert ids(second)[0] == 1 and ids(second)[1] is not None and ids(second)[1] != 1


def test_empty_frames_advance_the_tracker_and_a_short_gap_keeps_the_id() -> None:
    stream = tracker()
    for index in range(3):
        stream.update([car(10 + 5 * index)])

    gap = stream.update([])
    after = stream.update([car(30)])

    assert gap.objects == [] and gap.active_tracks == 0
    assert ids(after) == [1]


def test_low_score_boxes_continue_existing_tracks_but_do_not_start_new_ones() -> None:
    stream = tracker(confidence=0.5)
    for index in range(3):
        stream.update([car(10 + 5 * index)])

    frame = stream.update([car(25, confidence=0.2), person(100, confidence=0.2)])

    # The occluded car keeps ID 1 with its real (low) score; the new low-score person is dropped.
    assert [(box.label, box.track_id, box.confidence) for box in frame.objects] == [("car", 1, 0.2)]
    # Detection events keep Detection Only semantics: nothing below the user's threshold counts.
    assert frame.threshold_detections == []


def test_boxes_at_the_threshold_without_an_id_are_still_reported() -> None:
    stream = tracker()
    stream.update([car(10)])
    degenerate = DetectionBox(class_id=2, label="car", confidence=0.9, xyxy=(500, 10, 500, 50))

    frame = stream.update([car(15), degenerate])

    assert ids(frame) == [1, None]
    assert len(frame.threshold_detections) == 2


def test_separate_trackers_do_not_share_ids_or_state() -> None:
    first, second = tracker(), tracker()
    for index in range(3):
        first.update([car(10 + 5 * index), person(100)])

    other = second.update([person(200)])

    assert ids(other) == [1]
    assert ids(first.update([car(25), person(100)])) == [1, 2]


def test_closing_releases_state_and_prevents_reuse() -> None:
    stream = tracker(trajectory_length=5)
    for index in range(3):
        stream.update([car(10 + 5 * index)])

    stream.close()
    stream.close()  # idempotent

    assert stream.closed and len(stream.trajectories) == 0
    with pytest.raises(RuntimeError):
        stream.update([car(30)])


def test_updates_use_an_injected_tracker_output_mapping() -> None:
    fake = SimpleNamespace(update=Mock(return_value=np.asarray([[0, 0, 1, 1, 7, 0.9, 2, 1]], dtype=np.float32)),
                           reset=Mock())
    stream = ObjectTracker(ByteTrackParameters.for_confidence(0.25), tracker_factory=lambda args: fake)

    frame = stream.update([car(10), car(100)])
    stream.close()

    assert ids(frame) == [None, 7]
    passed = fake.update.call_args.args[0]
    assert passed.conf.tolist() == pytest.approx([0.9, 0.9]) and passed.xywh[0].tolist() == [35, 30, 50, 40]
    fake.reset.assert_called_once()


# Trajectories and statistics ------------------------------------------------------------------

def test_trajectories_are_bounded_in_length_age_and_count() -> None:
    history = TrajectoryHistory(length=3, max_age=2, max_tracks=2)
    for index in range(5):
        history.update(index, [car(10 * index).model_copy(update={"track_id": 1})])
    assert len(history.points(1)) == 3

    history.update(5, [car(0).model_copy(update={"track_id": 2}), car(0).model_copy(update={"track_id": 3})])
    assert len(history) == 2 and history.points(1) == []  # evicted beyond max_tracks
    history.update(9, [])
    assert len(history) == 0  # unseen for longer than max_age


def test_tracker_trajectories_follow_object_centers() -> None:
    stream = tracker(trajectory_length=4)
    for index in range(6):
        stream.update([car(10 + 10 * index)])

    assert stream.trajectories.points(1) == [(55, 30), (65, 30), (75, 30), (85, 30)]


def test_accumulator_reports_unique_ids_active_tracks_and_per_track_summaries() -> None:
    stream = tracker()
    parameters = stream.parameters
    accumulator = TrackingAccumulator(parameters, NAMES, fps=10)
    for index in range(4):
        accumulator.add(stream.update([car(10 + 5 * index), person(100, confidence=0.6)]))

    statistics = accumulator.result()

    assert statistics.tracker == "bytetrack"
    assert statistics.count_semantics == "TRACK_IDS_ASSIGNED_BY_BYTETRACK"
    assert statistics.unique_track_ids == 2
    assert statistics.unique_track_ids_by_class == {"car": 1, "person": 1}
    assert statistics.max_active_tracks == 2 and statistics.frames_with_tracks == 4
    assert statistics.tracked_detections == 8 and statistics.untracked_detections == 0
    first = statistics.tracks[0]
    assert (first.track_id, first.class_name, first.first_frame, first.last_frame) == (1, "car", 0, 3)
    assert (first.first_timestamp_ms, first.last_timestamp_ms, first.frames_observed) == (0, 300, 4)
    assert first.last_box == (25.0, 10.0, 75.0, 50.0)
    assert statistics.tracks[1].average_confidence == pytest.approx(0.6)


def test_accumulator_bounds_stored_track_summaries_but_counts_every_id() -> None:
    accumulator = TrackingAccumulator(ByteTrackParameters.for_confidence(0.25), NAMES, fps=30, max_tracks=1)
    from app.services.object_tracking import TrackedFrame

    accumulator.add(TrackedFrame(0, [car(0).model_copy(update={"track_id": 1}),
                                     person(0).model_copy(update={"track_id": 2})], 2, 0.25))

    statistics = accumulator.result()
    assert statistics.unique_track_ids == 2 and len(statistics.tracks) == 1 and statistics.tracks_truncated
    assert statistics.unique_track_ids_by_class == {"car": 1, "person": 1}


# Annotation ---------------------------------------------------------------------------------

def test_labels_show_the_track_id_only_when_confirmed() -> None:
    assert track_label(car(0, 0.94).model_copy(update={"track_id": 7})) == "car #7 0.94"
    assert track_label(car(0, 0.91)) == "car 0.91"


def test_annotation_draws_boxes_and_trajectories_into_the_frame() -> None:
    image = np.zeros((120, 200, 3), dtype=np.uint8)
    history = TrajectoryHistory(length=5, max_age=5)
    tracked = car(60, y=50).model_copy(update={"track_id": 3})
    for index in range(3):
        history.update(index, [car(20 + 20 * index, y=50).model_copy(update={"track_id": 3})])

    annotated = annotate_tracked(image, [tracked, car(5, y=5)], NAMES, history)

    assert annotated.shape == (120, 200, 3) and annotated.dtype == np.uint8
    assert annotated.any()


# Batch integration ----------------------------------------------------------------------------

def _result(boxes):
    return SimpleNamespace(
        boxes=SimpleNamespace(cls=[b.class_id for b in boxes], conf=[b.confidence for b in boxes],
                              xyxy=[list(b.xyxy) for b in boxes]),
        speed={"inference": 2.0}, plot=Mock(return_value="plotted"),
        orig_img=np.zeros((120, 400, 3), dtype=np.uint8),
    )


def test_iter_frames_runs_bytetrack_at_the_inference_confidence_and_annotates_ids() -> None:
    results = [_result([car(10 + 5 * index), person(20, confidence=0.05)]) for index in range(3)]
    model = SimpleNamespace(predict=Mock(return_value=iter(results)), predictor=None)
    loaded = LoadedModel(model, "yolo11n", "cpu", NAMES)
    stream = tracker(confidence=0.3)

    frames = list(DetectionService().iter_frames(Path("clip.mp4"), loaded, 0.3, 320, [0, 2], tracker=stream))

    assert model.predict.call_args.kwargs["conf"] == pytest.approx(0.1)
    assert [[box.track_id for box in frame.boxes] for frame in frames] == [[1], [1], [1]]
    assert all(frame.tracked is not None and frame.tracked.active_tracks == 1 for frame in frames)
    assert all(not result.plot.called for result in results)
    assert all(isinstance(frame.image, np.ndarray) and frame.image.any() for frame in frames)


def test_iter_frames_without_a_tracker_is_unchanged() -> None:
    results = [_result([car(10)])]
    model = SimpleNamespace(predict=Mock(return_value=iter(results)), predictor=None)
    loaded = LoadedModel(model, "yolo11n", "cpu", NAMES)

    frames = list(DetectionService().iter_frames(Path("clip.mp4"), loaded, 0.3, 320, [2]))

    assert model.predict.call_args.kwargs["conf"] == 0.3
    assert frames[0].image == "plotted" and frames[0].tracked is None
    assert frames[0].boxes[0].track_id is None


def test_iter_frames_rejects_a_tracker_for_another_confidence() -> None:
    model = SimpleNamespace(predict=Mock(), predictor=None)
    with pytest.raises(InferenceError):
        list(DetectionService().iter_frames(Path("clip.mp4"), LoadedModel(model, "yolo11n", "cpu", NAMES),
                                            0.3, 320, [2], tracker=tracker(confidence=0.5)))
    model.predict.assert_not_called()


class _Frame:
    shape = (2, 4, 3)
    dtype = "uint8"


class _Writer:
    def __init__(self, path, *args):
        self.path = Path(path)
        self.path.write_bytes(b"header")

    def isOpened(self):
        return True

    def write(self, image):
        with self.path.open("ab") as output:
            output.write(b"frame")

    def release(self):
        pass


class _Capture:
    def __init__(self, path):
        self.properties = {1: 4, 2: 2, 3: 10.0, 4: 3}

    def isOpened(self):
        return True

    def get(self, key):
        return self.properties[key]

    def read(self):
        return True, _Frame()

    def release(self):
        pass


class _RecordingTracker(ObjectTracker):
    instances: list[_RecordingTracker] = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _RecordingTracker.instances.append(self)


@pytest.fixture
def processor_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    _RecordingTracker.instances = []
    source = tmp_path / "input.mp4"
    source.write_bytes(b"generated-video-fixture")
    cv2 = SimpleNamespace(CAP_PROP_FRAME_WIDTH=1, CAP_PROP_FRAME_HEIGHT=2, CAP_PROP_FPS=3, CAP_PROP_FRAME_COUNT=4,
                          VideoCapture=_Capture, VideoWriter=_Writer, VideoWriter_fourcc=lambda *letters: 1)
    loaded = SimpleNamespace(model_key="yolo11n", device="cpu", names=NAMES)

    def iter_frames(video_path, loaded_model, confidence, image_size, classes, tracker=None):
        for index in range(3):
            boxes = [car(10 + 5 * index), person(100 + 2 * index, confidence=0.2)]
            if tracker is None:
                yield DetectedFrame(_Frame(), [b for b in boxes if b.confidence >= confidence], 2.0)
            else:
                tracked = tracker.update(boxes)
                yield DetectedFrame(_Frame(), tracked.objects, 2.0, tracked)
                if failures.get("after_frame") == index:
                    raise InferenceError("broken frame")

    failures: dict[str, int] = {}
    detection = SimpleNamespace(iter_frames=iter_frames)
    settings = Settings(temp_dir=tmp_path, model_cache_dir=tmp_path / "models")
    processor = VideoProcessor(settings, SimpleNamespace(load=Mock(return_value=loaded)), detection,
                               tracker_factory=_RecordingTracker)
    monkeypatch.setattr(processor, "_opencv", lambda: cv2)
    monkeypatch.setattr(processor, "_validate_source", Mock())
    return SimpleNamespace(processor=processor, source=source, tmp=tmp_path, failures=failures)


def _request(source: Path, mode: ProcessingMode) -> DetectionRequest:
    return DetectionRequest(source_type=SourceType.LOCAL_FILE, source=str(source), confidence=0.25,
                            classes=[0, 2], processing_mode=mode)


def test_detection_only_jobs_create_no_tracker(processor_environment) -> None:
    context = processor_environment

    result = context.processor.process(context.source, context.tmp / "a.avi",
                                       _request(context.source, ProcessingMode.DETECTION_ONLY))

    assert _RecordingTracker.instances == []
    assert result.processing_mode == ProcessingMode.DETECTION_ONLY and result.tracking is None
    assert result.statistics.detections_by_class == {"car": 3}


def test_tracking_jobs_report_ids_keep_detection_counts_and_release_the_tracker(processor_environment) -> None:
    context = processor_environment

    result = context.processor.process(context.source, context.tmp / "a.avi",
                                       _request(context.source, ProcessingMode.DETECTION_TRACKING))

    assert len(_RecordingTracker.instances) == 1 and _RecordingTracker.instances[0].closed
    assert result.processing_mode == ProcessingMode.DETECTION_TRACKING
    # The low-score person never starts a track and is never counted as a detection event.
    assert result.statistics.detections_by_class == {"car": 3}
    assert result.tracking.unique_track_ids == 1 and result.tracking.tracks[0].frames_observed == 3
    assert result.tracking.tracks[0].last_timestamp_ms == 200


def test_consecutive_jobs_get_fresh_trackers_with_ids_starting_at_one(processor_environment) -> None:
    context = processor_environment
    request = _request(context.source, ProcessingMode.DETECTION_TRACKING)

    first = context.processor.process(context.source, context.tmp / "a.avi", request)
    second = context.processor.process(context.source, context.tmp / "b.avi", request)

    assert len(_RecordingTracker.instances) == 2
    assert _RecordingTracker.instances[0] is not _RecordingTracker.instances[1]
    assert all(tracker.closed for tracker in _RecordingTracker.instances)
    assert [t.track_id for t in first.tracking.tracks] == [t.track_id for t in second.tracking.tracks] == [1]


def test_a_failed_tracking_job_still_releases_its_tracker(processor_environment) -> None:
    context = processor_environment
    context.failures["after_frame"] = 1

    with pytest.raises(InferenceError):
        context.processor.process(context.source, context.tmp / "a.avi",
                                  _request(context.source, ProcessingMode.DETECTION_TRACKING))

    assert len(_RecordingTracker.instances) == 1 and _RecordingTracker.instances[0].closed
    assert not (context.tmp / "a.avi").exists()
