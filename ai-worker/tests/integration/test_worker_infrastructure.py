"""Worker against a real RabbitMQ and MinIO (opt-in).

Run with disposable services, for example:
    IT_RABBITMQ_HOST=127.0.0.1 IT_RABBITMQ_PORT=25672 IT_RABBITMQ_PASSWORD=... \
    IT_MINIO_ENDPOINT=http://127.0.0.1:29000 IT_MINIO_PASSWORD=... \
    python -m pytest -q tests/integration

Only the YOLO pipeline is replaced by a fake; pika, the consumer loop, acknowledgements,
quorum-queue redelivery counting, dead-lettering, and MinIO uploads are all real.
Every run uses its own queue names and bucket and removes them afterwards.
"""

from __future__ import annotations

import json
import os
import threading
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest

pytestmark = pytest.mark.skipif(
    not (os.environ.get("IT_RABBITMQ_PASSWORD") and os.environ.get("IT_MINIO_PASSWORD")),
    reason="Set IT_RABBITMQ_* and IT_MINIO_* to run broker/storage integration tests",
)

from app.config.settings import Settings  # noqa: E402
from app.core.exceptions import ArtifactStorageError  # noqa: E402
from app.schemas.progress import ProgressEvent, ProgressStage  # noqa: E402
from app.services.artifact_storage import MinioArtifactStore  # noqa: E402
from app.workers.job_processor import DetectionJobProcessor  # noqa: E402
from app.workers.rabbitmq_worker import RabbitMQWorker  # noqa: E402


class SlowFakePipeline:
    calls = 0

    def __init__(self, settings, seconds=0.0):
        self.settings = settings
        self.seconds = seconds

    def process_video(self, request, on_progress=None):
        type(self).calls += 1
        deadline = time.monotonic() + self.seconds
        step = 15
        while True:
            on_progress(ProgressEvent(stage=ProgressStage.DETECTING, progress=min(step, 84),
                                      processed_frames=step, total_frames=100))
            step += 10
            if time.monotonic() >= deadline:
                break
            time.sleep(0.5)
        on_progress(ProgressEvent(stage=ProgressStage.ENCODING, progress=90))
        out = self.settings.output_dir / "exec"
        out.mkdir(parents=True)
        video = out / "detected.mp4"
        video.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"\x00" * 2048)
        return SimpleNamespace(
            model_key=request.model_key, output=SimpleNamespace(video_path=video),
            statistics=SimpleNamespace(total_frames_processed=36),
            model_dump_json=lambda by_alias: json.dumps({
                "modelKey": request.model_key, "processingTimeMs": 1234,
                "statistics": {"totalFramesProcessed": 36, "detectionsByClass": {"bus": 36}},
            }),
        )


class FailingStore(MinioArtifactStore):
    def store(self, job_id, video, manifest):
        raise ArtifactStorageError("simulated outage")


