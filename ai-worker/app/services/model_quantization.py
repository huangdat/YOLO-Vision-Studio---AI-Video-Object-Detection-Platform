"""OpenVINO INT8 post-training quantization of approved detection checkpoints (proof of concept).

* Export is explicit (``python -m app.cli models quantize``) and never downloads weights: the FP32
  checkpoint must already be prepared in the model cache.
* Artifacts live in a separate directory (``Settings.quantized_models_path``), one folder per model
  key, so the PyTorch cache and its verification records are untouched.
* A folder is usable only when its ``quantization.json`` manifest is present and consistent: the
  manifest is written last, after the exported model was loaded and run once, and it pins the
  SHA-256 of the FP32 checkpoint it was made from.
* Models are exported with dynamic input shapes so the requested ``imgsz`` is honoured exactly as
  with PyTorch. A static export would make Ultralytics silently replace it with the export size.

Importing this module never imports PyTorch, Ultralytics, or OpenVINO.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from functools import partial
import hashlib
import importlib
from importlib import metadata
import json
import logging
import math
import os
from pathlib import Path
import shutil
from typing import Any
import uuid

from app.config.settings import Settings
from app.core.exceptions import QuantizationError
from app.services.model_registry import ModelSpec, get_model_spec

logger = logging.getLogger(__name__)

INT8_FORMAT = "openvino-int8"
MANIFEST_FILENAME = "quantization.json"
MANIFEST_VERSION = 1
# OpenVINO device used for INT8 inference. A bare "cpu" lets Ultralytics choose OpenVINO's AUTO
# device whenever a GPU is visible, so the CPU plugin is requested explicitly.
OPENVINO_CPU_DEVICE = "intel:cpu"
RECOMMENDED_CALIBRATION_IMAGES = 300


class Int8Status(StrEnum):
    VALID = "VALID"
    NOT_EXPORTED = "NOT_EXPORTED"
    INVALID = "INVALID"
    SOURCE_CHANGED = "SOURCE_CHANGED"


@dataclass(frozen=True)
class Int8ArtifactStatus:
    spec: ModelSpec
    status: Int8Status
    directory: Path
    reason: str | None = None
    size_bytes: int | None = None
    manifest: dict[str, Any] | None = None

    @property
    def available(self) -> bool:
        return self.status == Int8Status.VALID

    def as_dict(self) -> dict[str, Any]:
        """Public status shape; deliberately contains no filesystem paths."""
        manifest = self.manifest or {}
        calibration = manifest.get("calibration") or {}
        return {
            "modelKey": self.spec.model_key,
            "format": INT8_FORMAT,
            "status": self.status.value,
            "reason": self.reason,
            "sizeBytes": self.size_bytes,
            "exportImageSize": manifest.get("imageSize"),
            "calibrationImages": calibration.get("images"),
            "createdAt": manifest.get("createdAt"),
        }


def int8_artifact_dir(root: Path, spec: ModelSpec) -> Path:
    return Path(root) / f"{spec.model_key}_int8_openvino_model"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _directory_size(directory: Path) -> int:
    return sum(item.stat().st_size for item in directory.rglob("*") if item.is_file() and not item.is_symlink())


def inspect_int8_artifact(settings: Settings, spec: ModelSpec, *, check_source: bool = True) -> Int8ArtifactStatus:
    """Inspect one INT8 artifact without importing or loading anything."""
    root = settings.quantized_models_path.expanduser().resolve()
    directory = int8_artifact_dir(root, spec)

    def result(status: Int8Status, reason: str | None = None, manifest: dict[str, Any] | None = None,
               size: int | None = None) -> Int8ArtifactStatus:
        return Int8ArtifactStatus(spec, status, directory, reason, size, manifest)

    if directory.is_symlink() or not directory.is_dir():
        return result(Int8Status.NOT_EXPORTED, "No INT8 artifact has been exported for this model.")
    if not directory.resolve().is_relative_to(root):
        return result(Int8Status.INVALID, "The INT8 artifact must stay inside the quantized model directory.")
    try:
        manifest = json.loads((directory / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return result(Int8Status.INVALID, "The manifest is missing; the export did not finish validation.")
    except (OSError, ValueError):
        return result(Int8Status.INVALID, "The manifest is unreadable.")
    if not isinstance(manifest, dict) or manifest.get("manifestVersion") != MANIFEST_VERSION:
        return result(Int8Status.INVALID, "Unsupported manifest version.")
    if manifest.get("modelKey") != spec.model_key or manifest.get("format") != INT8_FORMAT:
        return result(Int8Status.INVALID, "The manifest describes a different model or format.", manifest)
    if not (manifest.get("validation") or {}).get("passed"):
        return result(Int8Status.INVALID, "The exported model did not pass validation.", manifest)
    files = manifest.get("files")
    if not isinstance(files, dict) or not any(str(name).endswith(".xml") for name in files):
        return result(Int8Status.INVALID, "The manifest lists no OpenVINO model files.", manifest)
    for name, expected in files.items():
        path = directory / str(name)
        if Path(str(name)).name != str(name) or path.is_symlink() or not path.is_file():
            return result(Int8Status.INVALID, f"Artifact file {name} is missing.", manifest)
        if path.stat().st_size != expected:
            return result(Int8Status.INVALID, f"Artifact file {name} changed after export.", manifest)
    size = _directory_size(directory)
    if check_source:
        source = settings.model_cache_dir.expanduser().resolve() / spec.weights_filename
        recorded = (manifest.get("source") or {}).get("sha256")
        if source.is_file() and not source.is_symlink():
            try:
                if sha256_file(source) != recorded:
                    return result(Int8Status.SOURCE_CHANGED,
                                  "The FP32 checkpoint changed since this INT8 model was exported.", manifest, size)
            except OSError:
                return result(Int8Status.INVALID, "The FP32 checkpoint could not be read.", manifest, size)
    return result(Int8Status.VALID, None, manifest, size)


@dataclass(frozen=True)
class CalibrationDataset:
    data_yaml: Path
    images: int
    source: str
    frame_range: tuple[int, int]
    stride: int

    def describe(self) -> dict[str, Any]:
        return {"kind": "video-frames", "source": self.source, "images": self.images,
                "frameRange": list(self.frame_range), "stride": self.stride}


def build_calibration_dataset(
    video: Path, output_dir: Path, names: dict[int, str], *, max_images: int = RECOMMENDED_CALIBRATION_IMAGES,
    start_frame: int = 0, end_frame: int | None = None,
) -> CalibrationDataset:
    """Sample up to ``max_images`` evenly spaced frames from ``[start_frame, end_frame)`` into an
    unlabeled YOLO dataset. Post-training quantization only needs representative inputs, so no
    annotations are written; Ultralytics treats the missing label files as background."""
    if max_images < 1:
        raise QuantizationError("At least one calibration image is required.")
    if start_frame < 0 or (end_frame is not None and end_frame <= start_frame):
        raise QuantizationError("The calibration frame range is empty.")
    cv2 = importlib.import_module("cv2")
    capture = cv2.VideoCapture(str(video))
    try:
        if not capture.isOpened():
            raise QuantizationError("The calibration video could not be opened.")
        total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        stop = min(end_frame, total) if end_frame is not None and total > 0 else (end_frame or total)
        if not stop or stop <= start_frame:
            raise QuantizationError("The calibration video has no frames in the requested range.")
        stride = max(1, (stop - start_frame) // max_images)
        images_dir = output_dir / "images" / "val"
        images_dir.mkdir(parents=True, exist_ok=True)
        written = 0
        index = 0
        while index < stop and written < max_images:
            ok, frame = capture.read()
            if not ok:
                break
            if index >= start_frame and (index - start_frame) % stride == 0:
                if not cv2.imwrite(str(images_dir / f"frame_{index:06d}.jpg"), frame):
                    raise QuantizationError("A calibration frame could not be written.")
                written += 1
            index += 1
    finally:
        capture.release()
    if written == 0:
        raise QuantizationError("No calibration frames could be decoded from the video.")
    data_yaml = output_dir / "data.yaml"
    lines = [f"path: {json.dumps(str(output_dir.resolve()))}", "train: images/val", "val: images/val", "names:"]
    lines += [f"  {key}: {json.dumps(value)}" for key, value in sorted(names.items())]
    data_yaml.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if written < RECOMMENDED_CALIBRATION_IMAGES:
        logger.warning("Only %d calibration images; about %d are recommended for INT8 calibration",
                       written, RECOMMENDED_CALIBRATION_IMAGES)
    return CalibrationDataset(data_yaml, written, Path(video).name, (start_frame, index), stride)


@dataclass(frozen=True)
class ImageCalibrationDataset:
    data_yaml: Path
    images: int
    sources: tuple[dict[str, Any], ...]

    def describe(self) -> dict[str, Any]:
        return {"kind": "image-folders", "images": self.images, "sources": list(self.sources)}


CALIBRATION_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp"}
GENERIC_IMAGE_FOLDERS = {"img1", "images", "image", "frames", "val", "train"}


def build_calibration_dataset_from_images(
    sources: list[Path], output_dir: Path, names: dict[int, str], *,
    max_images: int = RECOMMENDED_CALIBRATION_IMAGES,
) -> ImageCalibrationDataset:
    """Combine evenly spaced images from several folders (for example frames of different scenes)
    into one unlabeled calibration set. Each source gets an equal share of ``max_images``; the
    manifest records, per source, how many images were used and a SHA-256 of their file names."""
    if max_images < 1 or not sources:
        raise QuantizationError("At least one calibration image and one source folder are required.")
    listings = []
    for source in sources:
        files = sorted(path for path in Path(source).iterdir()
                       if path.is_file() and path.suffix.lower() in CALIBRATION_IMAGE_SUFFIXES) \
            if Path(source).is_dir() else []
        if not files:
            raise QuantizationError(f"Calibration folder {Path(source).name} contains no images.")
        listings.append(files)
    images_dir = output_dir / "images" / "val"
    images_dir.mkdir(parents=True, exist_ok=True)
    quotas = [max_images // len(sources) + (1 if index < max_images % len(sources) else 0)
              for index in range(len(sources))]
    provenance = []
    for index, (source, files, quota) in enumerate(zip(sources, listings, quotas)):
        quota = min(quota, len(files))
        step = len(files) / quota if quota else 1
        chosen = [files[int(position * step)] for position in range(quota)]
        for path in chosen:
            shutil.copy2(path, images_dir / f"s{index}_{path.name}")
        digest = hashlib.sha256("\n".join(path.name for path in chosen).encode("utf-8")).hexdigest()
        folder = Path(source).resolve()
        # Generic frame folders (MOT "img1", "images", ...) are named with their parent for provenance.
        name = f"{folder.parent.name}/{folder.name}" if folder.name.lower() in GENERIC_IMAGE_FOLDERS else folder.name
        provenance.append({"name": name, "available": len(files), "used": len(chosen),
                           "first": chosen[0].name, "last": chosen[-1].name, "fileListSha256": digest})
    total = sum(item["used"] for item in provenance)
    data_yaml = output_dir / "data.yaml"
    lines = [f"path: {json.dumps(str(output_dir.resolve()))}", "train: images/val", "val: images/val", "names:"]
    lines += [f"  {key}: {json.dumps(value)}" for key, value in sorted(names.items())]
    data_yaml.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if total < RECOMMENDED_CALIBRATION_IMAGES:
        logger.warning("Only %d calibration images; about %d are recommended for INT8 calibration",
                       total, RECOMMENDED_CALIBRATION_IMAGES)
    return ImageCalibrationDataset(data_yaml, total, tuple(provenance))


@dataclass(frozen=True)
class Int8ExportResult:
    status: Int8ArtifactStatus
    fp32_size_bytes: int
    int8_size_bytes: int
    fake_quantize_nodes: int


def _require(module: str, hint: str) -> Any:
    try:
        return importlib.import_module(module)
    except Exception as error:
        raise QuantizationError(f"{module} is not installed. {hint}") from error


def _package_version(*names: str) -> str | None:
    for name in names:
        try:
            return metadata.version(name)
        except metadata.PackageNotFoundError:
            continue
    return None


def export_int8(
    settings: Settings, model_key: str, *, data: str | Path, image_size: int, fraction: float = 1.0,
    calibration: dict[str, Any] | None = None, validation_image: Path | None = None,
) -> Int8ExportResult:
    """Export, validate, and atomically install the INT8 OpenVINO artifact of one prepared model."""
    spec = get_model_spec(model_key)
    if spec is None:
        raise QuantizationError("Unsupported model identifier; use an approved detection model key.")
    if image_size < 32 or image_size % 32:
        raise QuantizationError("The export image size must be a positive multiple of 32.")
    if not 0 < fraction <= 1 or not math.isfinite(fraction):
        raise QuantizationError("The calibration fraction must be in (0, 1].")
    cache_dir = settings.model_cache_dir.expanduser().resolve()
    weights = cache_dir / spec.weights_filename
    if weights.is_symlink() or not weights.is_file():
        raise QuantizationError(f"{spec.weights_filename} is not prepared; run 'models prepare' first.")
    hint = "Install the optional quantization dependencies: pip install -r requirements-quantization.txt"
    _require("openvino", hint)
    _require("nncf", hint)
    os.environ.setdefault("YOLO_CONFIG_DIR", str(cache_dir / "ultralytics-settings"))
    # Never let Ultralytics pip-install packages while exporting; missing ones fail above instead.
    os.environ.setdefault("YOLO_AUTOINSTALL", "false")
    ultralytics = _require("ultralytics", "Install the AI dependencies (requirements-ai.txt).")

    root = settings.quantized_models_path.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = int8_artifact_dir(root, spec)
    staging = root / f".staging-{spec.model_key}-{uuid.uuid4().hex[:8]}"
    staging.mkdir()
    try:
        source_sha = sha256_file(weights)
        staged_weights = staging / spec.weights_filename
        shutil.copy2(weights, staged_weights)
        fp32 = ultralytics.YOLO(str(staged_weights))
        names = {int(key): str(value) for key, value in dict(fp32.names).items()}
        logger.info("Exporting %s to OpenVINO INT8 (imgsz=%d, data=%s)", spec.model_key, image_size, data)
        try:
            exported = Path(fp32.export(format="openvino", quantize=8, data=str(data), imgsz=image_size,
                                        fraction=fraction, dynamic=True, batch=1, device="cpu", verbose=False))
        except Exception as error:
            raise QuantizationError("OpenVINO INT8 export or calibration failed.") from error
        if not exported.is_dir():
            raise QuantizationError("The exporter did not produce an OpenVINO model directory.")
        validation, fake_quantize = _validate_export(ultralytics, exported, names, image_size, validation_image)
        files = {item.name: item.stat().st_size for item in sorted(exported.iterdir()) if item.is_file()}
        manifest = {
            "manifestVersion": MANIFEST_VERSION,
            "modelKey": spec.model_key,
            "format": INT8_FORMAT,
            "quantize": 8,
            "dynamic": True,
            "imageSize": image_size,
            "source": {"weightsFilename": spec.weights_filename, "sha256": source_sha,
                       "sizeBytes": weights.stat().st_size},
            "calibration": {**(calibration or {"kind": "dataset-yaml", "source": Path(str(data)).name}),
                            "fraction": fraction},
            "files": files,
            "validation": validation,
            "runtime": {
                "ultralytics": _package_version("ultralytics", "ultralytics-opencv-headless"),
                "openvino": _package_version("openvino"),
                "nncf": _package_version("nncf"),
                "torch": _package_version("torch"),
            },
            "createdAt": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        # The manifest is written last: its presence marks a complete, validated export.
        (exported / MANIFEST_FILENAME).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        retired = root / f".retired-{spec.model_key}-{uuid.uuid4().hex[:8]}"
        if target.exists():
            os.replace(target, retired)
        os.replace(exported, target)
        shutil.rmtree(retired, ignore_errors=True)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    status = inspect_int8_artifact(settings, spec)
    if not status.available:
        raise QuantizationError(f"The installed INT8 artifact is not usable: {status.reason}")
    return Int8ExportResult(status, weights.stat().st_size, status.size_bytes or 0, fake_quantize)


def limit_openvino_threads(model: Any, threads: int, artifact_dir: Path) -> int | None:
    """Recompile an Ultralytics OpenVINO model so inference uses at most ``threads`` CPU threads.

    OpenVINO otherwise uses every physical core and ignores both ``AI_CPU_THREADS`` and process
    affinity on Windows. Ultralytics exposes no option for this, so the compiled model of its
    backend is replaced. Call after one predict() (the backend is created lazily). Returns the
    effective thread count, or None when the backend layout is not the expected one, in which case
    nothing is changed.
    """
    backend = getattr(getattr(getattr(model, "predictor", None), "model", None), "backend", None)
    compile_model = getattr(backend, "compile_model", None)
    compiled = getattr(backend, "ov_compiled_model", None)
    core = getattr(getattr(compile_model, "func", None), "__self__", None)
    xml = next(Path(artifact_dir).glob("*.xml"), None)
    if compiled is None or core is None or xml is None or not hasattr(compile_model, "keywords"):
        return None
    config = {**(compile_model.keywords.get("config") or {}), "INFERENCE_NUM_THREADS": int(threads)}
    recompile = partial(compile_model.func, *compile_model.args, **{**compile_model.keywords, "config": config})
    backend.ov_compiled_model = recompile(core.read_model(str(xml)))
    backend.compile_model = recompile
    return int(backend.ov_compiled_model.get_property("INFERENCE_NUM_THREADS"))


def _validate_export(ultralytics: Any, exported: Path, names: dict[int, str], image_size: int,
                     validation_image: Path | None) -> tuple[dict[str, Any], int]:
    """Load the exported model, confirm it is really quantized, and run one inference."""
    openvino = importlib.import_module("openvino")
    xml = next(exported.glob("*.xml"), None)
    if xml is None or not xml.with_suffix(".bin").is_file():
        raise QuantizationError("The OpenVINO export is missing its .xml or .bin file.")
    ov_model = openvino.Core().read_model(str(xml))
    fake_quantize = sum(1 for op in ov_model.get_ops() if op.get_type_name() == "FakeQuantize")
    if fake_quantize == 0:
        raise QuantizationError("The exported model contains no quantized operations.")
    model = ultralytics.YOLO(str(exported), task="detect")
    loaded_names = {int(key): str(value) for key, value in dict(model.names).items()}
    if loaded_names != names:
        raise QuantizationError("The INT8 model's class names differ from the FP32 checkpoint.")
    if validation_image is not None:
        source: Any = str(validation_image)
    else:
        numpy = importlib.import_module("numpy")
        source = numpy.full((image_size, image_size, 3), 114, dtype=numpy.uint8)
    try:
        results = model.predict(source=source, imgsz=image_size, device=OPENVINO_CPU_DEVICE, conf=0.25,
                                save=False, verbose=False)
    except Exception as error:
        raise QuantizationError("The exported INT8 model could not run inference.") from error
    if len(results) != 1 or getattr(results[0], "boxes", None) is None:
        raise QuantizationError("The exported INT8 model returned no detection output.")
    return {"passed": True, "fakeQuantizeNodes": fake_quantize, "boxes": len(results[0].boxes),
            "image": Path(validation_image).name if validation_image is not None else "synthetic"}, fake_quantize
