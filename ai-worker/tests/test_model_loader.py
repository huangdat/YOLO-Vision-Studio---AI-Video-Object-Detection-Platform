from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import sys

import pytest

from app.config.settings import Settings
from app.core.exceptions import ModelLoadingError
from app.services.model_loader import ModelLoader


@pytest.fixture
def model_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(ModelLoader, "_cache", {})
    torch = SimpleNamespace(
        cuda=SimpleNamespace(is_available=Mock(return_value=False), device_count=Mock(return_value=0)),
        set_num_threads=Mock(),
    )
    model = SimpleNamespace(names={0: "person", 2: "car"}, to=Mock())
    factory = Mock(return_value=model)
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "ultralytics", SimpleNamespace(YOLO=factory))
    settings = Settings(model_cache_dir=tmp_path / "models", cpu_threads=2)
    return settings, torch, factory, model


def test_loads_only_the_supported_weights_into_the_configured_cache(model_environment) -> None:
    settings, torch, factory, model = model_environment

    loaded = ModelLoader(settings).load("yolo26s", "cpu")

    factory.assert_called_once_with(str(settings.model_cache_dir.resolve() / "yolo26s.pt"))
    model.to.assert_called_once_with("cpu")
    torch.set_num_threads.assert_called_once_with(2)
    assert loaded.model_key == "yolo26s"
    assert loaded.names == {0: "person", 2: "car"}
    assert loaded.device == "cpu"


@pytest.mark.parametrize("identifier", [
    "../other.pt", "https://example.com/model.pt", "yolo26s.pt", "yolov5s", "yolo26s-seg",
    "yolo11s-pose", "YOLO11S", "C:\\models\\yolo11s.pt", "/tmp/yolo11s.pt", "",
])
def test_rejects_unsupported_or_filesystem_model_identifiers(model_environment, identifier: str) -> None:
    settings, _, factory, _ = model_environment

    with pytest.raises(ModelLoadingError, match="Unsupported model"):
        ModelLoader(settings).load(identifier)

    factory.assert_not_called()


def test_auto_falls_back_to_real_cpu_when_cuda_is_unavailable(model_environment) -> None:
    settings, _, _, _ = model_environment

    assert ModelLoader(settings).load(device="auto").device == "cpu"


@pytest.mark.parametrize("device", ["auto", "cuda:0"])
def test_uses_cuda_when_it_is_available(model_environment, device: str) -> None:
    settings, torch, _, model = model_environment
    torch.cuda.is_available.return_value = True
    torch.cuda.device_count.return_value = 1

    assert ModelLoader(settings).load(device=device).device == "cuda:0"
    model.to.assert_called_once_with("cuda:0")


def test_explicit_unavailable_cuda_is_a_meaningful_error(model_environment) -> None:
    settings, _, factory, _ = model_environment

    with pytest.raises(ModelLoadingError, match="CUDA.*unavailable"):
        ModelLoader(settings).load(device="cuda:0")

    factory.assert_not_called()


def test_reuses_models_across_loader_instances_in_the_process(model_environment) -> None:
    settings, _, factory, _ = model_environment

    first = ModelLoader(settings).load(device="cpu")
    second = ModelLoader(settings).load(device="auto")

    assert first is second
    factory.assert_called_once()


def test_does_not_attempt_a_download_when_downloads_are_disabled(model_environment) -> None:
    settings, _, factory, _ = model_environment

    with pytest.raises(ModelLoadingError, match="downloads are disabled"):
        ModelLoader(settings).load(device="cpu", allow_download=False)

    factory.assert_not_called()


def test_load_failure_keeps_its_cause_and_is_not_cached(model_environment) -> None:
    settings, _, factory, _ = model_environment
    factory.side_effect = RuntimeError("damaged weights")

    with pytest.raises(ModelLoadingError, match="could not be loaded") as failure:
        ModelLoader(settings).load(device="cpu")

    assert isinstance(failure.value.__cause__, RuntimeError)
    assert not ModelLoader._cache


def test_missing_native_pytorch_runtime_has_a_meaningful_error(model_environment, monkeypatch) -> None:
    settings, _, _, _ = model_environment
    monkeypatch.setattr(
        "app.services.model_loader.importlib.import_module",
        Mock(side_effect=OSError("required native library unavailable")),
    )

    with pytest.raises(ModelLoadingError, match="PyTorch could not be imported") as failure:
        ModelLoader(settings).load(device="cpu")

    assert isinstance(failure.value.__cause__, OSError)


