"""Long-running detection consumer: ``python -m app.workers.rabbitmq_worker``.

Threading model: the pika BlockingConnection lives on the main thread, which keeps calling
``process_data_events`` so AMQP heartbeats are serviced while inference runs for minutes.
Jobs execute on a bounded thread pool. Worker threads never touch pika objects directly:
publishes and acknowledgements are marshalled back with ``add_callback_threadsafe``, the
only thread-safe pika entry point.

Acknowledgement policy: a command is acknowledged only after its outcome event (COMPLETED
or FAILED) was confirmed by the broker. Transient failures are requeued a bounded number of
times; unprocessable commands and exhausted retries are rejected to the dead-letter queue.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from functools import partial
import json
import logging
import logging.config
from pathlib import Path
import signal
import sys
import threading
import time
from typing import Any

from app.config.logging import logging_config
from app.config.settings import Settings, get_settings
from app.schemas.messaging import EVENT_MESSAGE_TYPE, SCHEMA_VERSION, DetectionEvent
from app.workers.job_processor import (
    DetectionJobProcessor, Disposition, EventPublicationError, Settlement,
)

logger = logging.getLogger(__name__)

PUBLISH_TIMEOUT_SECONDS = 30
MAX_RECONNECT_DELAY_SECONDS = 30
HEALTH_INTERVAL_SECONDS = 5


def declare_topology(channel: Any, settings: Settings) -> None:
    """Declare exactly what the backend's RabbitConfiguration declares (same arguments)."""
    for exchange in (settings.command_exchange, settings.event_exchange, settings.dead_letter_exchange):
        channel.exchange_declare(exchange=exchange, exchange_type="direct", durable=True)
    work_arguments = {
        "x-queue-type": "quorum",
        "x-delivery-limit": settings.delivery_limit,
        "x-dead-letter-exchange": settings.dead_letter_exchange,
        "x-dead-letter-routing-key": settings.dead_letter_routing_key,
    }
    channel.queue_declare(queue=settings.command_queue, durable=True, arguments=work_arguments)
    channel.queue_declare(queue=settings.event_queue, durable=True, arguments=work_arguments)
    channel.queue_declare(queue=settings.dead_letter_queue, durable=True, arguments={"x-queue-type": "quorum"})
    channel.queue_bind(queue=settings.command_queue, exchange=settings.command_exchange,
                       routing_key=settings.command_routing_key)
    channel.queue_bind(queue=settings.event_queue, exchange=settings.event_exchange,
                       routing_key=settings.event_routing_key)
    channel.queue_bind(queue=settings.dead_letter_queue, exchange=settings.dead_letter_exchange,
                       routing_key=settings.dead_letter_routing_key)


def delivery_attempt(properties: Any) -> int:
    """Quorum queues count failed deliveries in x-delivery-count (absent on the first one)."""
    headers = getattr(properties, "headers", None) or {}
    try:
        return max(1, int(headers.get("x-delivery-count", 0)) + 1)
    except (TypeError, ValueError):
        return 1


class BrokerEventSink:
    """Publishes events from worker threads through the connection's thread-safe callback."""

    def __init__(self, connection: Any, channel: Any, settings: Settings,
                 timeout: float = PUBLISH_TIMEOUT_SECONDS) -> None:
        self.connection = connection
        self.channel = channel
        self.settings = settings
        self.timeout = timeout

    def publish(self, event: DetectionEvent, *, required: bool) -> None:
        import pika

        body = event.to_json_bytes()
        properties = pika.BasicProperties(
            content_type="application/json", content_encoding="utf-8",
            delivery_mode=pika.DeliveryMode.Persistent, message_id=str(event.event_id),
            correlation_id=str(event.job_id), type=EVENT_MESSAGE_TYPE,
            timestamp=int(event.timestamp.timestamp()), headers={"schemaVersion": SCHEMA_VERSION},
        )
        done = threading.Event()
        failure: list[BaseException] = []

        def send() -> None:
            try:
                # Confirm mode: returns only after the broker acknowledged the message;
                # mandatory makes an unroutable event an error instead of a silent drop.
                self.channel.basic_publish(exchange=self.settings.event_exchange,
                                           routing_key=self.settings.event_routing_key,
                                           body=body, properties=properties, mandatory=True)
            except BaseException as error:  # noqa: BLE001 - reported to the waiting thread
                failure.append(error)
            finally:
                done.set()

        try:
            self.connection.add_callback_threadsafe(send)
            confirmed = done.wait(self.timeout)
        except Exception as error:
            failure.append(error)
            confirmed = True
        if confirmed and not failure:
            return
        reason = type(failure[0]).__name__ if failure else "timeout"
        if required:
            raise EventPublicationError(f"{event.status.value} event for job {event.job_id} not confirmed ({reason})")
        logger.warning("%s event for job %s was not published (%s)", event.status.value, event.job_id, reason)


