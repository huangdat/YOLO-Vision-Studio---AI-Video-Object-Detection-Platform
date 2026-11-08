"""Lazy, process-local loading of the explicitly supported inference model."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
import importlib
from importlib import metadata
import json
import logging
import os
from pathlib import Path
from threading import Lock, RLock
from typing import Any, ClassVar

from app.config.settings import Settings
from app.core.exceptions import ModelLoadingError
from app.services.model_registry import (
    DEFAULT_MODEL_KEY, MODEL_SPECS, ModelSpec, file_fingerprint, get_model_spec, verification_record_path,
)

logger = logging.getLogger(__name__)


def _package_version(*names: str) -> str | None:
    """Installed distribution version, read from metadata without importing the package."""
    for name in names:
        try:
            return metadata.version(name)
        except metadata.PackageNotFoundError:
            continue
    return None


@dataclass
class LoadedModel:
    model: Any
    model_key: str
    device: str
    names: dict[int, str]
    # Ultralytics predictors keep mutable state; concurrent streams must not share it.
    lock: Any = field(default_factory=RLock, repr=False)


class ModelLoader:
    """Only explicit inference/preparation calls may import AI packages or fetch weights."""

    # Derived from the registry; kept for callers that only need key -> checkpoint.
    SUPPORTED_MODELS: ClassVar[dict[str, str]] = {
        spec.model_key: spec.weights_filename for spec in MODEL_SPECS
    }
    _cache: ClassVar[dict[tuple[str, str, str], LoadedModel]] = {}
    _load_lock: ClassVar[Any] = Lock()

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def load(
        self, model_key: str = DEFAULT_MODEL_KEY, device: str | None = None,
        allow_download: bool = True,
    ) -> LoadedModel:
        spec = get_model_spec(model_key)
        if spec is None:
            raise ModelLoadingError(
                "Unsupported model identifier; use an approved detection model key such as yolo26s."
            )
        if spec.task_type != "DETECT":
            raise ModelLoadingError("Only pretrained object detection models are supported.")
        filename = spec.weights_filename
        requested_device = device or self.settings.ai_device
        if requested_device not in {"auto", "cpu", "cuda:0"}:
            raise ModelLoadingError("Device must be auto, cpu, or cuda:0.")
        try:
            torch = importlib.import_module("torch")
        except Exception as error:
            raise ModelLoadingError(
                "PyTorch could not be imported. Install the optional AI dependencies and required runtime libraries."
            ) from error
        actual_device = self._select_device(torch, requested_device)
        cache_dir = self.settings.model_cache_dir.expanduser().resolve()
        cache_key = (str(cache_dir), model_key, actual_device)
        with self._load_lock:
            if cache_key in self._cache:
                return self._cache[cache_key]
            weights = cache_dir / filename
            if weights.is_symlink() or not weights.resolve().is_relative_to(cache_dir):
                raise ModelLoadingError("Model weights must remain inside the configured model cache.")
            if not allow_download and not weights.is_file():
                raise ModelLoadingError(
                    f"{filename} is not cached and downloads are disabled; prepare the model explicitly."
                )
            try:
                cache_dir.mkdir(parents=True, exist_ok=True)
                # Keep optional Ultralytics settings/cache artifacts in the model cache too.
                os.environ.setdefault("YOLO_CONFIG_DIR", str(cache_dir / "ultralytics-settings"))
                os.environ.setdefault("YOLO_AUTOINSTALL", "false")
                ultralytics = importlib.import_module("ultralytics")
                if actual_device == "cpu":
                    torch.set_num_threads(self.settings.cpu_threads)
                logger.info("Loading model %s on %s", model_key, actual_device)
                model = ultralytics.YOLO(str(weights))
                model.to(actual_device)
                raw_names = model.names
                names = ({int(key): str(value) for key, value in raw_names.items()}
                         if isinstance(raw_names, dict)
                         else {index: str(value) for index, value in enumerate(raw_names)})
                if not names or any(key < 0 or not value for key, value in names.items()):
                    raise ValueError("Model class names are unavailable or invalid")
                task = getattr(model, "task", None)
                if task is not None and str(task).lower() != "detect":
                    raise ModelLoadingError(
                        f"{filename} is a {task} checkpoint; only detection models are supported."
                    )
                loaded = LoadedModel(model, model_key, actual_device, names)
                self._cache[cache_key] = loaded
            except ModelLoadingError:
                raise
            except Exception as error:
                raise ModelLoadingError(
                    f"{filename} could not be loaded. Check the optional AI dependencies, "
                    "cached weights, network availability, and requested device."
                ) from error
            self._record_verification(cache_dir, spec, weights, actual_device)
            return loaded

    @staticmethod
    def _record_verification(cache_dir: Path, spec: ModelSpec, weights: Path, device: str) -> None:
        """Best effort: a successful load from this cache marks this exact file verified."""
        try:
            if weights.is_symlink() or not weights.is_file():
                logger.warning("Loaded %s, but its checkpoint is not in the model cache", spec.model_key)
                return
            record = {
                "modelKey": spec.model_key,
                "weightsFilename": spec.weights_filename,
                "fingerprint": file_fingerprint(weights),
                "device": device,
                "verifiedAt": datetime.now(UTC).isoformat(timespec="seconds"),
                "runtime": {
                    "ultralytics": _package_version("ultralytics", "ultralytics-opencv-headless"),
                    "torch": _package_version("torch"),
                },
            }
            target = verification_record_path(cache_dir, spec)
            target.parent.mkdir(parents=True, exist_ok=True)
            partial = target.with_suffix(".json.partial")
            partial.write_text(json.dumps(record, indent=2), encoding="utf-8")
            os.replace(partial, target)
        except Exception:
            logger.warning("Could not record verification for %s", spec.model_key, exc_info=True)

    @staticmethod
    def _select_device(torch: Any, requested: str) -> str:
        if requested == "cpu":
            return "cpu"
        try:
            available = bool(torch.cuda.is_available())
            if requested == "cuda:0":
                if not available or torch.cuda.device_count() < 1:
                    raise ModelLoadingError("CUDA device 0 was requested, but CUDA is unavailable.")
                return "cuda:0"
            return "cuda:0" if available else "cpu"
        except ModelLoadingError:
            raise
        except Exception as error:
            raise ModelLoadingError("CUDA availability could not be determined.") from error
