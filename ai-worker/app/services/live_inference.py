"""Single-frame inference for Live Detection (webcam frames forwarded by the Spring Boot gateway).

Reuses the approved model registry, ModelLoader, and DetectionService. Frames are decoded in
memory, never written to disk or logged, and models are only ever loaded from the prepared
cache (no downloads). The number of loaded models is bounded (least recently used is evicted).
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

logger = logging.getLogger(__name__)

MODEL_KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
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
                 classes: list[int]) -> LiveSettings:
        errors: list[str] = []
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
        return LiveSettings(model_key, frame_id, confidence, image_size, sorted(classes))

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
        try:
            detected = self.detector.detect_image(
                image, loaded, settings.confidence, settings.image_size, settings.classes)
        except InferenceError as error:
            logger.warning("Live inference failed for frame %d: %s", settings.frame_id, error)
            raise LiveError("INFERENCE_FAILED", "YOLO inference failed on the frame.", 500) from error
        elapsed = (time.perf_counter() - started) * 1000
        return {
            "frameId": settings.frame_id,
            "modelKey": settings.model_key,
            "width": width,
            "height": height,
            "detections": [
                {
                    "classId": box.class_id,
                    "label": box.label,
                    "confidence": round(box.confidence, 4),
                    "box": [round(min(max(value, 0.0), limit), 1)
                            for value, limit in zip(box.xyxy, (width, height, width, height))],
                }
                for box in detected.boxes
            ],
            "inferenceMs": round(detected.inference_time_ms if detected.inference_time_ms is not None else elapsed, 1),
        }

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
