"""Minimal durable storage for completed job artifacts (Phase 05 scope only).

Objects use deterministic, job-scoped keys, so a retried job overwrites only its own
artifacts. The result manifest is written last: its presence means the video is stored
too, which lets a redelivered command republish completion instead of re-running inference.
"""

from __future__ import annotations

from dataclasses import dataclass
import io
import json
import logging
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit
from uuid import UUID

from app.config.settings import Settings
from app.core.exceptions import ArtifactStorageError

logger = logging.getLogger(__name__)

VIDEO_CONTENT_TYPE = "video/mp4"
JSON_CONTENT_TYPE = "application/json"


@dataclass(frozen=True)
class ArtifactKeys:
    video: str
    result: str


class ArtifactStore(Protocol):
    def keys_for(self, job_id: UUID) -> ArtifactKeys: ...

    def find_completed(self, job_id: UUID) -> dict[str, Any] | None: ...

    def store(self, job_id: UUID, video: Path, manifest: dict[str, Any]) -> ArtifactKeys: ...


class MinioArtifactStore:
    """MinIO implementation. The client is created lazily, so importing costs nothing."""

    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self.settings = settings
        self.bucket = settings.minio_bucket
        self._client = client
        self._bucket_ready = False

    def keys_for(self, job_id: UUID) -> ArtifactKeys:
        prefix = f"{self.settings.minio_object_prefix}/{UUID(str(job_id))}"
        return ArtifactKeys(video=f"{prefix}/detected.mp4", result=f"{prefix}/result.json")

    def find_completed(self, job_id: UUID) -> dict[str, Any] | None:
        """Return the stored manifest when both artifacts already exist, else None."""
        keys = self.keys_for(job_id)
        client = self._get_client()
        try:
            if not self._exists(client, keys.result):
                return None
            response = client.get_object(self.bucket, keys.result)
            try:
                manifest = json.loads(response.read(1024 * 1024).decode("utf-8"))
            finally:
                response.close()
                response.release_conn()
            if not self._exists(client, keys.video):
                logger.warning("Result manifest exists without its video for job %s; reprocessing", job_id)
                return None
        except ArtifactStorageError:
            raise
        except (ValueError, UnicodeDecodeError):
            logger.warning("Ignoring an unreadable stored manifest for job %s", job_id)
            return None
        except Exception as error:
            raise ArtifactStorageError("Artifact storage could not be queried.") from error
        return manifest if isinstance(manifest, dict) else None

    def store(self, job_id: UUID, video: Path, manifest: dict[str, Any]) -> ArtifactKeys:
        keys = self.keys_for(job_id)
        video = Path(video)
        if not video.is_file() or video.stat().st_size == 0:
            raise ArtifactStorageError("The encoded video to upload is missing or empty.")
        payload = json.dumps(manifest, indent=2).encode("utf-8")
        client = self._get_client()
        try:
            self._ensure_bucket(client)
            client.fput_object(self.bucket, keys.video, str(video), content_type=VIDEO_CONTENT_TYPE)
            self._verify(client, keys.video, video.stat().st_size)
            client.put_object(self.bucket, keys.result, io.BytesIO(payload), len(payload),
                              content_type=JSON_CONTENT_TYPE)
            self._verify(client, keys.result, len(payload))
        except ArtifactStorageError:
            raise
        except Exception as error:
            raise ArtifactStorageError("Uploading job artifacts to object storage failed.") from error
        logger.info("Stored artifacts for job %s (%d video bytes)", job_id, video.stat().st_size)
        return keys

    def _verify(self, client: Any, key: str, expected_size: int) -> None:
        stat = client.stat_object(self.bucket, key)
        if int(getattr(stat, "size", -1)) != expected_size:
            raise ArtifactStorageError("A stored artifact did not match the uploaded size.")

    def _ensure_bucket(self, client: Any) -> None:
        if self._bucket_ready:
            return
        if not client.bucket_exists(self.bucket):
            # New buckets are private by default; no public policy is ever applied here.
            client.make_bucket(self.bucket, location=self.settings.minio_region)
            logger.info("Created private bucket %s", self.bucket)
        self._bucket_ready = True

    def _exists(self, client: Any, key: str) -> bool:
        """True when the object exists; a missing object or bucket is not an error."""
        try:
            client.stat_object(self.bucket, key)
            return True
        except Exception as error:
            if getattr(error, "code", None) in {"NoSuchKey", "NoSuchBucket", "NoSuchObject"}:
                return False
            raise

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                from minio import Minio
            except ImportError as error:
                raise ArtifactStorageError("MinIO support requires requirements-ai.txt to be installed.") from error
            endpoint = urlsplit(self.settings.minio_endpoint)
            if endpoint.scheme not in {"http", "https"} or not endpoint.netloc:
                raise ArtifactStorageError("MINIO_ENDPOINT must be an http(s) URL such as http://minio:9000.")
            if self.settings.minio_secret_key is None:
                raise ArtifactStorageError("MINIO_SECRET_KEY is not configured.")
            self._client = Minio(
                endpoint.netloc, access_key=self.settings.minio_access_key,
                secret_key=self.settings.minio_secret_key.get_secret_value(),
                secure=endpoint.scheme == "https", region=self.settings.minio_region,
            )
        return self._client
