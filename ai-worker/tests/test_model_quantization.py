"""INT8 (OpenVINO) quantization PoC: artifact inspection, calibration data, loading, and fallback.

Unit tests use fake modules and synthetic files; they never import OpenVINO or export a model.
The last test runs real INT8 tracking only when OpenVINO, an exported yolo11n artifact, and a local
sample video are all available, and is skipped otherwise.
"""

from importlib.util import find_spec
import json
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import sys

import pytest

from app import cli
from app.config.settings import Settings
from app.core.exceptions import ModelLoadingError, QuantizationError
from app.services.detection_service import DetectionService
from app.services.model_loader import LoadedModel, ModelLoader
from app.services.model_quantization import (
    INT8_FORMAT, MANIFEST_FILENAME, MANIFEST_VERSION, OPENVINO_CPU_DEVICE, Int8Status,
    build_calibration_dataset, export_int8, inspect_int8_artifact, int8_artifact_dir, limit_openvino_threads,
    sha256_file,
)
from app.services.model_registry import get_model_spec

SPEC = get_model_spec("yolo11n")
NAMES = {0: "person", 2: "car"}


def settings_for(tmp_path: Path, **values) -> Settings:
    return Settings(model_cache_dir=tmp_path / "models", **values)


def write_weights(settings: Settings, content: bytes = b"fp32-weights") -> Path:
    weights = settings.model_cache_dir / SPEC.weights_filename
    weights.parent.mkdir(parents=True, exist_ok=True)
    weights.write_bytes(content)
    return weights


def write_artifact(settings: Settings, *, source: Path | None = None, **overrides) -> Path:
    directory = int8_artifact_dir(settings.quantized_models_path, SPEC)
    directory.mkdir(parents=True)
    (directory / "yolo11n.xml").write_text("<net/>", encoding="utf-8")
    (directory / "yolo11n.bin").write_bytes(b"\x00" * 64)
    (directory / "metadata.yaml").write_text("task: detect\n", encoding="utf-8")
    manifest = {
        "manifestVersion": MANIFEST_VERSION, "modelKey": "yolo11n", "format": INT8_FORMAT, "imageSize": 640,
        "source": {"sha256": sha256_file(source) if source else None},
        "calibration": {"kind": "video-frames", "images": 300},
        "files": {item.name: item.stat().st_size for item in directory.iterdir()},
        "validation": {"passed": True, "fakeQuantizeNodes": 12},
        "createdAt": "2026-11-15T00:00:00+00:00",
    }
    manifest.update(overrides)
    (directory / MANIFEST_FILENAME).write_text(json.dumps(manifest), encoding="utf-8")
    return directory


# --- Settings -----------------------------------------------------------------------------------

def test_precision_defaults_to_fp32_and_artifacts_use_a_separate_directory(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)

    assert settings.model_precision == "fp32"
    assert settings.int8_fallback_to_fp32 is True
    assert settings.quantized_models_path == tmp_path / "models" / "quantized"
    assert settings_for(tmp_path, quantized_model_dir=tmp_path / "int8").quantized_models_path == tmp_path / "int8"


def test_precision_is_read_from_the_environment_and_validated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_MODEL_PRECISION", "int8")
    assert Settings().model_precision == "int8"
    monkeypatch.setenv("AI_MODEL_PRECISION", "int4")
    with pytest.raises(ValueError):
        Settings()


# --- Artifact inspection ------------------------------------------------------------------------

def test_missing_artifact_is_not_exported(tmp_path: Path) -> None:
    status = inspect_int8_artifact(settings_for(tmp_path), SPEC)

    assert status.status == Int8Status.NOT_EXPORTED
    assert not status.available


