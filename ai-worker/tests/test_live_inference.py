"""Live Detection inference: the internal API contract with a fake YOLO model (no weights)."""

from __future__ import annotations

import asyncio
from pathlib import Path
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
from fastapi.testclient import TestClient
import numpy as np
import pytest

from app.config.settings import Settings
from app.core.exceptions import ModelLoadingError
from app.live_server import create_live_app
from app.services.detection_service import DetectionService
from app.services.live_inference import LiveError, LiveInferenceService, jpeg_dimensions
from app.services.model_loader import LoadedModel, ModelLoader

COCO = {index: name for index, name in enumerate(
    ["person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck"]
    + [f"class{i}" for i in range(8, 80)])}


def jpeg(width: int = 640, height: int = 480, quality: int = 80) -> bytes:
    image = np.zeros((height, width, 3), dtype=np.uint8)
    image[:, : width // 2] = (40, 120, 200)
    ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, quality])
    assert ok
    return encoded.tobytes()


class FakeModel:
    def __init__(self, boxes=((2, 0.87, (120.0, 85.0, 310.0, 260.0)),), fail=False, gate=None) -> None:
        self.boxes = boxes
        self.fail = fail
        self.gate = gate
        self.calls: list[dict] = []

    def predict(self, **kwargs):
        self.calls.append(kwargs)
        if self.gate is not None:
            self.gate.wait(5)
        if self.fail:
            raise RuntimeError("internal torch error with /secret/path")
        return [SimpleNamespace(
            boxes=SimpleNamespace(cls=[b[0] for b in self.boxes], conf=[b[1] for b in self.boxes],
                                  xyxy=[list(b[2]) for b in self.boxes]),
            speed={"inference": 42.0},
        )]


class FakeLoader:
    def __init__(self, model: FakeModel, fail: bool = False) -> None:
        self.model = model
        self.fail = fail
        self.calls: list[tuple] = []

    def load(self, model_key, allow_download=True, record_verification=True):
        self.calls.append((model_key, allow_download, record_verification))
        if self.fail:
            raise ModelLoadingError("broken checkpoint")
        return LoadedModel(self.model, model_key, "cpu", COCO)


@pytest.fixture
def cache(tmp_path: Path) -> Path:
    for name in ("yolo11n.pt", "yolo26n.pt", "yolov8n.pt"):
        (tmp_path / name).write_bytes(b"weights")
    return tmp_path


def make_service(cache: Path, model: FakeModel | None = None, loader_fail: bool = False, **overrides):
    settings = Settings(AI_MODEL_CACHE_DIR=cache, **overrides)
    loader = FakeLoader(model or FakeModel(), fail=loader_fail)
    return LiveInferenceService(settings, loader=loader, detector=DetectionService()), loader


def client_for(service: LiveInferenceService) -> TestClient:
    return TestClient(create_live_app(service=service, settings=service.settings))


def infer(client: TestClient, body: bytes, **params):
    query = {"modelKey": "yolo11n", "frameId": 42, "confidence": 0.25, "imageSize": 416, "classes": "1,2,3,5,7"}
    query.update(params)
    return client.post("/internal/live/infer", params=query, content=body,
                       headers={"Content-Type": "image/jpeg"})


# Contract ---------------------------------------------------------------------------------

def test_valid_jpeg_returns_the_documented_contract_in_frame_pixels(cache: Path) -> None:
    service, loader = make_service(cache)
    with client_for(service) as client:
        response = infer(client, jpeg())

    assert response.status_code == 200
    assert response.json() == {
        "frameId": 42, "modelKey": "yolo11n", "width": 640, "height": 480,
        "detections": [{"classId": 2, "label": "car", "confidence": 0.87, "box": [120.0, 85.0, 310.0, 260.0]}],
        "inferenceMs": 42.0,
    }
    call = loader.model.calls[0]
    assert call["conf"] == 0.25 and call["imgsz"] == 416 and call["classes"] == [1, 2, 3, 5, 7]
    assert call["save"] is False and isinstance(call["source"], np.ndarray)
    assert call["source"].shape == (480, 640, 3)
    # Prepared models are loaded without downloads and without writing to the shared cache.
    assert loader.calls == [("yolo11n", False, False)]


def test_empty_detection_results_are_an_empty_list(cache: Path) -> None:
    service, _ = make_service(cache, FakeModel(boxes=()))
    with client_for(service) as client:
        response = infer(client, jpeg())
    assert response.status_code == 200
    assert response.json()["detections"] == []


def test_boxes_are_clamped_to_the_frame(cache: Path) -> None:
    service, _ = make_service(cache, FakeModel(boxes=((0, 0.5, (-4.0, -2.0, 700.0, 500.0)),)))
    with client_for(service) as client:
        box = infer(client, jpeg()).json()["detections"][0]["box"]
    assert box == [0.0, 0.0, 640.0, 480.0]


