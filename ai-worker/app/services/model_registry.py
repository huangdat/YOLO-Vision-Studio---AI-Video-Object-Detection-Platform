"""Approved pretrained detection checkpoints and read-only cache status.

This module is the worker's allowlist. Client input selects a key; it never
selects a path, URL, or filename. Keep it consistent with the backend Flyway
catalog (``tests/test_model_registry.py`` compares both definitions).
Importing this module never imports PyTorch or Ultralytics.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DETECT_TASK = "DETECT"
SIZE_NAMES = {"n": "Nano", "s": "Small", "m": "Medium", "l": "Large", "x": "Extra Large"}
VERIFICATION_DIRECTORY = "verification"


@dataclass(frozen=True)
class ModelSpec:
    model_key: str
    version: str
    model_size: str
    task_type: str
    weights_filename: str

    @property
    def size_name(self) -> str:
        return SIZE_NAMES[self.model_size]


# (version label, key prefix) in release order. Official Ultralytics detection
# checkpoint names are "<prefix><size>.pt", e.g. yolov8n.pt and yolo11n.pt.
_FAMILIES = (("YOLOv8", "yolov8"), ("YOLO11", "yolo11"), ("YOLO12", "yolo12"), ("YOLO26", "yolo26"))

MODEL_SPECS: tuple[ModelSpec, ...] = tuple(
    ModelSpec(f"{prefix}{size}", version, size, DETECT_TASK, f"{prefix}{size}.pt")
    for version, prefix in _FAMILIES
    for size in SIZE_NAMES
)
_BY_KEY = {spec.model_key: spec for spec in MODEL_SPECS}
DEFAULT_MODEL_KEY = "yolo26s"


def get_model_spec(model_key: str) -> ModelSpec | None:
    """Return the approved specification, or None for anything not allowlisted."""
    return _BY_KEY.get(model_key) if isinstance(model_key, str) else None


def supported_model_keys() -> tuple[str, ...]:
    return tuple(_BY_KEY)


class CacheStatus(StrEnum):
    NOT_CACHED = "NOT_CACHED"
    CACHED_UNVERIFIED = "CACHED_UNVERIFIED"
    VERIFIED = "VERIFIED"
    CHANGED_SINCE_VERIFICATION = "CHANGED_SINCE_VERIFICATION"


@dataclass(frozen=True)
class ModelStatus:
    spec: ModelSpec
    cached: bool
    status: CacheStatus
    size_bytes: int | None = None
    verified_at: str | None = None
    verified_device: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """Public status shape; deliberately contains no filesystem paths."""
        return {
            "modelKey": self.spec.model_key,
            "version": self.spec.version,
            "modelSize": self.spec.model_size,
            "taskType": self.spec.task_type,
            "weightsFilename": self.spec.weights_filename,
            "cached": self.cached,
            "status": self.status.value,
            "sizeBytes": self.size_bytes,
            "verifiedAt": self.verified_at,
            "verifiedDevice": self.verified_device,
        }


def verification_record_path(cache_dir: Path, spec: ModelSpec) -> Path:
    return cache_dir / VERIFICATION_DIRECTORY / f"{spec.model_key}.json"


def file_fingerprint(path: Path) -> dict[str, int]:
    stat = path.stat()
    return {"sizeBytes": stat.st_size, "modifiedNs": stat.st_mtime_ns}


def inspect_model(cache_dir: Path, spec: ModelSpec) -> ModelStatus:
    """Inspect one cache entry without loading, importing, or downloading anything.

    A verification record is written only after a successful load from this cache,
    so verification is local to the runtime that owns the cache directory.
    """
    cache_dir = Path(cache_dir).expanduser().resolve()
    weights = cache_dir / spec.weights_filename
    if weights.is_symlink() or not weights.is_file():
        return ModelStatus(spec, cached=False, status=CacheStatus.NOT_CACHED)
    try:
        fingerprint = file_fingerprint(weights)
    except OSError:
        return ModelStatus(spec, cached=False, status=CacheStatus.NOT_CACHED)
    size = fingerprint["sizeBytes"]
    try:
        record = json.loads(verification_record_path(cache_dir, spec).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return ModelStatus(spec, cached=True, status=CacheStatus.CACHED_UNVERIFIED, size_bytes=size)
    except (OSError, ValueError):
        logger.warning("Ignoring an unreadable model verification record for %s", spec.model_key)
        return ModelStatus(spec, cached=True, status=CacheStatus.CACHED_UNVERIFIED, size_bytes=size)
    if not isinstance(record, dict) or record.get("weightsFilename") != spec.weights_filename:
        return ModelStatus(spec, cached=True, status=CacheStatus.CACHED_UNVERIFIED, size_bytes=size)
    if record.get("fingerprint") != fingerprint:
        return ModelStatus(spec, cached=True, status=CacheStatus.CHANGED_SINCE_VERIFICATION, size_bytes=size)
    return ModelStatus(
        spec, cached=True, status=CacheStatus.VERIFIED, size_bytes=size,
        verified_at=record.get("verifiedAt"), verified_device=record.get("device"),
    )


def inspect_models(cache_dir: Path, specs: tuple[ModelSpec, ...] = MODEL_SPECS) -> list[ModelStatus]:
    return [inspect_model(cache_dir, spec) for spec in specs]