def test_complete_artifact_from_the_current_checkpoint_is_valid(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    write_artifact(settings, source=write_weights(settings))

    status = inspect_int8_artifact(settings, SPEC)

    assert status.status == Int8Status.VALID
    assert status.available
    public = status.as_dict()
    assert public["calibrationImages"] == 300 and public["exportImageSize"] == 640
    assert str(tmp_path) not in json.dumps(public)


def test_changed_fp32_checkpoint_invalidates_the_int8_artifact(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    weights = write_weights(settings)
    write_artifact(settings, source=weights)
    weights.write_bytes(b"different-checkpoint")

    assert inspect_int8_artifact(settings, SPEC).status == Int8Status.SOURCE_CHANGED


@pytest.mark.parametrize("damage", ["manifest", "truncated", "unvalidated", "other-model", "version"])
def test_incomplete_or_tampered_artifacts_are_invalid(tmp_path: Path, damage: str) -> None:
    settings = settings_for(tmp_path)
    overrides = {"unvalidated": {"validation": {"passed": False}}, "other-model": {"modelKey": "yolo11s"},
                 "version": {"manifestVersion": 99}}.get(damage, {})
    directory = write_artifact(settings, source=write_weights(settings), **overrides)
    if damage == "manifest":
        (directory / MANIFEST_FILENAME).unlink()
    if damage == "truncated":
        (directory / "yolo11n.bin").write_bytes(b"\x00")

    assert inspect_int8_artifact(settings, SPEC).status == Int8Status.INVALID


# --- Calibration dataset ------------------------------------------------------------------------

def _write_video(path: Path, frames: int) -> None:
    import cv2
    import numpy as np

    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10, (64, 48))
    for index in range(frames):
        writer.write(np.full((48, 64, 3), index * 5 % 255, dtype=np.uint8))
    writer.release()


def test_calibration_frames_are_sampled_evenly_into_an_unlabeled_dataset(tmp_path: Path) -> None:
    video = tmp_path / "clip.avi"
    _write_video(video, 40)

    dataset = build_calibration_dataset(video, tmp_path / "calibration", NAMES, max_images=5, end_frame=20)

    images = sorted((tmp_path / "calibration" / "images" / "val").glob("*.jpg"))
    assert dataset.images == 5 and dataset.stride == 4
    assert [image.name for image in images] == [f"frame_{index:06d}.jpg" for index in (0, 4, 8, 12, 16)]
    assert not (tmp_path / "calibration" / "labels").exists()
    yaml = dataset.data_yaml.read_text(encoding="utf-8")
    assert "val: images/val" in yaml and '0: "person"' in yaml and '2: "car"' in yaml
    assert dataset.describe()["kind"] == "video-frames"


@pytest.mark.parametrize("arguments", [{"max_images": 0}, {"start_frame": 10, "end_frame": 10},
                                       {"start_frame": 50}])
def test_calibration_rejects_empty_requests(tmp_path: Path, arguments) -> None:
    video = tmp_path / "clip.avi"
    _write_video(video, 20)

    with pytest.raises(QuantizationError):
        build_calibration_dataset(video, tmp_path / "calibration", NAMES, **arguments)


# --- Export preconditions (no AI packages needed) -----------------------------------------------

@pytest.mark.parametrize(("model_key", "image_size", "message"), [
    ("yolov5s", 640, "Unsupported"), ("yolo11n", 100, "multiple of 32"), ("yolo11n", 640, "not prepared"),
])
def test_export_rejects_invalid_requests_before_importing_ai_packages(
    tmp_path: Path, model_key: str, image_size: int, message: str,
) -> None:
    with pytest.raises(QuantizationError, match=message):
        export_int8(settings_for(tmp_path), model_key, data="data.yaml", image_size=image_size)


# --- Loading ------------------------------------------------------------------------------------

@pytest.fixture
def loader_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(ModelLoader, "_cache", {})
    torch = SimpleNamespace(
        cuda=SimpleNamespace(is_available=Mock(return_value=False), device_count=Mock(return_value=0)),
        set_num_threads=Mock(),
    )
    models: list[SimpleNamespace] = []

    def factory(path: str, task: str | None = None) -> SimpleNamespace:
        model = SimpleNamespace(path=path, task_argument=task, names=dict(NAMES), to=Mock(), predict=Mock())
        models.append(model)
        return model

    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "ultralytics", SimpleNamespace(YOLO=Mock(side_effect=factory)))
    return torch, models


