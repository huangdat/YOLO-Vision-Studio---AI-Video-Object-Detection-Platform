from fastapi.testclient import TestClient
import subprocess
import sys

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


def test_http_startup_and_cli_help_do_not_import_optional_ai_packages() -> None:
    script = '''
import importlib.abc
import sys

class NoAi(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'torch', 'ultralytics', 'cv2', 'numpy', 'yt_dlp'}:
            raise AssertionError('Unexpected optional AI import: ' + fullname)

sys.meta_path.insert(0, NoAi())
from fastapi.testclient import TestClient
from app.main import create_app
with TestClient(create_app()) as client:
    assert client.get('/health').json() == {'service': 'ai-worker', 'status': 'UP'}
from app.cli import main
try:
    main(['--help'])
except SystemExit as result:
    assert result.code == 0
'''
    completed = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=20)
    assert completed.returncode == 0, completed.stderr