@pytest.mark.parametrize("model_key", ["yolov8n", "yolo11m", "yolo12l", "yolo26x", "yolo26s"])
def test_loads_each_family_from_its_own_official_checkpoint(model_environment, model_key: str) -> None:
    settings, _, factory, _ = model_environment

    loaded = ModelLoader(settings).load(model_key, "cpu")

    factory.assert_called_once_with(str(settings.model_cache_dir.resolve() / f"{model_key}.pt"))
    assert loaded.model_key == model_key


def test_cache_is_keyed_by_model_so_different_models_do_not_collide(model_environment) -> None:
    settings, _, factory, _ = model_environment
    factory.side_effect = lambda path: SimpleNamespace(names={0: Path(path).stem}, to=Mock())

    first = ModelLoader(settings).load("yolov8n", "cpu")
    second = ModelLoader(settings).load("yolo11n", "cpu")

    assert first is not second
    assert first.names == {0: "yolov8n"} and second.names == {0: "yolo11n"}
    assert ModelLoader(settings).load("yolov8n", "cpu") is first
    assert factory.call_count == 2


def test_model_provided_class_metadata_is_kept_for_non_coco_class_sets(model_environment) -> None:
    settings, _, _, model = model_environment
    model.names = ["helmet", "vest", "cone"]

    assert ModelLoader(settings).load("yolo11n", "cpu").names == {0: "helmet", 1: "vest", 2: "cone"}


@pytest.mark.parametrize("task", ["segment", "pose", "classify", "obb"])
def test_rejects_a_checkpoint_whose_task_is_not_detection(model_environment, task: str) -> None:
    settings, _, _, model = model_environment
    model.task = task

    with pytest.raises(ModelLoadingError, match="only detection models"):
        ModelLoader(settings).load("yolov8n", "cpu")

    assert not ModelLoader._cache


def test_successful_load_of_cached_weights_records_verification(model_environment) -> None:
    from app.services.model_registry import CacheStatus, get_model_spec, inspect_model

    settings, _, _, model = model_environment
    model.task = "detect"
    cache = settings.model_cache_dir
    cache.mkdir(parents=True)
    (cache / "yolov8n.pt").write_bytes(b"checkpoint")
    assert inspect_model(cache, get_model_spec("yolov8n")).status == CacheStatus.CACHED_UNVERIFIED

    ModelLoader(settings).load("yolov8n", "cpu", allow_download=False)

    status = inspect_model(cache, get_model_spec("yolov8n"))
    assert status.status == CacheStatus.VERIFIED
    assert status.verified_device == "cpu"


def test_failed_load_of_corrupt_cached_weights_is_not_verified_or_deleted(model_environment) -> None:
    from app.services.model_registry import CacheStatus, get_model_spec, inspect_model

    settings, _, factory, _ = model_environment
    factory.side_effect = RuntimeError("invalid load key")
    cache = settings.model_cache_dir
    cache.mkdir(parents=True)
    (cache / "yolo12n.pt").write_bytes(b"corrupt")

    with pytest.raises(ModelLoadingError, match="yolo12n.pt could not be loaded"):
        ModelLoader(settings).load("yolo12n", "cpu", allow_download=False)

    assert (cache / "yolo12n.pt").read_bytes() == b"corrupt"
    assert inspect_model(cache, get_model_spec("yolo12n")).status == CacheStatus.CACHED_UNVERIFIED


def test_missing_weights_with_downloads_disabled_names_the_checkpoint(model_environment) -> None:
    settings, _, factory, _ = model_environment

    with pytest.raises(ModelLoadingError, match="yolo11s.pt is not cached"):
        ModelLoader(settings).load("yolo11s", "cpu", allow_download=False)

    factory.assert_not_called()


def test_registry_derived_mapping_preserves_the_phase_03_yolo26s_entry() -> None:
    assert ModelLoader.SUPPORTED_MODELS["yolo26s"] == "yolo26s.pt"
    assert len(ModelLoader.SUPPORTED_MODELS) == 20