def test_class_filter_is_passed_to_yolo_sorted(cache: Path) -> None:
    service, loader = make_service(cache)
    with client_for(service) as client:
        assert infer(client, jpeg(), classes="7,0").status_code == 200
    assert loader.model.calls[0]["classes"] == [0, 7]


def test_the_loaded_model_is_reused_across_frames(cache: Path) -> None:
    service, loader = make_service(cache)
    with client_for(service) as client:
        for frame_id in range(3):
            assert infer(client, jpeg(), frameId=frame_id).status_code == 200
    assert len(loader.calls) == 1
    assert len(loader.model.calls) == 3


def test_loaded_models_are_bounded_and_least_recently_used_is_evicted(cache: Path, monkeypatch) -> None:
    evicted: list[set[str]] = []
    monkeypatch.setattr(ModelLoader, "evict", classmethod(lambda cls, keep: evicted.append(set(keep)) or []))
    service, _ = make_service(cache)
    service.load_model("yolo11n")
    service.load_model("yolo26n")
    assert service.loaded_model_keys() == ["yolo26n"]
    assert evicted[-1] == {"yolo26n"}


def test_loading_warms_up_once_per_model_and_size(cache: Path) -> None:
    service, loader = make_service(cache)
    with client_for(service) as client:
        assert client.post("/internal/live/models/yolo11n/load", params={"imageSize": 320}).status_code == 200
        assert client.post("/internal/live/models/yolo11n/load", params={"imageSize": 320}).status_code == 200
        assert client.post("/internal/live/models/yolo11n/load", params={"imageSize": 416}).status_code == 200
        bad = client.post("/internal/live/models/yolo11n/load", params={"imageSize": 500})
    sizes = [call["imgsz"] for call in loader.model.calls]
    assert sizes == [320, 416]
    assert all(call["source"].shape == (call["imgsz"], call["imgsz"], 3) for call in loader.model.calls)
    assert len(loader.calls) == 1
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "INVALID_PARAMETERS"


def test_load_endpoint_reports_the_device(cache: Path) -> None:
    service, _ = make_service(cache)
    with client_for(service) as client:
        response = client.post("/internal/live/models/yolo11n/load")
    assert response.status_code == 200
    assert response.json() == {"modelKey": "yolo11n", "device": "cpu", "classes": 80}


# Rejections -------------------------------------------------------------------------------

@pytest.mark.parametrize("body", [b"not a jpeg", b"\xff\xd8\xff\xe0garbage", b"\x89PNG\r\n\x1a\n"])
def test_malformed_images_are_rejected(cache: Path, body: bytes) -> None:
    service, loader = make_service(cache)
    with client_for(service) as client:
        response = infer(client, body)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_FRAME"
    assert loader.model.calls == []


def test_truncated_jpeg_with_a_valid_header_fails_decoding(cache: Path) -> None:
    service, _ = make_service(cache)
    data = jpeg()
    with client_for(service) as client:
        response = infer(client, data[:400])
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_FRAME"


def test_non_jpeg_content_type_is_rejected(cache: Path) -> None:
    service, _ = make_service(cache)
    with client_for(service) as client:
        response = client.post("/internal/live/infer", params={"modelKey": "yolo11n", "frameId": 1},
                               content=jpeg(), headers={"Content-Type": "application/octet-stream"})
    assert response.json()["error"]["code"] == "INVALID_FRAME"


def test_oversized_payload_is_rejected_before_decoding(cache: Path) -> None:
    service, loader = make_service(cache, LIVE_MAX_FRAME_BYTES=2048)
    with client_for(service) as client:
        response = infer(client, jpeg(quality=95))
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "FRAME_TOO_LARGE"
    assert loader.calls == []


def test_declared_dimensions_are_checked_before_allocating(cache: Path) -> None:
    service, loader = make_service(cache)
    with client_for(service) as client:
        response = infer(client, jpeg(width=1920, height=1080, quality=30))
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "FRAME_TOO_LARGE"
    assert loader.model.calls == []


def test_jpeg_header_parser_reads_dimensions() -> None:
    assert jpeg_dimensions(jpeg(320, 240)) == (320, 240)
    with pytest.raises(LiveError):
        jpeg_dimensions(b"\xff\xd8\xff\xda\x00\x02")


@pytest.mark.parametrize("model_key", ["yolo99z", "yolo11s", "yolo11n-seg", "../etc/passwd", "YOLO11N"])
def test_unsupported_models_are_rejected(cache: Path, model_key: str) -> None:
    service, loader = make_service(cache)
    with client_for(service) as client:
        response = infer(client, jpeg(), modelKey=model_key)
        load = client.post(f"/internal/live/models/{model_key}/load")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "MODEL_NOT_SUPPORTED"
    assert load.status_code in (404, 405)
    assert loader.calls == []


def test_missing_checkpoint_is_not_prepared(cache: Path) -> None:
    (cache / "yolo11n.pt").unlink()
    service, loader = make_service(cache)
    with client_for(service) as client:
        response = infer(client, jpeg())
    assert response.status_code == 409
    body = response.json()["error"]
    assert body["code"] == "MODEL_NOT_PREPARED" and "models prepare --model yolo11n" in body["message"]
    assert loader.calls == []


