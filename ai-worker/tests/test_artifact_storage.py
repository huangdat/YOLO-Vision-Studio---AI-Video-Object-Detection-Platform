import io
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.config.settings import Settings
from app.core.exceptions import ArtifactStorageError
from app.services.artifact_storage import MinioArtifactStore

JOB = UUID("3f1d2a4e-8a7b-4c1d-9e2f-0123456789ab")


class MissingObject(Exception):
    code = "NoSuchKey"


class FakeMinio:
    def __init__(self, bucket_exists=True):
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.buckets = {"videos"} if bucket_exists else set()
        self.fail_upload = False
        self.truncate = False

    def bucket_exists(self, bucket):
        return bucket in self.buckets

    def make_bucket(self, bucket, location=None):
        self.buckets.add(bucket)

    def fput_object(self, bucket, key, path, content_type):
        if self.fail_upload:
            raise ConnectionError("minio unavailable")
        data = Path(path).read_bytes()
        self.objects[key] = (data[:-1] if self.truncate else data, content_type)

    def put_object(self, bucket, key, stream, length, content_type):
        self.objects[key] = (stream.read(length), content_type)

    def stat_object(self, bucket, key):
        if key not in self.objects:
            raise MissingObject()
        return SimpleNamespace(size=len(self.objects[key][0]))

    def get_object(self, bucket, key):
        response = io.BytesIO(self.objects[key][0])
        response.release_conn = lambda: None
        return response


@pytest.fixture
def video(tmp_path):
    path = tmp_path / "detected.mp4"
    path.write_bytes(b"\x00\x00\x00 ftypisom video bytes")
    return path


def store(client):
    return MinioArtifactStore(Settings(MINIO_SECRET_KEY="test-only"), client=client)


def test_keys_are_deterministic_and_job_scoped():
    keys = store(FakeMinio()).keys_for(JOB)

    assert keys.video == f"detections/{JOB}/detected.mp4"
    assert keys.result == f"detections/{JOB}/result.json"


def test_store_uploads_video_then_manifest_with_content_types(video):
    client = FakeMinio()

    keys = store(client).store(JOB, video, {"modelKey": "yolo11n"})

    assert client.objects[keys.video] == (video.read_bytes(), "video/mp4")
    stored, content_type = client.objects[keys.result]
    assert content_type == "application/json" and json.loads(stored) == {"modelKey": "yolo11n"}


def test_missing_bucket_is_created_privately(video):
    client = FakeMinio(bucket_exists=False)

    store(client).store(JOB, video, {})

    assert "videos" in client.buckets


def test_upload_failure_is_a_storage_error_and_writes_no_manifest(video):
    client = FakeMinio()
    client.fail_upload = True

    with pytest.raises(ArtifactStorageError):
        store(client).store(JOB, video, {})
    assert not any(key.endswith("result.json") for key in client.objects)


def test_size_mismatch_after_upload_is_detected(video):
    client = FakeMinio()
    client.truncate = True

    with pytest.raises(ArtifactStorageError, match="did not match"):
        store(client).store(JOB, video, {})


def test_empty_video_is_refused(tmp_path):
    empty = tmp_path / "empty.mp4"
    empty.write_bytes(b"")

    with pytest.raises(ArtifactStorageError):
        store(FakeMinio()).store(JOB, empty, {})


def test_find_completed_returns_the_manifest_only_when_both_objects_exist(video):
    client = FakeMinio()
    artifacts = store(client)
    assert artifacts.find_completed(JOB) is None

    artifacts.store(JOB, video, {"modelKey": "yolo11n"})
    assert artifacts.find_completed(JOB) == {"modelKey": "yolo11n"}

    del client.objects[artifacts.keys_for(JOB).video]
    assert artifacts.find_completed(JOB) is None


def test_missing_credentials_are_reported_without_contacting_minio():
    with pytest.raises(ArtifactStorageError, match="MINIO_SECRET_KEY"):
        MinioArtifactStore(Settings()).find_completed(JOB)