def test_int8_precision_loads_the_openvino_artifact_without_moving_it_to_a_torch_device(
    tmp_path: Path, loader_environment,
) -> None:
    _, models = loader_environment
    settings = settings_for(tmp_path, model_precision="int8")
    directory = write_artifact(settings, source=write_weights(settings))

    loaded = ModelLoader(settings).load("yolo11n", "cpu")

    assert models[0].path == str(directory.resolve()) and models[0].task_argument == "detect"
    models[0].to.assert_not_called()
    assert models[0].predict.call_args.kwargs["device"] == OPENVINO_CPU_DEVICE  # warm-up on the CPU plugin
    assert (loaded.precision, loaded.device, loaded.predict_device) == ("int8", "cpu", OPENVINO_CPU_DEVICE)
    assert loaded.names == NAMES


def test_fp32_and_int8_models_are_cached_separately(tmp_path: Path, loader_environment) -> None:
    _, models = loader_environment
    settings = settings_for(tmp_path)
    write_artifact(settings, source=write_weights(settings))
    loader = ModelLoader(settings)

    fp32 = loader.load("yolo11n", "cpu")
    int8 = loader.load("yolo11n", "cpu", precision="int8")

    assert (fp32.precision, int8.precision) == ("fp32", "int8")
    assert fp32.predict_device == "cpu"
    assert loader.load("yolo11n", "cpu", precision="int8") is int8
    assert len(models) == 2


def test_configured_int8_without_an_artifact_falls_back_to_fp32_with_a_warning(
    tmp_path: Path, loader_environment, caplog: pytest.LogCaptureFixture,
) -> None:
    _, models = loader_environment
    settings = settings_for(tmp_path, model_precision="int8")
    write_weights(settings)

    with caplog.at_level(logging.WARNING):
        loaded = ModelLoader(settings).load("yolo11n", "cpu", record_verification=False)

    assert loaded.precision == "fp32"
    assert models[0].path.endswith("yolo11n.pt")
    assert "INT8 is unavailable" in caplog.text


def test_int8_is_strict_when_fallback_is_disabled_or_precision_is_explicit(tmp_path: Path, loader_environment) -> None:
    _, models = loader_environment
    settings = settings_for(tmp_path, model_precision="int8", int8_fallback_to_fp32=False)
    write_weights(settings)

    with pytest.raises(ModelLoadingError, match="INT8 model for yolo11n is unavailable"):
        ModelLoader(settings).load("yolo11n", "cpu")
    with pytest.raises(ModelLoadingError, match="NOT_EXPORTED"):
        ModelLoader(settings_for(tmp_path)).load("yolo11n", "cpu", precision="int8")
    assert models == []


def test_int8_is_cpu_only(tmp_path: Path, loader_environment) -> None:
    torch, _ = loader_environment
    torch.cuda.is_available.return_value = True
    torch.cuda.device_count.return_value = 1
    settings = settings_for(tmp_path, model_precision="int8")
    write_artifact(settings, source=write_weights(settings))

    assert ModelLoader(settings).load("yolo11n", "auto", record_verification=False).precision == "fp32"
    with pytest.raises(ModelLoadingError, match="CPU only"):
        ModelLoader(settings).load("yolo11n", "cuda:0", precision="int8")


