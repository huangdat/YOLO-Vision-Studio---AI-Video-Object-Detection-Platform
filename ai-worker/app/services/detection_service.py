"""Streaming inference and per-frame annotations, independent of HTTP and queues."""

from collections.abc import Iterator
from dataclasses import dataclass
import logging
import math
from pathlib import Path
from typing import Any

from app.core.exceptions import InferenceError
from app.schemas.detection import DetectionBox
from app.services.model_loader import LoadedModel

logger = logging.getLogger(__name__)


@dataclass
class DetectedFrame:
    image: Any
    boxes: list[DetectionBox]
    inference_time_ms: float | None = None


class DetectionService:
    @staticmethod
    def _validate(loaded_model: LoadedModel, confidence: float, image_size: int, classes: list[int]) -> None:
        if not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise InferenceError("Confidence must be between zero and one.")
        if image_size <= 0:
            raise InferenceError("Image size must be positive.")
        if not classes or any(
            isinstance(value, bool) or not isinstance(value, int) or value not in loaded_model.names
            for value in classes
        ):
            raise InferenceError("Selected class identifiers are not supported by this model.")

    def detect_image(
        self, image: Any, loaded_model: LoadedModel, confidence: float,
        image_size: int, classes: list[int],
    ) -> DetectedFrame:
        """One decoded BGR image (live frames). Boxes are in the image's own pixel coordinates;
        no annotated image is rendered and nothing is written to disk."""
        self._validate(loaded_model, confidence, image_size, classes)
        with loaded_model.lock:
            try:
                results = loaded_model.model.predict(
                    source=image, conf=confidence, imgsz=image_size, classes=classes,
                    device=loaded_model.device, save=False, verbose=False,
                )
                result = results[0]
                boxes = self._boxes(result, loaded_model.names)
            except InferenceError:
                raise
            except Exception as error:
                raise InferenceError("YOLO inference failed on the submitted frame.") from error
        speed = getattr(result, "speed", {}) or {}
        timing = speed.get("inference")
        timing = float(timing) if timing is not None and math.isfinite(float(timing)) and float(timing) >= 0 else None
        return DetectedFrame(image=None, boxes=boxes, inference_time_ms=timing)

    def iter_frames(
        self, video_path: Path, loaded_model: LoadedModel, confidence: float,
        image_size: int, classes: list[int],
    ) -> Iterator[DetectedFrame]:
        self._validate(loaded_model, confidence, image_size, classes)
        stream: Any = None
        with loaded_model.lock:
            try:
                stream = loaded_model.model.predict(
                    source=str(video_path), conf=confidence, imgsz=image_size,
                    classes=classes, device=loaded_model.device, stream=True,
                    save=False, verbose=False,
                )
                for result in stream:
                    boxes = self._boxes(result, loaded_model.names)
                    speed = getattr(result, "speed", {}) or {}
                    timing = speed.get("inference")
                    if timing is not None:
                        timing = float(timing)
                        if not math.isfinite(timing) or timing < 0:
                            timing = None
                    yield DetectedFrame(
                        image=result.plot(labels=True, conf=True), boxes=boxes,
                        inference_time_ms=timing,
                    )
            except InferenceError:
                raise
            except Exception as error:
                raise InferenceError("YOLO inference failed while processing video frames.") from error
            finally:
                if stream is not None and callable(getattr(stream, "close", None)):
                    try:
                        stream.close()
                    except Exception:
                        logger.warning("Could not close the inference stream", exc_info=True)
                self._release_captures(loaded_model.model)

    @staticmethod
    def _values(value: Any) -> list[Any]:
        for method in ("detach", "cpu"):
            operation = getattr(value, method, None)
            if callable(operation):
                value = operation()
        operation = getattr(value, "tolist", None)
        return operation() if callable(operation) else list(value)

    @classmethod
    def _boxes(cls, result: Any, names: dict[int, str]) -> list[DetectionBox]:
        raw = getattr(result, "boxes", None)
        if raw is None:
            return []
        identifiers = cls._values(raw.cls)
        confidences = cls._values(raw.conf)
        coordinates = cls._values(raw.xyxy)
        if not len(identifiers) == len(confidences) == len(coordinates):
            raise InferenceError("Model returned inconsistent bounding box data.")
        boxes: list[DetectionBox] = []
        for identifier, confidence, xyxy in zip(identifiers, confidences, coordinates):
            class_id = int(identifier)
            if class_id != identifier or class_id not in names:
                raise InferenceError("Model returned an unknown class identifier.")
            boxes.append(DetectionBox(
                class_id=class_id, label=names[class_id], confidence=float(confidence),
                xyxy=tuple(float(value) for value in xyxy),
            ))
        return boxes

    @staticmethod
    def _release_captures(model: Any) -> None:
        dataset = getattr(getattr(model, "predictor", None), "dataset", None)
        if dataset is None:
            return
        captures = [getattr(dataset, "cap", None)]
        extra = getattr(dataset, "caps", [])
        if isinstance(extra, dict):
            captures.extend(extra.values())
        elif isinstance(extra, (list, tuple)):
            captures.extend(extra)
        seen: set[int] = set()
        for capture in captures:
            if capture is not None and id(capture) not in seen:
                seen.add(id(capture))
                try:
                    capture.release()
                except Exception:
                    logger.warning("Could not release an inference video capture", exc_info=True)