@pytest.fixture
def infra(tmp_path):
    import pika
    from minio import Minio

    run = uuid4().hex[:10]
    settings = Settings(
        RABBITMQ_HOST=os.environ.get("IT_RABBITMQ_HOST", "127.0.0.1"),
        RABBITMQ_PORT=int(os.environ.get("IT_RABBITMQ_PORT", "5672")),
        RABBITMQ_USERNAME=os.environ.get("IT_RABBITMQ_USERNAME", "yolovision"),
        RABBITMQ_PASSWORD=os.environ["IT_RABBITMQ_PASSWORD"],
        RABBITMQ_HEARTBEAT_SECONDS=10,
        RABBITMQ_COMMAND_EXCHANGE=f"it.{run}.commands", RABBITMQ_COMMAND_QUEUE=f"it.{run}.jobs",
        RABBITMQ_EVENT_EXCHANGE=f"it.{run}.events", RABBITMQ_EVENT_QUEUE=f"it.{run}.events.backend",
        RABBITMQ_DEAD_LETTER_EXCHANGE=f"it.{run}.dlx", RABBITMQ_DEAD_LETTER_QUEUE=f"it.{run}.dead-letter",
        RABBITMQ_DELIVERY_LIMIT=5, JOB_MAX_RETRIES=2, WORKER_RETRY_BACKOFF_SECONDS=0,
        WORKER_PROGRESS_INTERVAL_SECONDS=1, WORKER_HEARTBEAT_SECONDS=2,
        MINIO_ENDPOINT=os.environ.get("IT_MINIO_ENDPOINT", "http://127.0.0.1:9000"),
        MINIO_ACCESS_KEY=os.environ.get("IT_MINIO_USERNAME", "yolovision"),
        MINIO_SECRET_KEY=os.environ["IT_MINIO_PASSWORD"], MINIO_BUCKET=f"it-{run}",
        AI_MODEL_CACHE_DIR=tmp_path / "models", AI_TEMP_DIR=tmp_path / "temp",
        AI_LOCAL_INPUT_DIR=tmp_path / "inputs",
    )
    settings.model_cache_dir.mkdir(parents=True)
    (settings.model_cache_dir / "yolo11n.pt").write_bytes(b"prepared")
    parameters = pika.ConnectionParameters(
        host=settings.rabbitmq_host, port=settings.rabbitmq_port,
        credentials=pika.PlainCredentials(settings.rabbitmq_username, settings.rabbitmq_password.get_secret_value()))
    minio = Minio(settings.minio_endpoint.split("://")[1], access_key=settings.minio_access_key,
                  secret_key=settings.minio_secret_key.get_secret_value(), secure=False)
    workers: list[tuple[RabbitMQWorker, threading.Thread]] = []
    SlowFakePipeline.calls = 0

    def start(store_class=MinioArtifactStore, seconds=0.0):
        processor = DetectionJobProcessor(
            settings, store_class(settings),
            pipeline_factory=lambda job_settings: SlowFakePipeline(job_settings, seconds),
            model_preloader=lambda *_: None,
        )
        worker = RabbitMQWorker(settings, processor)
        reconnects = []
        original = worker._connect
        worker._connect = lambda: reconnects.append(1) or original()
        thread = threading.Thread(target=worker.run, daemon=True)
        thread.start()
        workers.append((worker, thread))
        worker.connections = reconnects
        wait_for(lambda: queue_exists(parameters, settings.command_queue), 20)
        return worker

    yield SimpleNamespace(settings=settings, parameters=parameters, minio=minio, start=start)

    for worker, thread in workers:
        worker.request_stop()
        thread.join(timeout=30)
    connection = pika.BlockingConnection(parameters)
    channel = connection.channel()
    for queue in (settings.command_queue, settings.event_queue, settings.dead_letter_queue):
        channel.queue_delete(queue=queue)
    for exchange in (settings.command_exchange, settings.event_exchange, settings.dead_letter_exchange):
        channel.exchange_delete(exchange=exchange)
    connection.close()
    if minio.bucket_exists(settings.minio_bucket):
        for item in minio.list_objects(settings.minio_bucket, recursive=True):
            minio.remove_object(settings.minio_bucket, item.object_name)
        minio.remove_bucket(settings.minio_bucket)


def wait_for(condition, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.2)
    raise AssertionError("condition not met in time")


def queue_exists(parameters, queue):
    import pika

    try:
        connection = pika.BlockingConnection(parameters)
        try:
            connection.channel().queue_declare(queue=queue, passive=True)
            return True
        finally:
            if connection.is_open:
                connection.close()
    except Exception:
        return False


def publish_command(infra, job_id, **overrides):
    import pika

    body = {
        "schemaVersion": 1, "messageId": str(uuid4()), "jobId": str(job_id), "modelKey": "yolo11n",
        "sourceType": "LOCAL_FILE", "source": "clip.mp4", "confidence": 0.25, "imageSize": 320,
        "classes": [2, 5], "createdAt": "2026-11-08T00:00:00Z",
    }
    body.update(overrides)
    connection = pika.BlockingConnection(infra.parameters)
    channel = connection.channel()
    channel.confirm_delivery()
    payload = body if isinstance(body, (bytes, str)) else json.dumps(body)
    channel.basic_publish(infra.settings.command_exchange, infra.settings.command_routing_key, payload,
                          pika.BasicProperties(delivery_mode=2, content_type="application/json"), mandatory=True)
    connection.close()


def publish_raw(infra, raw: bytes):
    import pika

    connection = pika.BlockingConnection(infra.parameters)
    channel = connection.channel()
    channel.confirm_delivery()
    channel.basic_publish(infra.settings.command_exchange, infra.settings.command_routing_key, raw,
                          pika.BasicProperties(delivery_mode=2), mandatory=True)
    connection.close()


