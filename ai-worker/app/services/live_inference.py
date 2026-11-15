"""Single-frame inference for Live Detection (webcam frames forwarded by the Spring Boot gateway).

Reuses the approved model registry, ModelLoader, and DetectionService. Frames are decoded in
memory, never written to disk or logged, and models are only ever loaded from the prepared
cache (no downloads). The number of loaded models is bounded (least recently used is evicted).

Tracking mode keeps one ByteTrack tracker per gateway session ID, in memory only. Sessions are
bounded in number, expire when idle, and are ended explicitly by the gateway; an ended session
ID is never revived, so a late frame cannot resurrect old Track IDs.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import logging
import re
import threading
import time
from typing import Any

from app.config.settings import Settings
from app.core.exceptions import InferenceError, ModelLoadingError
from app.services.detection_service import DetectionService
from app.services.model_loader import LoadedModel, ModelLoader
from app.services.model_registry import CacheStatus, ModelSpec, get_model_spec, inspect_model
from app.services.object_tracking import ByteTrackParameters, ObjectTracker

logger = logging.getLogger(__name__)

MODEL_KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9-]{8,64}$")
ENDED_SESSIONS_REMEMBERED = 256
MAX_FRAME_ID = 2**32 - 1
COCO_CLASS_COUNT = 80
# JPEG start-of-frame markers that carry the image dimensions (baseline, progressive, ...).
_SOF_MARKERS = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


class LiveError(Exception):
    """A client-safe failure with a stable code and HTTP status."""

    def __init__(self, code: str, message: str, status: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


@dataclass(frozen=True)
class LiveSettings:
    model_key: str
    frame_id: int
    confidence: float
    image_size: int
    classes: list[int]
    tracking: bool = False
    session_id: str | None = None

    @property
    def signature(self) -> tuple[Any, ...]:
        return self.model_key, self.confidence, self.image_size, tuple(self.classes)


class _TrackingSession:
    def __init__(self, session_id: str, signature: tuple[Any, ...], tracker: ObjectTracker, now: float) -> None:
        self.session_id = session_id
        self.signature = signature
        self.tracker = tracker
        self.last_frame_id = -1
        self.last_used = now
        # Serializes this session's frames; different sessions never share a tracker.
        self.lock = threading.Lock()


class LiveTrackingSessions:
    """Bounded, in-memory ByteTrack state keyed by the gateway's session ID."""

    def __init__(self, max_sessions: int, ttl_seconds: float, track_buffer: int, *,
                 clock: Any = time.monotonic, tracker_factory: Any = ObjectTracker) -> None:
        self.max_sessions = max_sessions
        self.ttl_seconds = ttl_seconds
        self.track_buffer = track_buffer
        self.clock = clock
        self.tracker_factory = tracker_factory
        self._sessions: dict[str, _TrackingSession] = {}
        self._ended: OrderedDict[str, None] = OrderedDict()
        self._lock = threading.Lock()

    def acquire(self, settings: LiveSettings) -> _TrackingSession:
        session_id = settings.session_id or ""
        now = self.clock()
        stale: list[_TrackingSession] = []
        try:
            with self._lock:
                self._purge(now, stale)
                if session_id in self._ended:
                    raise LiveError("SESSION_ENDED", "The live session has ended.", 409)
                session = self._sessions.get(session_id)
                if session is not None and session.signature != settings.signature:
                    # Settings belong to the session; a change starts a fresh tracker with new IDs.
                    stale.append(self._sessions.pop(session_id))
                    session = None
                if session is None:
                    if len(self._sessions) >= self.max_sessions:
                        raise LiveError("TRACKING_CAPACITY",
                                        "The live worker is already tracking the maximum number of sessions.", 429)
                    tracker = self.tracker_factory(
                        ByteTrackParameters.for_confidence(settings.confidence, self.track_buffer))
                    session = _TrackingSession(session_id, settings.signature, tracker, now)
                    self._sessions[session_id] = session
                    logger.info("Tracking session started (%d active)", len(self._sessions))
                session.last_used = now
        finally:
            self._close(stale)
        return session

    def end(self, session_id: str) -> bool:
        with self._lock:
            session = self._sessions.pop(session_id, None)
            self._remember_ended(session_id)
        if session is not None:
            self._close([session])
            logger.info("Tracking session ended (%d active)", self.active())
        return session is not None

    def active(self) -> int:
        with self._lock:
            return len(self._sessions)

    def close_all(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        self._close(sessions)

    def _purge(self, now: float, stale: list[_TrackingSession]) -> None:
        for session_id, session in list(self._sessions.items()):
            # A session that is processing a frame is in use, so it cannot be idle.
            if now - session.last_used > self.ttl_seconds and not session.lock.locked():
                stale.append(self._sessions.pop(session_id))
                self._remember_ended(session_id)
                logger.info("Tracking session expired after %.0f s idle", now - session.last_used)

    def _remember_ended(self, session_id: str) -> None:
        self._ended[session_id] = None
        self._ended.move_to_end(session_id)
        while len(self._ended) > ENDED_SESSIONS_REMEMBERED:
            self._ended.popitem(last=False)

    @staticmethod
    def _close(sessions: list[_TrackingSession]) -> None:
        for session in sessions:
            with session.lock:  # waits for a frame of that session that is still being processed
                session.tracker.close()


def jpeg_dimensions(data: bytes) -> tuple[int, int]:
    """(width, height) from the JPEG header, read before decoding so a tiny file that
    declares a huge image cannot force a large allocation."""
    if len(data) < 4 or data[0] != 0xFF or data[1] != 0xD8:
        raise LiveError("INVALID_FRAME", "The frame is not a JPEG image.", 400)
    index = 2
    while index + 4 <= len(data):
        if data[index] != 0xFF:
            raise LiveError("INVALID_FRAME", "The JPEG structure is invalid.", 400)
        marker = data[index + 1]
        if marker == 0xFF:  # fill byte
            index += 1
            continue
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            index += 2
            continue
        length = int.from_bytes(data[index + 2:index + 4], "big")
        if length < 2 or index + 2 + length > len(data):
            break
        if marker in _SOF_MARKERS:
            if length < 7:
                break
            height = int.from_bytes(data[index + 5:index + 7], "big")
            width = int.from_bytes(data[index + 7:index + 9], "big")
            if width <= 0 or height <= 0:
                break
            return width, height
        if marker == 0xDA:  # start of scan before any frame header
            break
        index += 2 + length
    raise LiveError("INVALID_FRAME", "The JPEG image dimensions could not be read.", 400)


class LiveInferenceService:
    def __init__(self, settings: Settings, loader: ModelLoader | None = None,
                 detector: DetectionService | None = None) -> None:
        self.settings = settings
        self.loader = loader or ModelLoader(settings)
        self.detector = detector or DetectionService()
        self._models: OrderedDict[str, LoadedModel] = OrderedDict()
        self._warmed: dict[str, set[int]] = {}
        self._lock = threading.Lock()
        self.tracking = LiveTrackingSessions(settings.live_max_tracking_sessions,
                                             settings.live_tracking_session_ttl_seconds,
                                             settings.live_tracking_track_buffer)

    # Models ------------------------------------------------------------------------------

    def spec_for(self, model_key: str) -> ModelSpec:
        spec = get_model_spec(model_key) if MODEL_KEY_PATTERN.match(model_key or "") else None
        if spec is None or spec.task_type != "DETECT":
            raise LiveError("MODEL_NOT_SUPPORTED", "The model is not an approved detection model.", 404)
        if spec.model_size not in self.settings.live_allowed_model_sizes:
            raise LiveError("MODEL_NOT_SUPPORTED",
                            "Live Detection supports only the configured lightweight model sizes.", 404)
        return spec

    def load_model(self, model_key: str, warm_up_size: int | None = None) -> LoadedModel:
        """Load (or reuse) a prepared model. With ``warm_up_size`` a blank frame is run once at
        that inference size, so the first real frame does not pay the framework warm-up cost
        (measured at about 3 s on CPU) inside the gateway's per-frame timeout."""
        loaded = self._load(model_key)
        if warm_up_size is not None and warm_up_size not in self._warmed.setdefault(model_key, set()):
            import numpy as np

            started = time.perf_counter()
            try:
                self.detector.detect_image(np.zeros((warm_up_size, warm_up_size, 3), dtype=np.uint8),
                                           loaded, 0.5, warm_up_size, [0])
            except InferenceError as error:
                raise LiveError("MODEL_LOAD_FAILED", "The model could not run a warm-up inference.", 503) from error
            self._warmed[model_key].add(warm_up_size)
            logger.info("Warmed up %s at %d px in %.0f ms", model_key, warm_up_size,
                        (time.perf_counter() - started) * 1000)
        return loaded

    def _load(self, model_key: str) -> LoadedModel:
        spec = self.spec_for(model_key)
        with self._lock:
            if model_key in self._models:
                self._models.move_to_end(model_key)
                return self._models[model_key]
        status = inspect_model(self.settings.model_cache_dir, spec)
        if status.status == CacheStatus.NOT_CACHED:
            raise LiveError(
                "MODEL_NOT_PREPARED",
                f"{spec.weights_filename} is not prepared. Run 'python -m app.cli models prepare "
                f"--model {spec.model_key}' on the detection consumer, which shares the model cache.", 409)
        try:
            loaded = self.loader.load(model_key, allow_download=False, record_verification=False)
        except ModelLoadingError as error:
            logger.warning("Live model %s could not be loaded: %s", model_key, error)
            raise LiveError("MODEL_LOAD_FAILED", "The model could not be loaded by the live worker.", 503) from error
        with self._lock:
            self._models[model_key] = loaded
            self._models.move_to_end(model_key)
            while len(self._models) > self.settings.live_max_loaded_models:
                evicted, _ = self._models.popitem(last=False)
                self._warmed.pop(evicted, None)
                logger.info("Evicted live model %s (limit %d)", evicted, self.settings.live_max_loaded_models)
            evicted_keys = ModelLoader.evict(set(self._models))
        if evicted_keys:
            logger.info("Released cached models: %s", ", ".join(evicted_keys))
        logger.info("Live model %s ready on %s", model_key, loaded.device)
        return loaded

    def loaded_model_keys(self) -> list[str]:
        with self._lock:
            return list(self._models)

    # Inference ---------------------------------------------------------------------------

    def validate(self, model_key: str, frame_id: int, confidence: float, image_size: int,
                 classes: list[int], tracking: bool = False, session_id: str | None = None) -> LiveSettings:
        errors: list[str] = []
        if tracking and (session_id is None or not SESSION_ID_PATTERN.match(session_id)):
            errors.append("sessionId (8-64 letters, digits, or '-') is required for tracking")
        if not 0 <= frame_id <= MAX_FRAME_ID:
            errors.append("frameId must be an unsigned 32-bit integer")
        if not 0 <= confidence <= 1:
            errors.append("confidence must be between 0 and 1")
        if not 32 <= image_size <= self.settings.live_max_image_size or image_size % 32:
            errors.append(f"imageSize must be a multiple of 32 between 32 and {self.settings.live_max_image_size}")
        if not classes or len(classes) > COCO_CLASS_COUNT or len(set(classes)) != len(classes) or any(
                not 0 <= value < COCO_CLASS_COUNT for value in classes):
            errors.append("classes must be 1-80 unique COCO class IDs (0-79)")
        if errors:
            raise LiveError("INVALID_PARAMETERS", "; ".join(errors) + ".", 400)
        return LiveSettings(model_key, frame_id, confidence, image_size, sorted(classes), tracking,
                            session_id if tracking else None)

    def infer(self, frame: bytes, settings: LiveSettings) -> dict[str, Any]:
        if not frame:
            raise LiveError("INVALID_FRAME", "The frame is empty.", 400)
        if len(frame) > self.settings.live_max_frame_bytes:
            raise LiveError("FRAME_TOO_LARGE",
                            f"The frame exceeds {self.settings.live_max_frame_bytes} bytes.", 413)
        width, height = jpeg_dimensions(frame)
        if (max(width, height) > self.settings.live_max_frame_side
                or width * height > self.settings.live_max_frame_pixels):
            raise LiveError("FRAME_TOO_LARGE", "The frame dimensions exceed the live limits.", 413)
        loaded = self._load(settings.model_key)
        image = self._decode(frame, width, height)
        started = time.perf_counter()
        if settings.tracking:
            session = self.tracking.acquire(settings)
            with session.lock:
                if session.tracker.closed:
                    raise LiveError("SESSION_ENDED", "The live session has ended.", 409)
                if settings.frame_id <= session.last_frame_id:
                    # ByteTrack assumes time moves forward; never feed it an old frame.
                    raise LiveError("FRAME_OUT_OF_ORDER", "The frame is older than one already processed.", 409)
                detected = self._detect(image, loaded, settings, session.tracker.inference_confidence)
                tracked = session.tracker.update(detected.boxes)
                session.last_frame_id = settings.frame_id
            boxes, active_tracks = tracked.objects, tracked.active_tracks
        else:
            detected = self._detect(image, loaded, settings, settings.confidence)
            boxes, active_tracks = detected.boxes, None
        elapsed = (time.perf_counter() - started) * 1000
        result: dict[str, Any] = {
            "frameId": settings.frame_id,
            "modelKey": settings.model_key,
            "width": width,
            "height": height,
            "detections": [self._detection(box, width, height, settings.tracking) for box in boxes],
            "inferenceMs": round(detected.inference_time_ms if detected.inference_time_ms is not None else elapsed, 1),
        }
        if settings.tracking:
            result["tracking"] = True
            result["activeTracks"] = active_tracks
        return result

    def end_session(self, session_id: str) -> bool:
        return self.tracking.end(session_id)

    def _detect(self, image: Any, loaded: LoadedModel, settings: LiveSettings, confidence: float) -> Any:
        try:
            return self.detector.detect_image(image, loaded, confidence, settings.image_size, settings.classes)
        except InferenceError as error:
            logger.warning("Live inference failed for frame %d: %s", settings.frame_id, error)
            raise LiveError("INFERENCE_FAILED", "YOLO inference failed on the frame.", 500) from error

    @staticmethod
    def _detection(box: Any, width: int, height: int, tracking: bool) -> dict[str, Any]:
        detection: dict[str, Any] = {
            "classId": box.class_id,
            "label": box.label,
            "confidence": round(box.confidence, 4),
            "box": [round(min(max(value, 0.0), limit), 1)
                    for value, limit in zip(box.xyxy, (width, height, width, height))],
        }
        if tracking:
            # null: detected, but ByteTrack has not confirmed a track for it (yet).
            detection["trackId"] = box.track_id
        return detection

    @staticmethod
    def _decode(frame: bytes, width: int, height: int) -> Any:
        import cv2
        import numpy as np

        # Ignore EXIF orientation: boxes must use the submitted frame's own pixel grid.
        flags = cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION
        image = cv2.imdecode(np.frombuffer(frame, dtype=np.uint8), flags)
        if image is None or image.ndim != 3 or image.shape[0] != height or image.shape[1] != width:
            raise LiveError("INVALID_FRAME", "The JPEG image could not be decoded.", 400)
        return image
