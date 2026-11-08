import json
import threading
import time
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.config.settings import Settings
from app.schemas.messaging import DetectionEvent, WorkerJobStatus
from app.workers import rabbitmq_worker
from app.workers.job_processor import Disposition, EventPublicationError, Settlement
from app.workers.rabbitmq_worker import BrokerEventSink, RabbitMQWorker, declare_topology, delivery_attempt

JOB = UUID("3f1d2a4e-8a7b-4c1d-9e2f-0123456789ab")


class FakeChannel:
    def __init__(self):
        self.calls = []
        self.is_open = True
        self.consumer = None
        self.publish_error = None

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            if name == "basic_consume":
                self.consumer = kwargs["on_message_callback"]
                return "consumer-tag"
            if name == "basic_publish" and self.publish_error:
                raise self.publish_error
            return None
        return record

    def names(self):
        return [call[0] for call in self.calls]


class FakeConnection:
    """Runs thread-safe callbacks only inside process_data_events, like pika."""

    def __init__(self, deliveries=(), on_idle=None):
        self.is_open = True
        self.channels = []
        self.pending = list(deliveries)
        self.callbacks = []
        self.lock = threading.Lock()
        self.on_idle = on_idle
        self.closed = False

    def channel(self):
        channel = FakeChannel()
        self.channels.append(channel)
        return channel

    def add_callback_threadsafe(self, callback):
        if not self.is_open:
            raise RuntimeError("connection closed")
        with self.lock:
            self.callbacks.append(callback)

    def process_data_events(self, time_limit=0):
        consumer = self.channels[0]
        while self.pending:
            tag, headers, body = self.pending.pop(0)
            consumer.consumer(consumer, SimpleNamespace(delivery_tag=tag), SimpleNamespace(headers=headers), body)
        with self.lock:
            callbacks, self.callbacks = self.callbacks, []
        for callback in callbacks:
            callback()
        if self.on_idle:
            self.on_idle(self)
        time.sleep(0.01)

    def close(self):
        self.is_open = False
        self.closed = True


class FakeProcessor:
    def __init__(self, disposition=Disposition.ACK, publish=True, delay=0.0):
        self.disposition = disposition
        self.publish = publish
        self.delay = delay
        self.calls = []

    def handle(self, body, attempt, sink):
        self.calls.append((body, attempt))
        time.sleep(self.delay)
        if self.publish:
            sink.publish(DetectionEvent(job_id=JOB, status=WorkerJobStatus.DETECTING, progress=50), required=True)
        return Settlement(self.disposition)


@pytest.fixture
def settings(tmp_path):
    return Settings(RABBITMQ_PASSWORD="test-only", WORKER_CONCURRENCY=1, WORKER_SHUTDOWN_TIMEOUT_SECONDS=5,
                    WORKER_RETRY_BACKOFF_SECONDS=0, WORKER_HEALTH_FILE=tmp_path / "health.json",
                    RABBITMQ_DELIVERY_LIMIT=7)


def run_until(worker, condition, timeout=5.0):
    def stopper(connection):
        if condition(connection):
            worker.request_stop()

    return stopper


def test_topology_matches_the_backend_declaration(settings):
    channel = FakeChannel()

    declare_topology(channel, settings)

    exchanges = [call[2] for call in channel.calls if call[0] == "exchange_declare"]
    assert {e["exchange"] for e in exchanges} == {"vision.detection.commands", "vision.detection.events",
                                                 "vision.detection.dead-letter.exchange"}
    assert all(e["exchange_type"] == "direct" and e["durable"] for e in exchanges)
    queues = {call[2]["queue"]: call[2] for call in channel.calls if call[0] == "queue_declare"}
    for name in ("vision.detection.jobs", "vision.detection.events.backend"):
        assert queues[name]["durable"] is True
        assert queues[name]["arguments"] == {
            "x-queue-type": "quorum", "x-delivery-limit": 7,
            "x-dead-letter-exchange": "vision.detection.dead-letter.exchange",
            "x-dead-letter-routing-key": "detection.dead-letter",
        }
    assert queues["vision.detection.dead-letter"]["arguments"] == {"x-queue-type": "quorum"}
    bindings = {(c[2]["queue"], c[2]["exchange"], c[2]["routing_key"]) for c in channel.calls if c[0] == "queue_bind"}
    assert ("vision.detection.jobs", "vision.detection.commands", "detection.execute") in bindings
    assert ("vision.detection.events.backend", "vision.detection.events", "detection.status") in bindings


@pytest.mark.parametrize("headers, attempt", [(None, 1), ({}, 1), ({"x-delivery-count": 0}, 1),
                                              ({"x-delivery-count": 2}, 3), ({"x-delivery-count": "bad"}, 1)])
def test_delivery_attempt_uses_the_quorum_delivery_count(headers, attempt):
    assert delivery_attempt(SimpleNamespace(headers=headers)) == attempt


def publish_from_thread(sink, event, required):
    errors = []

    def target():
        try:
            sink.publish(event, required=required)
        except Exception as error:
            errors.append(error)

    thread = threading.Thread(target=target)
    thread.start()
    return thread, errors


def test_sink_publishes_persistent_json_through_the_connection_thread(settings):
    connection = FakeConnection()
    channel = connection.channel()
    sink = BrokerEventSink(connection, channel, settings, timeout=5)
    event = DetectionEvent(job_id=JOB, status=WorkerJobStatus.DETECTING, progress=65)

    thread, errors = publish_from_thread(sink, event, True)
    while thread.is_alive():
        connection.process_data_events()
    thread.join()

    assert errors == []
    _, _, kwargs = next(call for call in channel.calls if call[0] == "basic_publish")
    assert kwargs["exchange"] == "vision.detection.events" and kwargs["routing_key"] == "detection.status"
    assert kwargs["mandatory"] is True
    assert kwargs["properties"].delivery_mode == 2 and kwargs["properties"].content_type == "application/json"
    assert kwargs["properties"].message_id == str(event.event_id)
    assert json.loads(kwargs["body"])["progress"] == 65


