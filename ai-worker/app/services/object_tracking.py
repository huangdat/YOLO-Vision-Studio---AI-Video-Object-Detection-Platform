"""ByteTrack multi-object tracking for exactly one video job or one live session.

Design notes:

* Ultralytics' ``model.track(persist=True)`` keeps tracker state on the (process-wide, shared)
  model and registers callbacks on it, which would leak state between jobs and live sessions.
  Instead each stream owns one ``ObjectTracker`` wrapping its own Ultralytics ``BYTETracker``;
  the YOLO weights stay shared and detection still runs under the model lock.
* ByteTrack is *online*: each frame is associated using only the frames before it, so the same
  algorithm serves prerecorded videos and live streams. There is no second, offline pass.
* Confidence: ByteTrack's second association stage needs low-score boxes. In tracking mode YOLO
  therefore runs at ``inference_confidence = min(confidence, 0.1)``. The user's confidence stays
  the threshold for detection counts, for first-stage matching, and for starting new tracks; a
  box below it is reported only when it continues an existing track (with its real score).
  Greedy NMS keeps the same boxes at or above the user's confidence either way.
"""

from __future__ import annotations

from collections import Counter, OrderedDict, deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
import logging
from typing import Any

import numpy as np

from app.schemas.detection import DetectionBox
from app.schemas.tracking import TrackerParameters, TrackingStatistics, TrackSummary

logger = logging.getLogger(__name__)

# bytetrack.yaml defaults of the pinned Ultralytics version; the YAML file is read when available.
_BYTETRACK_DEFAULTS: dict[str, Any] = {
    "tracker_type": "bytetrack", "track_high_thresh": 0.25, "track_low_thresh": 0.1,
    "new_track_thresh": 0.25, "track_buffer": 30, "match_thresh": 0.8, "fuse_score": True,
}
MAX_TRAJECTORY_TRACKS = 256
UNTRACKED_COLOR = (128, 128, 128)  # BGR


def bytetrack_defaults() -> dict[str, Any]:
    """The shipped bytetrack.yaml values (read locally, never downloaded)."""
    try:
        from ultralytics.utils import YAML
        from ultralytics.utils.checks import check_yaml

        loaded = YAML.load(check_yaml("bytetrack.yaml"))
        if isinstance(loaded, dict) and loaded.get("tracker_type") == "bytetrack":
            return {**_BYTETRACK_DEFAULTS, **{key: loaded[key] for key in _BYTETRACK_DEFAULTS if key in loaded}}
    except Exception:  # pragma: no cover - only without Ultralytics installed
        logger.warning("bytetrack.yaml could not be read; using built-in ByteTrack defaults", exc_info=True)
    return dict(_BYTETRACK_DEFAULTS)


@dataclass(frozen=True)
class ByteTrackParameters:
    confidence: float
    track_buffer: int
    match_thresh: float
    fuse_score: bool
    low_score_floor: float

    @classmethod
    def for_confidence(cls, confidence: float, track_buffer: int | None = None) -> ByteTrackParameters:
        if not 0 <= confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        defaults = bytetrack_defaults()
        buffer = int(track_buffer if track_buffer is not None else defaults["track_buffer"])
        if buffer < 1:
            raise ValueError("track_buffer must be positive")
        return cls(confidence=float(confidence), track_buffer=buffer, match_thresh=float(defaults["match_thresh"]),
                   fuse_score=bool(defaults["fuse_score"]), low_score_floor=float(defaults["track_low_thresh"]))

    @property
    def inference_confidence(self) -> float:
        """YOLO threshold in tracking mode: low enough for ByteTrack's second association stage."""
        return min(self.confidence, self.low_score_floor)

    def tracker_args(self) -> Any:
        from types import SimpleNamespace

        return SimpleNamespace(
            tracker_type="bytetrack", track_high_thresh=self.confidence, track_low_thresh=self.inference_confidence,
            new_track_thresh=self.confidence, track_buffer=self.track_buffer, match_thresh=self.match_thresh,
            fuse_score=self.fuse_score,
        )

    def to_schema(self) -> TrackerParameters:
        args = self.tracker_args()
        return TrackerParameters(
            inference_confidence=self.inference_confidence, track_high_thresh=args.track_high_thresh,
            track_low_thresh=args.track_low_thresh, new_track_thresh=args.new_track_thresh,
            match_thresh=args.match_thresh, track_buffer=args.track_buffer, fuse_score=args.fuse_score,
        )


