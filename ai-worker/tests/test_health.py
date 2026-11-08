from fastapi.testclient import TestClient

from app.main import create_app


def test_health_returns_worker_liveness_contract() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {"service": "ai-worker", "status": "UP"}


def test_undefined_detection_route_is_not_available() -> None:
    with TestClient(create_app()) as client:
        response = client.post("/detect", json={"url": "https://example.com"})

    assert response.status_code == 404
