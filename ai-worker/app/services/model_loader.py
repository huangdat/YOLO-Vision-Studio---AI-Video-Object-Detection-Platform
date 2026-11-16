"""Lazy, process-local loading of the explicitly supported inference model."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
import importlib
from importlib import metadata
from importlib.util import find_spec
import json
import logging
import os
from pathlib import Path
from threading import Lock, RLock
from typing import Any, ClassVar

from app.config.settings import Settings
from app.core.exceptions import Int8ModelUnavailableError, ModelLoadingError
from app.services.model_registry import (
    DEFAULT_MODEL_KEY, MODEL_SPECS, ModelSpec, file_fingerprint, get_model_spec, verification_record_path,
)

logger = logging.getLogger(__name__)


def describe_device(torch: Any, device: str) -> str:
    """Log label of a device, e.g. "cuda:0 (NVIDIA GeForce GTX 1650)"; never raises."""
    if device.startswith("cuda"):
        try:
            return f"{device} ({torch.cuda.get_device_name(0)})"
        except Exception:
            return device
    return device


def openvino_available() -> bool:
    """Whether the optional OpenVINO runtime is installed (checked without importing it)."""
    return find_spec("openvino") is not None


def precision_configuration(settings: Settings) -> str:
    """One startup log line describing the configured precision; per-model loads log what was used."""
    if settings.model_precision == "fp32":
        return "Model precision: FP32 (PyTorch)"
    return (f"Model precision: INT8 requested (OpenVINO installed: {openvino_available()}, "
            f"fallback to FP32: {settings.int8_fallback_to_fp32}, artifacts: {settings.quantized_models_path})")


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
    # "fp32" (PyTorch checkpoint) or "int8" (OpenVINO artifact). ``device`` stays the public device
    # name ("cpu") for results and APIs; ``runtime_device`` is what predict() needs when it differs.
    precision: str = "fp32"
    runtime_device: str | None = None

    @property
    def predict_device(self) -> str:
        return self.runtime_device or self.device

    @property
    def runtime(self) -> str:
        """The inference runtime actually in use (logged; never inferred from configuration)."""
        return "OpenVINO" if (self.runtime_device or "").startswith("intel") else "PyTorch"


class ModelLoader:
    """Only explicit inference/preparation calls may import AI packages or fetch weights."""

    # Derived from the registry; kept for callers that only need key -> checkpoint.
    SUPPORTED_MODELS: ClassVar[dict[str, str]] = {
        spec.model_key: spec.weights_filename for spec in MODEL_SPECS
    }
    _cache: ClassVar[dict[tuple[str, str, str, str], LoadedModel]] = {}
    _load_lock: ClassVar[Any] = Lock()

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @classmethod
    def evict(cls, keep: set[str]) -> list[str]:
        """Drop process-cached models whose key is not in ``keep``; returns the evicted keys."""
        with cls._load_lock:
            evicted = [key for key in cls._cache if key[1] not in keep]
            for key in evicted:
                del cls._cache[key]
        return [key[1] for key in evicted]

    def load(
        self, model_key: str = DEFAULT_MODEL_KEY, device: str | None = None,
        allow_download: bool = True, record_verification: bool = True, precision: str | None = None,
    ) -> LoadedModel:
        """Load one approved model. ``precision`` overrides ``AI_MODEL_PRECISION``; an explicit
        ``precision="int8"`` never falls back to FP32, so benchmarks cannot measure the wrong model."""
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
        requested_precision = precision or self.settings.model_precision
        if requested_precision not in {"fp32", "int8"}:
            raise ModelLoadingError("Precision must be fp32 or int8.")
        # INT8 is an OpenVINO CPU artifact: with the "auto" policy it runs on the CPU even when a GPU
        # is present (FP32 jobs still use the GPU). An explicit cuda:0 request stays an error below.
        policy_device = "cpu" if requested_precision == "int8" and requested_device == "auto" else requested_device
        actual_device = self._select_device(torch, policy_device)
        int8_artifact = None
        strict = precision is not None or not self.settings.int8_fallback_to_fp32
        if requested_precision == "int8":
            int8_artifact = self._int8_artifact(spec, actual_device, strict)
            if int8_artifact is None:  # FP32 fallback: the normal device policy applies again (GPU if auto)
                actual_device = self._select_device(torch, requested_device)
        cache_dir = self.settings.model_cache_dir.expanduser().resolve()
        cache_key = (str(cache_dir), model_key, actual_device, "int8" if int8_artifact is not None else "fp32")
        with self._load_lock:
            if cache_key in self._cache:
                return self._cache[cache_key]
            if int8_artifact is not None:
                try:
                    return self._load_int8(torch, spec, int8_artifact, cache_dir, cache_key)
                except ModelLoadingError as error:
                    if strict:
                        raise
                    logger.warning("Using the FP32 model for %s; the INT8 runtime could not be initialised (%s)",
                                   model_key, error.__cause__ or error)
                    actual_device = self._select_device(torch, requested_device)
                    cache_key = (str(cache_dir), model_key, actual_device, "fp32")
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
                logger.info("Loading model %s on %s (fp32, PyTorch)", model_key, describe_device(torch, actual_device))
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
            if record_verification:
                # Read-only consumers of a shared cache (the live worker) skip this write.
                self._record_verification(cache_dir, spec, weights, actual_device)
            return loaded

    def _int8_artifact(self, spec: ModelSpec, device: str, strict: bool) -> Any:
        """The validated INT8 artifact to load, or None to load the FP32 checkpoint instead."""
        from app.services.model_quantization import inspect_int8_artifact

        if device != "cpu":
            reason = f"INT8 OpenVINO models run on CPU only, but {device} was selected"
        elif not openvino_available():
            reason = "OpenVINO is not installed in this image (build with INSTALL_OPENVINO=true)"
        else:
            status = inspect_int8_artifact(self.settings, spec)
            if status.available:
                return status
            reason = f"{status.status.value}: {status.reason}"
        if strict:
            raise Int8ModelUnavailableError(f"INT8 model for {spec.model_key} is unavailable ({reason.rstrip('.')}).")
        logger.warning("Using the FP32 model for %s; INT8 is unavailable (%s)", spec.model_key, reason)
        return None

    def _load_int8(self, torch: Any, spec: ModelSpec, artifact: Any, cache_dir: Path,
                   cache_key: tuple[str, str, str, str]) -> LoadedModel:
        from app.services.model_quantization import OPENVINO_CPU_DEVICE, limit_openvino_threads

        try:
            os.environ.setdefault("YOLO_CONFIG_DIR", str(cache_dir / "ultralytics-settings"))
            os.environ.setdefault("YOLO_AUTOINSTALL", "false")
            ultralytics = importlib.import_module("ultralytics")
            torch.set_num_threads(self.settings.cpu_threads)  # pre/post-processing still uses PyTorch
            logger.info("Loading INT8 OpenVINO model %s on CPU", spec.model_key)
            # Exported models are not PyTorch modules: no .to(device); the device is chosen per predict().
            model = ultralytics.YOLO(str(artifact.directory), task="detect")
            raw_names = model.names
            names = ({int(key): str(value) for key, value in raw_names.items()}
                     if isinstance(raw_names, dict)
                     else {index: str(value) for index, value in enumerate(raw_names)})
            if not names or any(key < 0 or not value for key, value in names.items()):
                raise ValueError("Model class names are unavailable or invalid")
            # One tiny warm-up creates the OpenVINO backend so its thread count can be capped.
            numpy = importlib.import_module("numpy")
            model.predict(source=numpy.zeros((64, 64, 3), dtype=numpy.uint8), imgsz=64,
                          device=OPENVINO_CPU_DEVICE, save=False, verbose=False)
            threads = limit_openvino_threads(model, self.settings.cpu_threads, artifact.directory)
        except Exception as error:
            raise ModelLoadingError(
                f"The INT8 model for {spec.model_key} could not be loaded. Check that the optional "
                "quantization dependencies (OpenVINO) are installed."
            ) from error
        if threads is None:
            logger.warning("Could not cap OpenVINO threads for %s; it may use every CPU core", spec.model_key)
        loaded = LoadedModel(model, spec.model_key, "cpu", names, precision="int8",
                             runtime_device=OPENVINO_CPU_DEVICE)
        self._cache[cache_key] = loaded
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
                    raise ModelLoadingError(
                        "CUDA device 0 was requested, but CUDA is unavailable. Use AI_DEVICE=auto or cpu, or run "
                        "the GPU image (TORCH_VARIANT=cu126) with GPU access (compose.gpu.yaml).")
                return "cuda:0"
            return "cuda:0" if available else "cpu"
        except ModelLoadingError:
            raise
        except Exception as error:
            raise ModelLoadingError("CUDA availability could not be determined.") from error