def drain(infra, queue, until, timeout=60):
    """Collect messages from a queue until ``until(messages)`` is true."""
    import pika

    messages = []
    connection = pika.BlockingConnection(infra.parameters)
    channel = connection.channel()
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            method, properties, body = channel.basic_get(queue=queue, auto_ack=True)
            if method is None:
                if until(messages):
                    return messages
                time.sleep(0.2)
                continue
            messages.append((properties, body))
            if until(messages):
                return messages
        raise AssertionError(f"Timed out; received {len(messages)} message(s) from {queue}")
    finally:
        connection.close()


def events_for(messages, job_id):
    return [json.loads(body) for _, body in messages if json.loads(body).get("jobId") == str(job_id)]


def message_count(infra, queue):
    import pika

    connection = pika.BlockingConnection(infra.parameters)
    try:
        return connection.channel().queue_declare(queue=queue, passive=True).method.message_count
    finally:
        connection.close()


def test_job_is_processed_stored_completed_and_acknowledged(infra):
    infra.start()
    job = uuid4()

    publish_command(infra, job)
    messages = drain(infra, infra.settings.event_queue,
                     lambda m: any(e["status"] == "COMPLETED" for e in events_for(m, job)))

    events = events_for(messages, job)
    statuses = [event["status"] for event in events]
    assert statuses[-1] == "COMPLETED" and "DETECTING" in statuses and "UPLOADING" in statuses
    progress = [event["progress"] for event in events]
    assert progress == sorted(progress) and progress[-1] == 100
    properties = messages[-1][0]
    assert properties.delivery_mode == 2 and properties.content_type == "application/json"
    completion = events[-1]
    assert completion["modelKey"] == "yolo11n"
    assert completion["result"]["outputVideoKey"] == f"detections/{job}/detected.mp4"
    video = infra.minio.stat_object(infra.settings.minio_bucket, f"detections/{job}/detected.mp4")
    manifest = infra.minio.stat_object(infra.settings.minio_bucket, f"detections/{job}/result.json")
    assert video.size > 0 and video.content_type == "video/mp4"
    assert manifest.content_type == "application/json"
    wait_for(lambda: message_count(infra, infra.settings.command_queue) == 0, 10)


def test_redelivered_command_republishes_completion_without_reprocessing(infra):
    infra.start()
    job = uuid4()
    publish_command(infra, job)
    drain(infra, infra.settings.event_queue, lambda m: any(e["status"] == "COMPLETED" for e in events_for(m, job)))

    publish_command(infra, job)
    messages = drain(infra, infra.settings.event_queue,
                     lambda m: any(e["status"] == "COMPLETED" for e in events_for(m, job)))

    assert [event["status"] for event in events_for(messages, job)] == ["COMPLETED"]
    assert SlowFakePipeline.calls == 1


def test_malformed_command_is_dead_lettered(infra):
    infra.start()

    publish_raw(infra, b"{not json")

    dead = drain(infra, infra.settings.dead_letter_queue, lambda m: len(m) >= 1, timeout=20)
    assert dead[0][1] == b"{not json"


def test_transient_failures_use_broker_redelivery_count_then_fail_and_dead_letter(infra):
    infra.start(store_class=FailingStore)
    job = uuid4()

    publish_command(infra, job)

    events = events_for(drain(infra, infra.settings.event_queue,
                              lambda m: any(e["status"] == "FAILED" for e in events_for(m, job))), job)
    failure = events[-1]
    assert failure["error"]["code"] == "STORAGE_FAILED"
    assert "Gave up after 2 attempt(s)" in failure["error"]["message"]
    assert "COMPLETED" not in [event["status"] for event in events]
    assert SlowFakePipeline.calls == 2
    dead = drain(infra, infra.settings.dead_letter_queue, lambda m: len(m) >= 1, timeout=20)
    assert json.loads(dead[0][1])["jobId"] == str(job)


def test_long_job_keeps_the_connection_alive_and_sends_heartbeat_events(infra):
    """A 25 s job with a 10 s AMQP heartbeat: the broker would drop a starved connection."""
    worker = infra.start(seconds=25)
    job = uuid4()

    publish_command(infra, job)
    messages = drain(infra, infra.settings.event_queue,
                     lambda m: any(e["status"] == "COMPLETED" for e in events_for(m, job)), timeout=90)

    assert len(worker.connections) == 1, "the worker had to reconnect during a long job"
    detecting = [e for e in events_for(messages, job) if e["status"] == "DETECTING"]
    assert len(detecting) >= 3
    wait_for(lambda: message_count(infra, infra.settings.command_queue) == 0, 10)
