from decimal import Decimal
import json
from uuid import uuid4

from pydantic import ValidationError
import pytest

from app.schemas.messaging import DetectionCommand, DetectionEvent, EventError, EventResult, WorkerJobStatus

JOB = "3f1d2a4e-8a7b-4c1d-9e2f-0123456789ab"


def command(**overrides):
    data = {
        "schemaVersion": 1, "messageId": str(uuid4()), "jobId": JOB, "modelKey": "yolo11n",
        "sourceType": "YOUTUBE_URL", "source": "https://www.youtube.com/watch?v=abcdefghijk",
        "confidence": 0.25, "imageSize": 960, "classes": [1, 2, 3, 5, 7],
        "createdAt": "2026-11-08T00:00:00.123456Z",
    }
    data.update(overrides)
    return json.dumps(data)


def test_backend_command_json_is_accepted():
    parsed = DetectionCommand.model_validate_json(command())

    assert str(parsed.job_id) == JOB
    assert parsed.model_key == "yolo11n"
    assert parsed.classes == [1, 2, 3, 5, 7]
    assert str(parsed.confidence) == "0.25"


def test_java_bigdecimal_scale_three_is_accepted():
    # Jackson serialises the persisted NUMERIC(4,3) as 0.250.
    body = command().replace('"confidence": 0.25', '"confidence": 0.250')
    assert '"confidence": 0.250' in body
    assert DetectionCommand.model_validate_json(body).confidence == Decimal("0.25")


def test_local_relative_source_is_accepted():
    assert DetectionCommand.model_validate_json(command(sourceType="LOCAL_FILE", source="clips/a.mp4")).source


@pytest.mark.parametrize("overrides", [
    {"schemaVersion": 2},
    {"schemaVersion": None},
    {"jobId": "42"},
    {"modelKey": "../yolo11n.pt"},
    {"modelKey": "YOLO11N"},
    {"sourceType": "FTP"},
    {"confidence": 1.5},
    {"confidence": -0.1},
    {"confidence": 0.2555},
    {"imageSize": 650},
    {"imageSize": 16},
    {"classes": []},
    {"classes": [2, 2]},
    {"classes": [-1]},
    {"classes": ["2"]},
    {"sourceType": "LOCAL_FILE", "source": "/etc/passwd"},
    {"sourceType": "LOCAL_FILE", "source": "clips/../../secret.mp4"},
    {"sourceType": "LOCAL_FILE", "source": "C:\\videos\\a.mp4"},
    {"weightsPath": "/tmp/evil.pt"},
])
def test_invalid_commands_are_rejected(overrides):
    with pytest.raises(ValidationError):
        DetectionCommand.model_validate_json(command(**overrides))


def test_missing_required_fields_are_rejected():
    data = json.loads(command())
    del data["modelKey"]
    with pytest.raises(ValidationError):
        DetectionCommand.model_validate_json(json.dumps(data))


def test_progress_event_serialises_to_the_backend_contract():
    event = DetectionEvent(job_id=JOB, status=WorkerJobStatus.DETECTING, progress=65, processed_frames=3250,
                           total_frames=5000, message="Processing video frames")

    payload = json.loads(event.to_json_bytes())

    assert payload["schemaVersion"] == 1
    assert payload["jobId"] == JOB and payload["status"] == "DETECTING" and payload["progress"] == 65
    assert payload["processedFrames"] == 3250 and payload["totalFrames"] == 5000
    assert payload["timestamp"].endswith("Z")
    assert "result" not in payload and "error" not in payload


def test_completion_event_requires_result_model_and_full_progress():
    result = EventResult(output_video_key="detections/x/detected.mp4", result_json_key="detections/x/result.json",
                         total_frames=36, processing_time_ms=7058, detection_summary={"bus": 36})
    event = DetectionEvent(job_id=JOB, status="COMPLETED", progress=100, model_key="yolo11n", result=result)

    payload = json.loads(event.to_json_bytes())
    assert payload["result"]["detectionSummary"] == {"bus": 36}
    assert payload["result"]["outputVideoKey"] == "detections/x/detected.mp4"

    with pytest.raises(ValidationError):
        DetectionEvent(job_id=JOB, status="COMPLETED", progress=100, model_key="yolo11n")
    with pytest.raises(ValidationError):
        DetectionEvent(job_id=JOB, status="COMPLETED", progress=99, model_key="yolo11n", result=result)


@pytest.mark.parametrize("kwargs", [
    {"status": "DETECTING", "progress": 100},
    {"status": "DETECTING", "progress": 101},
    {"status": "FAILED", "progress": 10},
    {"status": "DETECTING", "progress": 10, "error": EventError(code="X", message="y")},
    {"status": "QUEUED", "progress": 10},
])
def test_invalid_events_cannot_be_constructed(kwargs):
    with pytest.raises(ValidationError):
        DetectionEvent(job_id=JOB, **kwargs)
