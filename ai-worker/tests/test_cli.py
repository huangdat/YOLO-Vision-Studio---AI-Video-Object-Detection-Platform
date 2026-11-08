import pytest

from app import cli


def test_help_does_not_require_or_import_ai_packages(capsys):
    with pytest.raises(SystemExit) as result:
        cli.main(["--help"])
    assert result.value.code == 0
    assert "detect" in capsys.readouterr().out


@pytest.mark.parametrize("classes", ["1,nope", "-1,2", "2,2", ""])
def test_cli_rejects_invalid_class_lists(classes):
    with pytest.raises(SystemExit) as result:
        cli.main(["detect", "--source", "input.mp4", "--source-type", "local", "--classes", classes])
    assert result.value.code == 2


def test_cli_reports_invalid_configuration_without_echoing_sensitive_input(capsys):
    code = cli.main(["detect", "--source", "input.mp4", "--source-type", "local", "--confidence", "2"])
    assert code == 2
    assert "Invalid detection configuration" in capsys.readouterr().err


def _block_ai_imports(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name.split(".")[0] in {"torch", "ultralytics", "cv2", "yt_dlp"}:
            raise AssertionError(f"Unexpected AI import: {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)


def test_models_list_prints_all_twenty_approved_models_without_ai_imports(monkeypatch, capsys):
    import json

    _block_ai_imports(monkeypatch)

    assert cli.main(["models", "list", "--json"]) == 0

    rows = json.loads(capsys.readouterr().out)
    assert len(rows) == 20
    assert {"modelKey": "yolov8n", "version": "YOLOv8", "modelSize": "n", "sizeName": "Nano",
            "taskType": "DETECT", "weightsFilename": "yolov8n.pt"} in rows


def test_models_list_table_output(capsys):
    assert cli.main(["models", "list"]) == 0
    output = capsys.readouterr().out
    assert "yolo12x" in output and "Extra Large" in output


def test_models_status_reports_cache_state_without_loading_or_downloading(monkeypatch, tmp_path, capsys):
    import json

    monkeypatch.setenv("AI_MODEL_CACHE_DIR", str(tmp_path))
    (tmp_path / "yolo26s.pt").write_bytes(b"cached")
    _block_ai_imports(monkeypatch)

    assert cli.main(["models", "status", "--json"]) == 0

    rows = {row["modelKey"]: row for row in json.loads(capsys.readouterr().out)}
    assert rows["yolo26s"]["status"] == "CACHED_UNVERIFIED"
    assert rows["yolov8n"]["status"] == "NOT_CACHED"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["yolo26s.pt"]


def test_models_status_for_one_model_and_rejection_of_unknown_keys(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("AI_MODEL_CACHE_DIR", str(tmp_path))

    assert cli.main(["models", "status", "--model", "yolo11n"]) == 0
    assert "NOT_CACHED" in capsys.readouterr().out
    assert cli.main(["models", "status", "--model", "../yolo11n.pt"]) == 2
    assert "Unsupported model" in capsys.readouterr().err


from app.services.model_loader import ModelLoader as RealModelLoader  # noqa: E402


class _FakeLoader:
    calls = []

    def __init__(self, settings):
        self.settings = settings

    def load(self, model_key, device, allow_download=True):
        from types import SimpleNamespace

        from app.services.model_registry import get_model_spec

        self.calls.append((model_key, device, allow_download))
        cache = self.settings.model_cache_dir.resolve()
        cache.mkdir(parents=True, exist_ok=True)
        weights = cache / f"{model_key}.pt"
        weights.write_bytes(b"downloaded checkpoint")
        RealModelLoader._record_verification(cache, get_model_spec(model_key), weights, "cpu")
        return SimpleNamespace(model_key=model_key, device="cpu")


def test_models_prepare_downloads_loads_and_verifies_one_model(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("AI_MODEL_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr("app.services.model_loader.ModelLoader", _FakeLoader)
    _FakeLoader.calls = []

    assert cli.main(["models", "prepare", "--model", "yolov8n", "--device", "cpu"]) == 0

    captured = capsys.readouterr()
    assert _FakeLoader.calls == [("yolov8n", "cpu", True)]
    assert "Downloading official checkpoint yolov8n.pt" in captured.err
    assert "Prepared yolov8n (yolov8n.pt) on cpu: VERIFIED" in captured.out


def test_models_prepare_rejects_unknown_models_before_loading(monkeypatch, capsys):
    monkeypatch.setattr("app.services.model_loader.ModelLoader", _FakeLoader)
    _FakeLoader.calls = []

    assert cli.main(["models", "prepare", "--model", "https://example.com/x.pt"]) == 2
    assert _FakeLoader.calls == []


def test_models_prepare_reports_load_failures_with_exit_code_one(monkeypatch, tmp_path, capsys):
    from app.core.exceptions import ModelLoadingError

    class FailingLoader(_FakeLoader):
        def load(self, model_key, device, allow_download=True):
            raise ModelLoadingError("yolo11n.pt could not be loaded.")

    monkeypatch.setenv("AI_MODEL_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr("app.services.model_loader.ModelLoader", FailingLoader)

    assert cli.main(["models", "prepare", "--model", "yolo11n"]) == 1
    error = capsys.readouterr().err
    assert "Model preparation failed" in error and "could not be loaded" in error
    assert not (tmp_path / "verification").exists()


def test_legacy_prepare_model_command_still_works(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("AI_MODEL_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr("app.services.model_loader.ModelLoader", _FakeLoader)
    _FakeLoader.calls = []

    assert cli.main(["prepare-model", "--device", "cpu"]) == 0
    assert _FakeLoader.calls == [("yolo26s", "cpu", True)]


def test_detect_passes_the_selected_model_to_the_pipeline(monkeypatch, capsys):
    from types import SimpleNamespace

    requests = []

    class FakePipeline:
        def __init__(self, settings):
            pass

        def process_video(self, request, on_progress=None):
            requests.append(request)
            statistics = SimpleNamespace(model_dump_json=lambda **_: "{}")
            output = SimpleNamespace(video_path="out.mp4", metadata_path="out.json")
            return SimpleNamespace(statistics=statistics, output=output)

    monkeypatch.setattr("app.workers.detection_pipeline.DetectionPipeline", FakePipeline)

    assert cli.main(["detect", "--source", "a.mp4", "--source-type", "local", "--model", "yolov8n",
                     "--imgsz", "640", "--device", "cpu"]) == 0
    assert requests[0].model_key == "yolov8n" and requests[0].image_size == 640