class _Detections:
    """NumPy-backed detections in the shape BYTETracker.update expects (conf, cls, xywh, masks)."""

    def __init__(self, xyxy: np.ndarray, conf: np.ndarray, cls: np.ndarray) -> None:
        self.xyxy = xyxy
        self.conf = conf
        self.cls = cls

    @classmethod
    def from_boxes(cls, boxes: list[DetectionBox]) -> _Detections:
        if not boxes:
            return cls(np.zeros((0, 4), dtype=np.float32), np.zeros(0, dtype=np.float32),
                       np.zeros(0, dtype=np.float32))
        return cls(np.asarray([box.xyxy for box in boxes], dtype=np.float32),
                   np.asarray([box.confidence for box in boxes], dtype=np.float32),
                   np.asarray([box.class_id for box in boxes], dtype=np.float32))

    @property
    def xywh(self) -> np.ndarray:
        xywh = np.empty_like(self.xyxy)
        xywh[:, 0] = (self.xyxy[:, 0] + self.xyxy[:, 2]) / 2
        xywh[:, 1] = (self.xyxy[:, 1] + self.xyxy[:, 3]) / 2
        xywh[:, 2] = self.xyxy[:, 2] - self.xyxy[:, 0]
        xywh[:, 3] = self.xyxy[:, 3] - self.xyxy[:, 1]
        return xywh

    def __len__(self) -> int:
        return len(self.conf)

    def __getitem__(self, index: Any) -> _Detections:
        return _Detections(self.xyxy[index], self.conf[index], self.cls[index])


@dataclass(frozen=True)
class TrackedFrame:
    frame_index: int
    # Detections at or above the confidence threshold (with a Track ID when confirmed) plus
    # lower-score boxes that continued an existing track. Coordinates are the detection's own.
    objects: list[DetectionBox]
    active_tracks: int
    confidence: float

    @property
    def threshold_detections(self) -> list[DetectionBox]:
        """Boxes counted as detection events: the same set Detection Only mode reports."""
        return [box for box in self.objects if box.confidence >= self.confidence]


class TrajectoryHistory:
    """Short, bounded center-point history per Track ID (for drawing only)."""

    def __init__(self, length: int, max_age: int, max_tracks: int = MAX_TRAJECTORY_TRACKS) -> None:
        self.length = max(0, length)
        self.max_age = max(1, max_age)
        self.max_tracks = max(1, max_tracks)
        self._points: OrderedDict[int, deque[tuple[int, int]]] = OrderedDict()
        self._seen: dict[int, int] = {}

    def update(self, frame_index: int, objects: Iterable[DetectionBox]) -> None:
        if not self.length:
            return
        for box in objects:
            if box.track_id is None:
                continue
            x1, y1, x2, y2 = box.xyxy
            points = self._points.get(box.track_id)
            if points is None:
                points = self._points[box.track_id] = deque(maxlen=self.length)
            points.append((round((x1 + x2) / 2), round((y1 + y2) / 2)))
            self._points.move_to_end(box.track_id)
            self._seen[box.track_id] = frame_index
        for track_id in [key for key, seen in self._seen.items() if frame_index - seen > self.max_age]:
            self._forget(track_id)
        while len(self._points) > self.max_tracks:
            self._forget(next(iter(self._points)))

    def points(self, track_id: int) -> list[tuple[int, int]]:
        return list(self._points.get(track_id, ()))

    def __len__(self) -> int:
        return len(self._points)

    def clear(self) -> None:
        self._points.clear()
        self._seen.clear()

    def _forget(self, track_id: int) -> None:
        self._points.pop(track_id, None)
        self._seen.pop(track_id, None)


def _default_tracker_factory(args: Any) -> Any:
    from ultralytics.trackers.byte_tracker import BYTETracker

    return BYTETracker(args)


class ObjectTracker:
    """ByteTrack state for one ordered stream of frames. Not thread-safe: one caller at a time."""

    def __init__(self, parameters: ByteTrackParameters, *, trajectory_length: int = 0,
                 tracker_factory: Callable[[Any], Any] = _default_tracker_factory) -> None:
        self.parameters = parameters
        self._tracker = tracker_factory(parameters.tracker_args())
        self.trajectories = TrajectoryHistory(trajectory_length, parameters.track_buffer)
        self.frames = 0
        self.closed = False

    @property
    def inference_confidence(self) -> float:
        return self.parameters.inference_confidence

    def update(self, boxes: list[DetectionBox]) -> TrackedFrame:
        """Associate one frame's detections (all boxes at or above ``inference_confidence``).

        Frames must arrive in order; an empty list still advances the tracker so lost tracks age.
        """
        if self.closed:
            raise RuntimeError("The tracker was closed")
        output = self._tracker.update(_Detections.from_boxes(boxes))
        track_ids: dict[int, int] = {}
        for row in np.asarray(output).reshape(-1, 8) if len(output) else ():
            index, track_id = int(row[7]), int(row[4])
            if 0 <= index < len(boxes) and track_id >= 1:
                track_ids[index] = track_id
        confidence = self.parameters.confidence
        objects = [
            box.model_copy(update={"track_id": track_ids.get(index)})
            for index, box in enumerate(boxes)
            if index in track_ids or box.confidence >= confidence
        ]
        frame = TrackedFrame(frame_index=self.frames, objects=objects, active_tracks=len(track_ids),
                             confidence=confidence)
        self.trajectories.update(self.frames, objects)
        self.frames += 1
        return frame

    def close(self) -> None:
        """Release all track state; the tracker cannot be reused afterwards."""
        if self.closed:
            return
        self.closed = True
        reset = getattr(self._tracker, "reset", None)
        if callable(reset):
            reset()
        self._tracker = None
        self.trajectories.clear()


