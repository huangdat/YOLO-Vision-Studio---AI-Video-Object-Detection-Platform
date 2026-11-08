import json
import os
from pathlib import Path
import re

import pytest

from app.services.model_registry import (
    DEFAULT_MODEL_KEY,
    MODEL_SPECS,
    CacheStatus,
    file_fingerprint,
    get_model_spec,
    inspect_model,
    inspect_models,
    supported_model_keys,
    verification_record_path,
)

MIGRATIONS = Path(__file__).resolve().parents[2] / "backend" / "src" / "main" / "resources" / "db" / "migration"
EXPECTED_VERSIONS = {"yolov8": "YOLOv8", "yolo11": "YOLO11", "yolo12": "YOLO12", "yolo26": "YOLO26"}


def test_registry_contains_exactly_the_twenty_approved_detection_checkpoints() -> None:
    expected = {f"{prefix}{size}" for prefix in EXPECTED_VERSIONS for size in "nsmlx"}

    assert len(MODEL_SPECS) == 20
    assert set(supported_model_keys()) == expected
    assert len(set(supported_model_keys())) == 20
    assert DEFAULT_MODEL_KEY == "yolo26s"


@pytest.mark.parametrize("spec", MODEL_SPECS, ids=lambda spec: spec.model_key)
def test_each_key_maps_to_its_exact_official_checkpoint(spec) -> None:
    prefix, size = spec.model_key[:-1], spec.model_key[-1]

    assert spec.weights_filename == f"{spec.model_key}.pt"
    assert spec.version == EXPECTED_VERSIONS[prefix]
    assert spec.model_size == size
    assert spec.task_type == "DETECT"
    assert spec.size_name in {"Nano", "Small", "Medium", "Large", "Extra Large"}


def test_examples_resolve_to_the_documented_filenames() -> None:
    assert get_model_spec("yolov8n").weights_filename == "yolov8n.pt"
    assert get_model_spec("yolo26s").weights_filename == "yolo26s.pt"
    assert get_model_spec("yolo11x").size_name == "Extra Large"


@pytest.mark.parametrize("identifier", [
    "yolov5s", "yolo26s.pt", "../yolo26s", "yolo26s-seg", "yolo11n-pose", "yolo11n-cls", "YOLO26S", "", None, 5,
])
def test_unapproved_or_path_like_identifiers_are_not_resolved(identifier) -> None:
    assert get_model_spec(identifier) is None


def _flyway_catalog() -> set[tuple[str, str, str, str, str]]:
    rows: set[tuple[str, str, str, str, str]] = set()
    pattern = re.compile(r"\(\s*'([^']+)'\s*,\s*'([^']+)'\s*,\s*'([^']+)'\s*,\s*'([^']+)'\s*,\s*'([^']+)'\s*,")
    for migration in sorted(MIGRATIONS.glob("V*__*.sql")):
        sql = migration.read_text(encoding="utf-8")
        if "INSERT INTO model_configs" in sql:
            rows.update(pattern.findall(sql))
    return rows


@pytest.mark.skipif(not MIGRATIONS.is_dir(), reason="backend migrations are not part of this checkout")
def test_backend_flyway_catalog_matches_the_worker_registry() -> None:
    expected = {(spec.model_key, spec.version, spec.model_size, spec.task_type, spec.weights_filename)
                for spec in MODEL_SPECS}

    assert _flyway_catalog() == expected


@pytest.mark.skipif(not MIGRATIONS.is_dir(), reason="backend migrations are not part of this checkout")
def test_flyway_seeds_never_enable_models_or_overwrite_existing_rows() -> None:
    for migration in MIGRATIONS.glob("V*__*.sql"):
        sql = migration.read_text(encoding="utf-8")
        if "INSERT INTO model_configs" in sql:
            assert not re.search(r"\bTRUE\b", sql, re.IGNORECASE), migration.name
            assert "UPDATE" not in sql.upper(), migration.name


