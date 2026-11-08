# Phase 05 validation

## Environment

- **Platform:** Windows 11.
- **Backend:** JDK 21 and Maven 3.9.16, run offline from the local install (the wrapper's download is unavailable here).
- **Worker:** `ai-worker/.venv` with Python 3.11.15, PyTorch 2.13.0+cpu, Ultralytics 8.4.207, pika 1.4.4, and minio 7.2.20.
- **FFmpeg:** 9.0.2.
- **Docker:** Desktop 29.9.2.
- **Device:** CUDA was unavailable, so all inference ran on CPU.

Integration and end-to-end runs used **disposable** containers on unused host ports with random credentials:

- PostgreSQL 17
- RabbitMQ 4.2
- the project's MinIO image

The user's Compose stack, `.env`, data volumes, and images were not used or modified.

## Automated tests

| Check | Result |
| --- | --- |
| Backend unit + H2 (`mvn -B -o -Ppostgres-it clean verify`) | **PASS**: 119 tests (54 existing, 65 new: submission 25, lifecycle 16, event consumer 15, publisher 5, outbox 4) |
| Backend Testcontainers ITs (same run) | **PASS**: 48 tests. Persistence 40 (including 3 new V7 tests), catalog API 3, and **real RabbitMQ messaging 5**: topology, confirmed outbox publication, the event-driven lifecycle with duplicate completion, failure events, and dead-lettering |
| Backend packaging | **PASS**: `backend-1.0.0.jar` |
| Worker unit (`python -m pytest -q`) | **PASS**: 302 tests (216 existing, 86 new). The 5 broker integration tests skip themselves without `IT_*` settings |
| Same suite with host `RABBITMQ_*`/`WORKER_*`/`AI_*` overrides | **PASS**: 302, because the test environment is isolated |
| Worker ↔ real RabbitMQ 4.2 + MinIO (`tests/integration`) | **PASS**: 5 tests (listed below) |
| `docker compose config` (example env and the user's `.env`) | **PASS**. The user's host ports 18080/15432 are preserved |

The 5 worker integration tests:

- **Happy path:** stored artifacts, `COMPLETED`, and the command acknowledged.
- **Redelivery:** answered from storage without reprocessing.
- **Malformed command:** sent to the DLQ.
- **Transient storage failure:** the attempt count comes from the broker's `x-delivery-count`; after 2 attempts the worker publishes `FAILED` and the command goes to the DLQ.
- **Long job:** a 25 s job under a 10 s AMQP heartbeat completed without reconnecting, with periodic progress events.

## Real end-to-end asynchronous processing (PASS)

The backend JAR (`dev-harness` profile), the host worker process, PostgreSQL, RabbitMQ, and MinIO all ran as separate processes. `yolo11n` was enabled with SQL in the disposable database only. The input was a 4 s, 640×480 local clip.

| Observation | Result |
| --- | --- |
| Flyway on a fresh PostgreSQL 17 | V1–V7 applied |
| Worker and backend declared the same topology | No argument conflict |
| Status timeline from PostgreSQL | +1 s `QUEUED 0` → +9 s `DETECTING 15` → `DETECTING 46/77` → +19 s `ENCODING 85` → +21 s `COMPLETED 100` |
| Real YOLO11n CPU inference | 60/60 frames, 60 `bus` detections, 10,833 ms pipeline time |
| `detection_results` | Job-scoped output and result keys, `total_frames` 60, JSONB summary `{"bus": 60}`; outbox `PUBLISHED` after 1 attempt |
| MinIO objects | `detected.mp4` (275,415 bytes, `video/mp4`) and `result.json` (`application/json`). The bucket has no public policy. The manifest identifies `yolo11n`/YOLO11 and contains no local paths |
| Stored MP4 (FFprobe and full decode) | H.264, `yuv420p`, 640×480, 60 frames, decodes without errors. A frame shows a `bus 0.92` box |
| Duplicate command republished | The worker answered from storage; there was no second inference |
| Duplicate completion and a late `DETECTING` event | Recorded as `DUPLICATE` and `IGNORED_TERMINAL`; still exactly one result row |
| Job with a missing local file | `FAILED`, code `INVALID_SOURCE`, one attempt (permanent), no result |
| Submission with a disabled model (`yolov8n`) | Rejected by `InvalidDetectionJobException`; no job or message was created |
| Worker killed during `DETECTING` | The command returned to the queue. A new worker received it as attempt 2 and completed it with one result |

## Docker validation (PASS)

The worker image was built under a temporary tag (`yolo-vision-ai-worker:phase05`, removed afterwards), and its `pip check` passed. The `ai-detection-consumer` command was run against the disposable broker and MinIO:

- The Compose healthcheck command reported healthy.
- No AI libraries were imported at startup.
- A job for an unprepared `yolo26s` was consumed and failed with `MODEL_NOT_PREPARED`, with the remediation command. Nothing was downloaded.
- `docker stop` completed gracefully in 1.8 s (SIGTERM handled).

The full Compose stack was not started, so the user's running environment was left untouched.

## Not run

- **Live YouTube downloads:** the downloader is covered only by unit tests.
- **GPU inference.**
- **Lease-monitor timeout against the running stack:** this is covered by H2 lifecycle tests.
- **Outbox publication while the broker is down:** this is covered by unit tests of the publisher and outbox service.

## Defects found and fixed during validation

- **Pending acknowledgements at shutdown.** A finishing job left the active set before its acknowledgement ran on the connection thread. A graceful shutdown could therefore close the connection with the ack still pending, forcing a needless redelivery. Deliveries now remain active until their settlement executes.
- **Over-wide lock.** A `JOIN FETCH` inside the pessimistic job lock could also lock the shared model row on PostgreSQL. The lock now covers only the job row.
- **Test transaction handling.**
  - On PostgreSQL, the first expected constraint violation aborts the test's transaction, so the V7 constraint tests were split up.
  - A submission test cleared the persistence context before flushing.
- **Git Bash path conversion.** It rewrote container paths during manual Docker runs (`MSYS_NO_PATHCONV=1` is required). This affected only the validation commands, not the code.