def test_unloadable_checkpoint_is_a_controlled_failure(cache: Path) -> None:
    service, _ = make_service(cache, loader_fail=True)
    with client_for(service) as client:
        response = infer(client, jpeg())
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "MODEL_LOAD_FAILED"


def test_live_sizes_follow_configuration(cache: Path) -> None:
    (cache / "yolo11s.pt").write_bytes(b"weights")
    service, _ = make_service(cache, LIVE_MODEL_SIZES="n,s")
    with client_for(service) as client:
        assert infer(client, jpeg(), modelKey="yolo11s").status_code == 200


@pytest.mark.parametrize("params", [
    {"confidence": 1.5}, {"imageSize": 400}, {"imageSize": 1280}, {"classes": "1,1"},
    {"classes": "80"}, {"classes": "a,b"}, {"classes": ""}, {"frameId": -1}, {"frameId": 2**32},
])
def test_invalid_parameters_are_rejected_without_echoing_input(cache: Path, params: dict) -> None:
    service, loader = make_service(cache)
    with client_for(service) as client:
        response = infer(client, jpeg(), **params)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_PARAMETERS"
    assert loader.model.calls == []


def test_missing_parameters_are_reported_by_name_only(cache: Path) -> None:
    service, _ = make_service(cache)
    with client_for(service) as client:
        response = client.post("/internal/live/infer", content=jpeg(), headers={"Content-Type": "image/jpeg"})
    assert response.status_code == 400
    assert response.json()["error"] == {"code": "INVALID_PARAMETERS",
                                        "message": "Invalid or missing parameters: frameId, modelKey."}


def test_inference_failures_are_reported_without_internal_details(cache: Path) -> None:
    service, _ = make_service(cache, FakeModel(fail=True))
    with client_for(service) as client:
        response = infer(client, jpeg())
    assert response.status_code == 500
    assert response.json()["error"] == {"code": "INFERENCE_FAILED", "message": "YOLO inference failed on the frame."}


def test_a_busy_worker_answers_429_instead_of_queueing(cache: Path) -> None:
    gate = threading.Event()
    service, loader = make_service(cache, FakeModel(gate=gate))
    app = create_live_app(service=service, settings=service.settings)

    async def scenario():
        import httpx2 as httpx

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://live") as client:
            params = {"modelKey": "yolo11n", "frameId": 1}
            headers = {"Content-Type": "image/jpeg"}
            first = asyncio.create_task(client.post("/internal/live/infer", params=params, content=jpeg(),
                                                    headers=headers))
            for _ in range(200):
                if loader.model.calls:
                    break
                await asyncio.sleep(0.01)
            second = await client.post("/internal/live/infer", params={**params, "frameId": 2}, content=jpeg(),
                                       headers=headers)
            gate.set()
            return await first, second

    first, second = asyncio.run(scenario())
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "WORKER_BUSY"
    assert first.status_code == 200
    assert len(loader.model.calls) == 1


def test_frames_are_never_written_to_disk(cache: Path, tmp_path_factory) -> None:
    before = {path.name for path in cache.iterdir()}
    service, _ = make_service(cache)
    with client_for(service) as client:
        infer(client, jpeg())
    assert {path.name for path in cache.iterdir()} == before


def test_the_health_route_is_served_and_docs_are_disabled(cache: Path) -> None:
    service, _ = make_service(cache)
    with client_for(service) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404


def test_the_regular_worker_http_service_has_no_live_routes() -> None:
    from app.main import create_app

    with TestClient(create_app()) as client:
        assert client.post("/internal/live/infer").status_code == 404


def test_detect_image_does_not_render_annotations() -> None:
    model = Mock()
    model.predict.return_value = [SimpleNamespace(
        boxes=SimpleNamespace(cls=[0], conf=[0.9], xyxy=[[1, 2, 3, 4]]), speed={"inference": 5.0},
        plot=Mock(side_effect=AssertionError("live frames must not be annotated")))]
    frame = DetectionService().detect_image("image", LoadedModel(model, "yolo11n", "cpu", COCO), 0.3, 320, [0])
    assert frame.image is None and frame.boxes[0].label == "person" and frame.inference_time_ms == 5.0


def test_live_server_runs_without_a_per_frame_access_log(monkeypatch: pytest.MonkeyPatch, cache: Path) -> None:
    import logging

    import app.live_server as live_server

    run = Mock()
    monkeypatch.setattr(live_server.uvicorn, "run", run)
    live_server.main()
    assert run.call_args.kwargs["access_log"] is False

    access = logging.getLogger("uvicorn.access")
    monkeypatch.setattr(access, "disabled", False)
    service, _ = make_service(cache)
    with client_for(service):
        # The lifespan reconfigures logging; the access logger must stay off afterwards.
        assert access.disabled is True