def _write_weights(cache: Path, filename: str, content: bytes = b"weights") -> Path:
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / filename
    path.write_bytes(content)
    return path


def _write_record(cache: Path, model_key: str, weights: Path) -> None:
    spec = get_model_spec(model_key)
    record = verification_record_path(cache, spec)
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(json.dumps({
        "modelKey": model_key, "weightsFilename": spec.weights_filename,
        "fingerprint": file_fingerprint(weights), "device": "cpu", "verifiedAt": "2026-11-08T00:00:00+00:00",
    }), encoding="utf-8")


def test_missing_weights_are_reported_as_not_cached(tmp_path: Path) -> None:
    status = inspect_model(tmp_path, get_model_spec("yolov8n"))

    assert status.status == CacheStatus.NOT_CACHED
    assert not status.cached and status.size_bytes is None


def test_a_cached_file_is_not_verified_until_it_has_been_loaded(tmp_path: Path) -> None:
    _write_weights(tmp_path, "yolov8n.pt", b"12345")

    status = inspect_model(tmp_path, get_model_spec("yolov8n"))

    assert status.status == CacheStatus.CACHED_UNVERIFIED
    assert status.cached and status.size_bytes == 5


def test_a_matching_verification_record_reports_verified(tmp_path: Path) -> None:
    weights = _write_weights(tmp_path, "yolo11n.pt")
    _write_record(tmp_path, "yolo11n", weights)

    status = inspect_model(tmp_path, get_model_spec("yolo11n"))

    assert status.status == CacheStatus.VERIFIED
    assert status.verified_device == "cpu"


def test_a_replaced_checkpoint_loses_its_verified_status(tmp_path: Path) -> None:
    weights = _write_weights(tmp_path, "yolo12n.pt", b"original")
    _write_record(tmp_path, "yolo12n", weights)
    weights.write_bytes(b"replaced and longer")

    assert inspect_model(tmp_path, get_model_spec("yolo12n")).status == CacheStatus.CHANGED_SINCE_VERIFICATION


def test_a_record_for_a_different_checkpoint_or_a_corrupt_record_is_not_trusted(tmp_path: Path) -> None:
    weights = _write_weights(tmp_path, "yolo26n.pt")
    record = verification_record_path(tmp_path, get_model_spec("yolo26n"))
    record.parent.mkdir(parents=True)
    record.write_text(json.dumps({"weightsFilename": "yolo26s.pt", "fingerprint": file_fingerprint(weights)}))
    assert inspect_model(tmp_path, get_model_spec("yolo26n")).status == CacheStatus.CACHED_UNVERIFIED

    record.write_text("{not json")
    assert inspect_model(tmp_path, get_model_spec("yolo26n")).status == CacheStatus.CACHED_UNVERIFIED


def test_a_directory_named_like_a_checkpoint_is_not_cached(tmp_path: Path) -> None:
    (tmp_path / "yolov8s.pt").mkdir()

    assert inspect_model(tmp_path, get_model_spec("yolov8s")).status == CacheStatus.NOT_CACHED


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlinks unavailable")
def test_a_symlinked_checkpoint_is_not_reported_as_cached(tmp_path: Path) -> None:
    target = _write_weights(tmp_path / "elsewhere", "anything.pt")
    try:
        (tmp_path / "yolov8m.pt").symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is not permitted")

    assert inspect_model(tmp_path, get_model_spec("yolov8m")).status == CacheStatus.NOT_CACHED


def test_status_listing_covers_every_model_and_exposes_no_paths(tmp_path: Path) -> None:
    _write_weights(tmp_path, "yolo26s.pt")

    rows = [status.as_dict() for status in inspect_models(tmp_path)]

    assert [row["modelKey"] for row in rows] == list(supported_model_keys())
    assert {row["status"] for row in rows} == {"NOT_CACHED", "CACHED_UNVERIFIED"}
    assert str(tmp_path) not in json.dumps(rows)