class RabbitMQWorker:
    def __init__(
        self, settings: Settings, processor: DetectionJobProcessor, *,
        connection_factory: Callable[[Any], Any] | None = None,
    ) -> None:
        self.settings = settings
        self.processor = processor
        self.connection_factory = connection_factory
        self._stopping = threading.Event()
        self._active: dict[int, Future[None]] = {}
        self._active_lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=settings.worker_concurrency,
                                            thread_name_prefix="detection-job")
        self._health_written = 0.0

    # Lifecycle -------------------------------------------------------------------------

    def request_stop(self, *_: object) -> None:
        if not self._stopping.is_set():
            logger.info("Shutdown requested; finishing active jobs (up to %.0fs)",
                        self.settings.worker_shutdown_timeout_seconds)
        self._stopping.set()

    def install_signal_handlers(self) -> None:
        for name in ("SIGTERM", "SIGINT", "SIGBREAK"):
            if hasattr(signal, name):
                signal.signal(getattr(signal, name), self.request_stop)

    def run(self) -> int:
        delay = 1.0
        while not self._stopping.is_set():
            try:
                self._serve_once()
                delay = 1.0
            except Exception as error:
                if self._stopping.is_set():
                    break
                logger.warning("RabbitMQ connection lost or unavailable (%s); reconnecting in %.0fs",
                               type(error).__name__, delay)
                # Unacknowledged commands are redelivered by the broker. Let running jobs
                # finish first so a redelivery is answered from stored artifacts, not rerun.
                self._wait_for_active(timeout=None)
                self._write_health(connected=False, force=True)
                self._stopping.wait(delay)
                delay = min(delay * 2, MAX_RECONNECT_DELAY_SECONDS)
        self._executor.shutdown(wait=False, cancel_futures=True)
        logger.info("Detection worker stopped")
        return 0

    # Connection ------------------------------------------------------------------------

    def _connect(self) -> Any:
        import pika

        if self.settings.rabbitmq_password is None:
            raise RuntimeError("RABBITMQ_PASSWORD is not configured")
        parameters = pika.ConnectionParameters(
            host=self.settings.rabbitmq_host, port=self.settings.rabbitmq_port,
            virtual_host=self.settings.rabbitmq_vhost,
            credentials=pika.PlainCredentials(self.settings.rabbitmq_username,
                                              self.settings.rabbitmq_password.get_secret_value()),
            heartbeat=self.settings.rabbitmq_heartbeat_seconds, blocked_connection_timeout=300,
            connection_attempts=1, client_properties={"connection_name": "yolo-vision-detection-worker"},
        )
        factory = self.connection_factory or pika.BlockingConnection
        return factory(parameters)

    def _serve_once(self) -> None:
        connection = self._connect()
        try:
            consumer = connection.channel()
            publisher = connection.channel()
            publisher.confirm_delivery()
            declare_topology(consumer, self.settings)
            consumer.basic_qos(prefetch_count=self.settings.effective_prefetch_count)
            sink = BrokerEventSink(connection, publisher, self.settings)
            tag = consumer.basic_consume(
                queue=self.settings.command_queue, auto_ack=False,
                on_message_callback=partial(self._on_message, connection, consumer, sink),
            )
            logger.info("Consuming %s (concurrency %d, prefetch %d)", self.settings.command_queue,
                        self.settings.worker_concurrency, self.settings.effective_prefetch_count)
            while not self._stopping.is_set():
                connection.process_data_events(time_limit=1)
                self._write_health(connected=True)
            # Graceful shutdown: stop new deliveries, keep servicing the connection so
            # running jobs can publish and acknowledge, then close.
            consumer.basic_cancel(tag)
            deadline = time.monotonic() + self.settings.worker_shutdown_timeout_seconds
            while self._active_count() and time.monotonic() < deadline:
                connection.process_data_events(time_limit=0.5)
            if self._active_count():
                logger.warning("%d job(s) still running at shutdown; their commands will be redelivered",
                               self._active_count())
        finally:
            try:
                if connection.is_open:
                    connection.close()
            except Exception:
                logger.debug("Ignoring an error while closing the connection", exc_info=True)

    # Deliveries ------------------------------------------------------------------------

    def _on_message(self, connection: Any, channel: Any, sink: BrokerEventSink,
                    _channel: Any, method: Any, properties: Any, body: bytes) -> None:
        tag = method.delivery_tag
        attempt = delivery_attempt(properties)
        future = self._executor.submit(self._process, connection, channel, sink, tag, body, attempt)
        with self._active_lock:
            self._active[tag] = future

    def _process(self, connection: Any, channel: Any, sink: BrokerEventSink,
                 tag: int, body: bytes, attempt: int) -> None:
        try:
            settlement = self.processor.handle(body, attempt, sink)
        except Exception:
            logger.exception("Unexpected error while handling a command; requeueing it")
            settlement = Settlement(Disposition.RETRY, retry_delay_seconds=self.settings.worker_retry_backoff_seconds)
        if settlement.disposition == Disposition.RETRY and settlement.retry_delay_seconds:
            self._stopping.wait(settlement.retry_delay_seconds)
        self._settle(connection, channel, tag, settlement)

    def _settle(self, connection: Any, channel: Any, tag: int, settlement: Settlement) -> None:
        # A delivery stays "active" until its settlement ran on the connection thread, so a
        # graceful shutdown cannot close the connection while an acknowledgement is pending.
        def apply() -> None:
            try:
                if not channel.is_open:
                    logger.warning("Channel closed before settling delivery %d; it will be redelivered", tag)
                elif settlement.disposition == Disposition.ACK:
                    channel.basic_ack(delivery_tag=tag)
                elif settlement.disposition == Disposition.RETRY:
                    channel.basic_nack(delivery_tag=tag, requeue=True)
                else:
                    channel.basic_reject(delivery_tag=tag, requeue=False)
            finally:
                self._forget(tag)

        try:
            connection.add_callback_threadsafe(apply)
        except Exception:
            self._forget(tag)
            logger.warning("Connection closed before settling delivery %d; it will be redelivered", tag)
        if settlement.disposition != Disposition.ACK:
            logger.info("Delivery %d settled as %s (%s)", tag, settlement.disposition.value,
                        settlement.error_code or "no code")

    # Helpers ---------------------------------------------------------------------------

    def _forget(self, tag: int) -> None:
        with self._active_lock:
            self._active.pop(tag, None)

    def _active_count(self) -> int:
        with self._active_lock:
            return len(self._active)

    def _wait_for_active(self, timeout: float | None) -> None:
        with self._active_lock:
            futures = list(self._active.values())
        for future in futures:
            try:
                future.result(timeout=timeout)
            except Exception:
                logger.debug("A job ended with an error while waiting", exc_info=True)
        # Settlements queued on a dead connection never run; their deliveries are redelivered.
        with self._active_lock:
            for tag in [tag for tag, future in self._active.items() if future.done()]:
                del self._active[tag]

    def _write_health(self, *, connected: bool, force: bool = False) -> None:
        path = self.settings.worker_health_file
        now = time.monotonic()
        if path is None or (not force and now - self._health_written < HEALTH_INTERVAL_SECONDS):
            return
        self._health_written = now
        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(json.dumps({
                "updatedAt": datetime.now(UTC).isoformat(), "connected": connected,
                "activeJobs": self._active_count(),
            }), encoding="utf-8")
        except OSError:
            logger.warning("Worker health file could not be written", exc_info=True)


def build_worker(settings: Settings) -> RabbitMQWorker:
    from app.services.artifact_storage import MinioArtifactStore

    return RabbitMQWorker(settings, DetectionJobProcessor(settings, MinioArtifactStore(settings)))


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    logging.config.dictConfig(logging_config(settings.log_level))
    missing = [name for name, value in (("RABBITMQ_PASSWORD", settings.rabbitmq_password),
                                        ("MINIO_SECRET_KEY", settings.minio_secret_key)) if value is None]
    if missing:
        logger.error("Missing required configuration: %s", ", ".join(missing))
        return 2
    worker = build_worker(settings)
    worker.install_signal_handlers()
    logger.info("Detection worker starting; no model is loaded until a job requires it")
    return worker.run()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
