"""Live Detection tracking: per-session ByteTrack state behind the internal live API."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.live_inference import LiveError, LiveTrackingSessions
from tests.test_live_inference import FakeModel, cache, client_for, infer, jpeg, make_service  # noqa: F401

SESSION_A = "0f8f3c52-6b1e-4a43-9a51-1b2c3d4e5f60"
SESSION_B = "7a1d9e04-2c3b-4d5e-8f60-718293a4b5c6"
BOXES = ((2, 0.87, (120.0, 85.0, 310.0, 260.0)), (0, 0.66, (400.0, 100.0, 460.0, 300.0)))


def track(client, frame_id: int, session: str = SESSION_A, **params):
    return infer(client, jpeg(), frameId=frame_id, tracking="true", sessionId=session, classes="0,2", **params)


def test_detection_only_responses_are_unchanged(cache: Path) -> None:
    service, _ = make_service(cache, FakeModel(boxes=BOXES))
    with client_for(service) as client:
        body = infer(client, jpeg(), classes="0,2").json()

    assert "tracking" not in body and "activeTracks" not in body
    assert all("trackId" not in detection for detection in body["detections"])
    assert service.tracking.active() == 0


def test_tracking_returns_persistent_ids_for_one_session(cache: Path) -> None:
    service, loader = make_service(cache, FakeModel(boxes=BOXES))
    with client_for(service) as client:
        bodies = [track(client, frame_id).json() for frame_id in (1, 2, 3)]
        assert service.tracking.active() == 1

    assert [[d["trackId"] for d in body["detections"]] for body in bodies] == [[1, 2], [1, 2], [1, 2]]
    assert all(body["tracking"] is True and body["activeTracks"] == 2 for body in bodies)
    assert bodies[0]["detections"][0] == {"classId": 2, "label": "car", "confidence": 0.87,
                                          "box": [120.0, 85.0, 310.0, 260.0], "trackId": 1}
    # ByteTrack needs low-score boxes: YOLO runs at min(confidence, 0.1) in tracking mode.
    assert loader.model.calls[0]["conf"] == pytest.approx(0.1)


def test_sessions_are_isolated(cache: Path) -> None:
    service, _ = make_service(cache, FakeModel(boxes=BOXES))
    with client_for(service) as client:
        for frame_id in (1, 2, 3):
            track(client, frame_id, SESSION_A)
        other = track(client, 1, SESSION_B).json()
        assert service.tracking.active() == 2

    # A second session starts its own tracker: its IDs start again at 1, unaffected by session A.
    assert [d["trackId"] for d in other["detections"]] == [1, 2]


def test_tracking_requires_a_valid_session_id(cache: Path) -> None:
    service, _ = make_service(cache)
    with client_for(service) as client:
        missing = infer(client, jpeg(), tracking="true")
        invalid = infer(client, jpeg(), tracking="true", sessionId="bad id!")

    assert missing.status_code == invalid.status_code == 400
    assert missing.json()["error"]["code"] == "INVALID_PARAMETERS"
    assert service.tracking.active() == 0


def test_old_or_repeated_frames_are_rejected_in_order(cache: Path) -> None:
    service, _ = make_service(cache, FakeModel(boxes=BOXES))
    with client_for(service) as client:
        assert track(client, 5).status_code == 200
        repeated = track(client, 5)
        older = track(client, 4)
        newer = track(client, 9)

    assert repeated.status_code == older.status_code == 409
    assert older.json()["error"]["code"] == "FRAME_OUT_OF_ORDER"
    assert newer.status_code == 200


def test_ending_a_session_releases_state_and_is_idempotent(cache: Path) -> None:
    service, _ = make_service(cache, FakeModel(boxes=BOXES))
    with client_for(service) as client:
        track(client, 1)
        session = service.tracking._sessions[SESSION_A]
        first = client.delete(f"/internal/live/sessions/{SESSION_A}")
        second = client.delete(f"/internal/live/sessions/{SESSION_A}")
        late = track(client, 2)

    assert first.status_code == second.status_code == 204
    assert session.tracker.closed and service.tracking.active() == 0
    # A late frame of an ended session never revives the old Track IDs.
    assert late.status_code == 409 and late.json()["error"]["code"] == "SESSION_ENDED"


def test_ending_an_unknown_or_malformed_session_is_harmless(cache: Path) -> None:
    service, _ = make_service(cache)
    with client_for(service) as client:
        assert client.delete("/internal/live/sessions/unknown-session").status_code == 204
        assert client.delete("/internal/live/sessions/x").status_code == 204


def test_changed_settings_start_a_fresh_tracker(cache: Path) -> None:
    service, _ = make_service(cache, FakeModel(boxes=BOXES))
    with client_for(service) as client:
        track(client, 1)
        old = service.tracking._sessions[SESSION_A]
        track(client, 2, confidence=0.5)
        assert old.tracker.closed and service.tracking._sessions[SESSION_A] is not old


def _settings(service, session_id: str):
    return service.validate("yolo11n", 1, 0.25, 416, [2], True, session_id)


def test_idle_sessions_expire_and_capacity_is_bounded(cache: Path) -> None:
    service, _ = make_service(cache)
    now = [0.0]
    sessions = LiveTrackingSessions(max_sessions=2, ttl_seconds=30, track_buffer=10, clock=lambda: now[0])
    first = sessions.acquire(_settings(service, SESSION_A))
    sessions.acquire(_settings(service, SESSION_B))

    with pytest.raises(LiveError) as full:
        sessions.acquire(_settings(service, "c3c3c3c3-0000-4000-8000-000000000003"))
    assert full.value.code == "TRACKING_CAPACITY" and full.value.status == 429

    now[0] = 31.0
    sessions.acquire(_settings(service, "c3c3c3c3-0000-4000-8000-000000000003"))
    assert sessions.active() == 1 and first.tracker.closed
    with pytest.raises(LiveError) as expired:
        sessions.acquire(_settings(service, SESSION_A))
    assert expired.value.code == "SESSION_ENDED"


def test_shutdown_closes_every_tracker(cache: Path) -> None:
    service, _ = make_service(cache, FakeModel(boxes=BOXES))
    with client_for(service) as client:
        track(client, 1, SESSION_A)
        track(client, 1, SESSION_B)
        trackers = [session.tracker for session in service.tracking._sessions.values()]

    assert service.tracking.active() == 0 and all(tracker.closed for tracker in trackers)


def test_a_busy_worker_still_accepts_session_cleanup(cache: Path) -> None:
    service, _ = make_service(cache, FakeModel(boxes=BOXES))
    with client_for(service) as client:
        track(client, 1)
        session = service.tracking._sessions[SESSION_A]
        with session.lock:  # the session is "processing" a frame
            pass
        assert client.delete(f"/internal/live/sessions/{SESSION_A}").status_code == 204
    assert session.tracker.closed


# --- Tracker input for frontend (browser) ByteTrack ----------------------------------------------

LOW = ((2, 0.87, (120.0, 85.0, 310.0, 260.0)), (0, 0.15, (400.0, 100.0, 460.0, 300.0)))


def test_tracking_input_returns_every_box_from_the_low_score_floor_without_track_ids(cache: Path) -> None:
    service, loader = make_service(cache, FakeModel(boxes=LOW))
    with client_for(service) as client:
        body = infer(client, jpeg(), classes="0,2", trackingInput="true", confidence="0.4").json()

    # YOLO runs at ByteTrack's low-score floor, and the 0.15 box below the 0.4 threshold is kept for
    # the browser's second association stage.
    assert loader.model.calls[0]["conf"] == pytest.approx(0.1)
    assert [d["confidence"] for d in body["detections"]] == [0.87, 0.15]
    assert all("trackId" not in d for d in body["detections"])
    assert body["trackingInput"] is True and body["lowScoreFloor"] == pytest.approx(0.1)
    assert "tracking" not in body and "activeTracks" not in body
    assert body["device"] == "cpu" and body["precision"] == "FP32"
    assert service.tracking.active() == 0  # no server-side tracking state


def test_tracking_input_is_stateless_and_needs_no_session(cache: Path) -> None:
    service, _ = make_service(cache, FakeModel(boxes=LOW))
    with client_for(service) as client:
        later = infer(client, jpeg(), frameId=9, trackingInput="true")
        earlier = infer(client, jpeg(), frameId=3, trackingInput="true")  # ordering is the browser's job

    assert later.status_code == earlier.status_code == 200
    assert service.tracking.active() == 0


def test_tracking_input_cannot_be_combined_with_server_tracking(cache: Path) -> None:
    service, _ = make_service(cache, FakeModel(boxes=LOW))
    with client_for(service) as client:
        response = track(client, 1, trackingInput="true")

    assert response.status_code == 400
    assert "cannot be combined" in response.json()["error"]["message"]