def test_openvino_backend_is_recompiled_with_the_configured_thread_count(tmp_path: Path) -> None:
    (tmp_path / "model.xml").write_text("<net/>", encoding="utf-8")

    class FakeCore:
        def read_model(self, path: str) -> str:
            return f"read:{Path(path).name}"

        def compile_model(self, model: str, device_name: str, config: dict) -> SimpleNamespace:
            return SimpleNamespace(model=model, device=device_name, config=config,
                                   get_property=lambda name: config[name])

    from functools import partial

    core = FakeCore()
    backend = SimpleNamespace(compile_model=partial(core.compile_model, device_name="CPU",
                                                    config={"PERFORMANCE_HINT": "LATENCY"}),
                              ov_compiled_model=object())
    model = SimpleNamespace(predictor=SimpleNamespace(model=SimpleNamespace(backend=backend)))

    assert limit_openvino_threads(model, 3, tmp_path) == 3
    assert backend.ov_compiled_model.model == "read:model.xml"
    assert backend.ov_compiled_model.config == {"PERFORMANCE_HINT": "LATENCY", "INFERENCE_NUM_THREADS": 3}
    assert backend.compile_model("again").config["INFERENCE_NUM_THREADS"] == 3  # later reshapes keep the cap
    assert limit_openvino_threads(SimpleNamespace(predictor=None), 3, tmp_path) is None


def test_inference_uses_the_runtime_device_of_an_int8_model() -> None:
    frame = SimpleNamespace(boxes=SimpleNamespace(cls=[2], conf=[0.9], xyxy=[(1, 2, 3, 4)]), speed={"inference": 2.0})
    model = SimpleNamespace(predict=Mock(return_value=[frame]))
    loaded = LoadedModel(model, "yolo11n", "cpu", NAMES, precision="int8", runtime_device=OPENVINO_CPU_DEVICE)

    detected = DetectionService().detect_image("image", loaded, 0.3, 640, [2])

    assert model.predict.call_args.kwargs["device"] == OPENVINO_CPU_DEVICE
    assert detected.boxes[0].label == "car"


# --- CLI ----------------------------------------------------------------------------------------

def test_quantize_requires_exactly_one_calibration_source() -> None:
    with pytest.raises(SystemExit) as missing:
        cli.main(["models", "quantize", "--model", "yolo11n"])
    with pytest.raises(SystemExit) as both:
        cli.main(["models", "quantize", "--model", "yolo11n", "--data", "a.yaml", "--calibration-video", "v.mp4"])
    assert missing.value.code == both.value.code == 2


def test_int8_status_reports_artifacts_without_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setenv("AI_MODEL_CACHE_DIR", str(tmp_path / "models"))
    settings = settings_for(tmp_path)
    write_artifact(settings, source=write_weights(settings))

    assert cli.main(["models", "int8-status", "--model", "yolo11n", "--json"]) == 0

    output = capsys.readouterr().out
    assert json.loads(output) == [{**inspect_int8_artifact(settings, SPEC).as_dict()}]
    assert '"status": "VALID"' in output and str(tmp_path) not in output


# --- Real INT8 tracking (optional) --------------------------------------------------------------

WORKER_ROOT = Path(__file__).resolve().parents[1]
REAL_SETTINGS = Settings(model_cache_dir=WORKER_ROOT / "model-cache")
SAMPLE_VIDEO = WORKER_ROOT / "temp" / "cli-input" / "street.mp4"


@pytest.mark.skipif(
    find_spec("openvino") is None or find_spec("ultralytics") is None
    or not inspect_int8_artifact(REAL_SETTINGS, SPEC, check_source=False).available or not SAMPLE_VIDEO.is_file(),
    reason="needs OpenVINO, an exported yolo11n INT8 artifact, and temp/cli-input/street.mp4",
)
def test_real_int8_model_runs_through_the_bytetrack_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.object_tracking import ByteTrackParameters, ObjectTracker

    monkeypatch.setattr(ModelLoader, "_cache", {})
    loaded = ModelLoader(REAL_SETTINGS).load("yolo11n", "cpu", record_verification=False, precision="int8")
    tracker = ObjectTracker(ByteTrackParameters.for_confidence(0.25, 30), trajectory_length=5)
    try:
        frames = list(DetectionService().iter_frames(SAMPLE_VIDEO, loaded, 0.25, 640, [0, 1, 2, 3, 5, 7],
                                                     tracker=tracker))
    finally:
        tracker.close()

    assert loaded.precision == "int8"
    assert len(frames) > 0
    assert all(frame.tracked is not None and frame.image is not None for frame in frames)
    assert any(box.track_id is not None for frame in frames for box in frame.boxes)
