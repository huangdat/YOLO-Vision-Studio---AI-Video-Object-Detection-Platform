"""Lazy, process-local loading of the explicitly supported inference model."""

from dataclasses import dataclass, field
import importlib
import logging
import os
from pathlib import Path
from threading import Lock, RLock
from typing import Any, ClassVar

from app.config.settings import Settings
from app.core.exceptions import ModelLoadingError

logger = logging.getLogger(__name__)


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

    SUPPORTED_MODELS: ClassVar[dict[str, str]] = {"yolo26s": "yolo26s.pt"}
    _cache: ClassVar[dict[tuple[str, str, str], LoadedModel]] = {}
    _load_lock: ClassVar[Any] = Lock()

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def load(
        self, model_key: str = "yolo26s", device: str | None = None,
        allow_download: bool = True,
    ) -> LoadedModel:
        filename = self.SUPPORTED_MODELS.get(model_key)
        if filename is None:
            raise ModelLoadingError("Unsupported model identifier; Phase 03 supports yolo26s only.")
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
                raise ModelLoadingError("YOLO26s weights are not cached and downloads are disabled.")
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
                loaded = LoadedModel(model, model_key, actual_device, names)
                self._cache[cache_key] = loaded
                return loaded
            except Exception as error:
                raise ModelLoadingError(
                    "YOLO26s could not be loaded. Check the optional AI dependencies, "
                    "cached weights, network availability, and requested device."
                ) from error

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
