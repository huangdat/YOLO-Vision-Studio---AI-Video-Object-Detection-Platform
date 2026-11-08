from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.core.exceptions import InferenceError
from app.services.detection_service import DetectionService
from app.services.model_loader import LoadedModel


def result(classes=(2,), confidences=(0.85,), coordinates=((1, 2, 10, 20),)):
    return SimpleNamespace(
        boxes=SimpleNamespace(cls=list(classes), conf=list(confidences), xyxy=list(coordinates)),
        speed={"inference": 3.5}, plot=Mock(return_value="annotated-frame"),
    )


def loaded_model(results):
    capture = SimpleNamespace(release=Mock())
    model = SimpleNamespace(
        predict=Mock(return_value=iter(results)),
        predictor=SimpleNamespace(dataset=SimpleNamespace(cap=capture)),
    )
    return LoadedModel(model, "yolo26s", "cpu", {0: "person", 2: "car", 5: "bus"}), capture


def test_streams_the_configured_classes_confidence_image_size_and_actual_device() -> None:
    raw = result()
    model, capture = loaded_model([raw])

    frames = list(DetectionService().iter_frames(Path("sample.mp4"), model, 0.4, 640, [2, 5]))

    model.model.predict.assert_called_once_with(
        source="sample.mp4", conf=0.4, imgsz=640, classes=[2, 5], device="cpu",
        stream=True, save=False, verbose=False,
    )
    assert frames[0].image == "annotated-frame"
    assert frames[0].boxes[0].label == "car"
    assert frames[0].boxes[0].confidence == pytest.approx(0.85)
    assert frames[0].boxes[0].xyxy == (1, 2, 10, 20)
    assert frames[0].inference_time_ms == 3.5
    raw.plot.assert_called_once_with(labels=True, conf=True)
    capture.release.assert_called_once()


def test_zero_detection_frames_are_still_plotted_and_yielded() -> None:
    raw = result((), (), ())
    model, _ = loaded_model([raw])

    frames = list(DetectionService().iter_frames(Path("sample.mp4"), model, 0.25, 960, [2]))

    assert len(frames) == 1
    assert frames[0].boxes == []
    raw.plot.assert_called_once()


def test_supports_multiple_classes_including_non_vehicle_classes() -> None:
    raw = result((0, 2, 5), (0.9, 0.8, 0.7), ((0, 0, 4, 4),) * 3)
    model, _ = loaded_model([raw])

    frames = list(DetectionService().iter_frames(Path("sample.mp4"), model, 0.25, 960, [0, 2, 5]))

    assert [box.label for box in frames[0].boxes] == ["person", "car", "bus"]


@pytest.mark.parametrize("classes", [[80], [-1], [], [True]])
def test_rejects_class_identifiers_not_supported_by_the_loaded_model(classes: list[int]) -> None:
    model, _ = loaded_model([])

    with pytest.raises(InferenceError, match="class identifiers"):
        list(DetectionService().iter_frames(Path("sample.mp4"), model, 0.25, 960, classes))

    model.model.predict.assert_not_called()


def test_inference_failure_releases_video_resources_and_preserves_context() -> None:
    model, capture = loaded_model([])
    model.model.predict.side_effect = RuntimeError("inference failed")

    with pytest.raises(InferenceError, match="YOLO inference") as failure:
        list(DetectionService().iter_frames(Path("sample.mp4"), model, 0.25, 960, [2]))

    assert isinstance(failure.value.__cause__, RuntimeError)
    capture.release.assert_called_once()


def test_closing_a_partially_consumed_stream_closes_the_source_generator() -> None:
    model, capture = loaded_model([])
    closed = []

    def stream():
        try:
            yield result()
            yield result()
        finally:
            closed.append(True)

    model.model.predict.return_value = stream()
    frames = DetectionService().iter_frames(Path("sample.mp4"), model, 0.25, 960, [2])
    next(frames)
    frames.close()

    assert closed == [True]
    capture.release.assert_called_once()


def test_invalid_box_data_is_reported_as_inference_failure() -> None:
    model, capture = loaded_model([result((2,), (), ())])

    with pytest.raises(InferenceError, match="inconsistent bounding box"):
        list(DetectionService().iter_frames(Path("sample.mp4"), model, 0.25, 960, [2]))

    capture.release.assert_called_once()