@dataclass
class _TrackStats:
    first_frame: int
    first_timestamp_ms: int
    last_frame: int = 0
    last_timestamp_ms: int = 0
    frames: int = 0
    confidence_sum: float = 0.0
    max_confidence: float = 0.0
    last_box: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    classes: Counter[int] = field(default_factory=Counter)


class TrackingAccumulator:
    """Per-job tracking statistics. Memory is bounded by ``max_tracks`` stored summaries."""

    def __init__(self, parameters: ByteTrackParameters, names: dict[int, str], fps: float,
                 max_tracks: int = 5000) -> None:
        self.parameters = parameters
        self.names = names
        self.fps = fps
        self.max_tracks = max_tracks
        self._tracks: dict[int, _TrackStats] = {}
        self._overflow_ids: set[int] = set()
        self._overflow_classes: Counter[str] = Counter()
        self.max_active = 0
        self.active_sum = 0
        self.frames = 0
        self.frames_with_tracks = 0
        self.tracked = 0
        self.untracked = 0

    def add(self, frame: TrackedFrame) -> None:
        self.frames += 1
        self.max_active = max(self.max_active, frame.active_tracks)
        self.active_sum += frame.active_tracks
        if frame.active_tracks:
            self.frames_with_tracks += 1
        timestamp = round(frame.frame_index * 1000 / self.fps)
        for box in frame.objects:
            if box.track_id is None:
                self.untracked += 1
                continue
            self.tracked += 1
            stats = self._tracks.get(box.track_id)
            if stats is None:
                if len(self._tracks) >= self.max_tracks:
                    if box.track_id not in self._overflow_ids:
                        self._overflow_ids.add(box.track_id)
                        self._overflow_classes[box.label] += 1
                    continue
                stats = self._tracks[box.track_id] = _TrackStats(frame.frame_index, timestamp)
            stats.last_frame, stats.last_timestamp_ms = frame.frame_index, timestamp
            stats.frames += 1
            stats.confidence_sum += box.confidence
            stats.max_confidence = max(stats.max_confidence, box.confidence)
            stats.last_box = box.xyxy
            stats.classes[box.class_id] += 1

    def result(self) -> TrackingStatistics:
        summaries: list[TrackSummary] = []
        by_class: Counter[str] = Counter(self._overflow_classes)
        for track_id, stats in sorted(self._tracks.items()):
            # A track's class is its most frequent detected class (ByteTrack can relabel).
            class_id = stats.classes.most_common(1)[0][0]
            name = self.names.get(class_id, str(class_id))
            by_class[name] += 1
            summaries.append(TrackSummary(
                track_id=track_id, class_id=class_id, class_name=name, first_frame=stats.first_frame,
                last_frame=stats.last_frame, first_timestamp_ms=stats.first_timestamp_ms,
                last_timestamp_ms=stats.last_timestamp_ms, frames_observed=stats.frames,
                average_confidence=round(min(stats.confidence_sum / stats.frames, 1.0), 4),
                max_confidence=round(stats.max_confidence, 4),
                last_box=tuple(round(value, 1) for value in stats.last_box),
            ))
        return TrackingStatistics(
            parameters=self.parameters.to_schema(),
            unique_track_ids=len(self._tracks) + len(self._overflow_ids),
            unique_track_ids_by_class=dict(by_class), max_active_tracks=self.max_active,
            average_active_tracks=round(self.active_sum / self.frames, 3) if self.frames else 0.0,
            frames_with_tracks=self.frames_with_tracks, tracked_detections=self.tracked,
            untracked_detections=self.untracked, tracks=summaries, tracks_truncated=bool(self._overflow_ids),
        )


def track_label(box: DetectionBox) -> str:
    """'car #7 0.94' for a confirmed track, 'car 0.94' otherwise."""
    if box.track_id is None:
        return f"{box.label} {box.confidence:.2f}"
    return f"{box.label} #{box.track_id} {box.confidence:.2f}"


def annotate_tracked(image: Any, objects: list[DetectionBox], names: dict[int, str],
                     trajectories: TrajectoryHistory | None = None) -> Any:
    """Draw boxes with Track IDs (Ultralytics' annotator and palette) and short trajectories."""
    import cv2
    from ultralytics.utils.plotting import Annotator, colors

    annotator = Annotator(image, example=str(names))
    thickness = max(1, annotator.lw - 1)
    if trajectories is not None:
        for box in objects:
            points = trajectories.points(box.track_id) if box.track_id is not None else []
            if len(points) > 1:
                cv2.polylines(annotator.im, [np.asarray(points, dtype=np.int32)], False,
                              colors(box.track_id, True), thickness, cv2.LINE_AA)
    for box in objects:
        # Detections without a confirmed track are drawn in neutral grey: no identity is implied.
        color = colors(box.track_id, True) if box.track_id is not None else UNTRACKED_COLOR
        annotator.box_label(box.xyxy, track_label(box), color=color)
    return annotator.result()
