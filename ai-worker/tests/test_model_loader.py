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


@pytest.mark.parametrize("identifier", ["../other.pt", "https://example.com/model.pt", "yolo11s", "yolo26s.pt"])
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