def test_unconfirmed_required_event_raises_but_optional_progress_does_not(settings):
    connection = FakeConnection()
    channel = connection.channel()
    channel.publish_error = RuntimeError("nack")
    sink = BrokerEventSink(connection, channel, settings, timeout=5)
    event = DetectionEvent(job_id=JOB, status=WorkerJobStatus.DETECTING, progress=65)

    for required, expected in ((True, 1), (False, 0)):
        thread, errors = publish_from_thread(sink, event, required)
        while thread.is_alive():
            connection.process_data_events()
        assert len(errors) == expected
    assert isinstance(errors, list)


def test_publishing_on_a_closed_connection_fails_fast(settings):
    connection = FakeConnection()
    connection.is_open = False
    sink = BrokerEventSink(connection, FakeChannel(), settings, timeout=5)

    with pytest.raises(EventPublicationError):
        sink.publish(DetectionEvent(job_id=JOB, status=WorkerJobStatus.DETECTING, progress=1), required=True)


@pytest.mark.parametrize("disposition, method, requeue", [
    (Disposition.ACK, "basic_ack", None), (Disposition.RETRY, "basic_nack", True),
    (Disposition.DEAD_LETTER, "basic_reject", False),
])
def test_each_disposition_settles_the_delivery_correctly(settings, disposition, method, requeue):
    processor = FakeProcessor(disposition)
    worker = RabbitMQWorker(settings, processor)
    connection = FakeConnection(deliveries=[(7, {"x-delivery-count": 1}, b"{}")])
    connection.on_idle = run_until(worker, lambda c: any(
        name in c.channels[0].names() for name in ("basic_ack", "basic_nack", "basic_reject")))
    worker.connection_factory = lambda params: connection

    worker._serve_once()

    consumer = connection.channels[0]
    _, _, kwargs = next(call for call in consumer.calls if call[0] == method)
    assert kwargs["delivery_tag"] == 7
    if requeue is not None:
        assert kwargs["requeue"] is requeue
    assert processor.calls == [(b"{}", 2)]


def test_consumer_uses_manual_acks_bounded_prefetch_and_confirmed_publishing(settings):
    worker = RabbitMQWorker(settings, FakeProcessor())
    connection = FakeConnection(deliveries=[(1, None, b"{}")])
    connection.on_idle = run_until(worker, lambda c: "basic_ack" in c.channels[0].names())
    worker.connection_factory = lambda params: connection

    worker._serve_once()

    consumer, publisher = connection.channels
    assert ("basic_qos", (), {"prefetch_count": 1}) in consumer.calls
    consume = next(call for call in consumer.calls if call[0] == "basic_consume")
    assert consume[2]["auto_ack"] is False and consume[2]["queue"] == "vision.detection.jobs"
    assert "confirm_delivery" in publisher.names() and "basic_publish" in publisher.names()
    assert "basic_cancel" in consumer.names() and connection.closed
    assert json.loads(settings.worker_health_file.read_text())["connected"] is True


def test_graceful_shutdown_lets_the_running_job_finish_and_acknowledge(settings):
    worker = RabbitMQWorker(settings, FakeProcessor(delay=0.3, publish=False))
    connection = FakeConnection(deliveries=[(3, None, b"{}")])
    # Stop as soon as the job starts; it must still be acknowledged before the close.
    connection.on_idle = run_until(worker, lambda c: worker._active_count() > 0)
    worker.connection_factory = lambda params: connection

    worker._serve_once()

    assert "basic_ack" in connection.channels[0].names()


def test_settling_after_the_connection_closed_is_skipped_for_redelivery(settings):
    worker = RabbitMQWorker(settings, FakeProcessor())
    connection = FakeConnection()
    channel = connection.channel()
    connection.is_open = False

    worker._settle(connection, channel, 9, Settlement(Disposition.ACK))

    assert "basic_ack" not in channel.names()


def test_run_reconnects_after_a_connection_failure_and_stops_on_request(settings):
    worker = RabbitMQWorker(settings, FakeProcessor())
    attempts = []

    def factory(params):
        attempts.append(params)
        if len(attempts) == 1:
            raise ConnectionError("broker down")
        connection = FakeConnection()
        connection.on_idle = lambda c: worker.request_stop()
        return connection

    worker.connection_factory = factory
    worker._stopping.wait = lambda timeout=None: False  # no real backoff sleep in tests

    assert worker.run() == 0
    assert len(attempts) == 2


def test_connection_parameters_use_configured_heartbeat_and_credentials(settings):
    captured = []
    worker = RabbitMQWorker(settings, FakeProcessor(), connection_factory=lambda params: captured.append(params))

    worker._connect()

    params = captured[0]
    assert params.heartbeat == 60 and params.host == "localhost" and params.port == 5672
    assert params.credentials.username == "yolovision"


def test_main_refuses_to_start_without_credentials(monkeypatch):
    monkeypatch.setattr(rabbitmq_worker, "build_worker", lambda settings: pytest.fail("must not start"))

    assert rabbitmq_worker.main([]) == 2


def test_request_stop_is_idempotent(settings):
    worker = RabbitMQWorker(settings, FakeProcessor())
    worker.request_stop()
    worker.request_stop()

    assert worker._stopping.is_set()
