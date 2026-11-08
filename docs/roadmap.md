# Roadmap

The application starts with vehicle detection as its first use case. Model, class, and job contracts should allow general-purpose object detection as the product develops. Each future phase requires its own scoped implementation, relevant tests, one or more logical Conventional Commits, a push to `origin/main`, and verification of the remote result.

| Phase | Scope | Completion evidence |
| --- | --- | --- |
| 1 — Foundation | Monorepo, Spring Boot system API, FastAPI health, React dashboard, infrastructure, configuration, documentation | Service builds and tests, real backend connection state, health checks, Compose validation and startup where Docker is available, verified Git push |
| 2 — Database design and persistence | Model configurations, detection jobs and results, Flyway migrations, UUID/JSONB/timestamp mappings, repositories, DTO foundations, disabled YOLO26s seed | Persistence and constraint tests, production migrations verified separately on PostgreSQL, unchanged system API, Maven build, and verified Git push |
| 3 — Python YOLO detection engine | Independent local/authorized-YouTube pipeline, lazy YOLO26s loading, CPU/CUDA selection, streaming annotations, cumulative statistics, progress, H.264 output, JSON metadata, CLI | Unit tests, explicit short-video real inference, decode/codec checks, health compatibility, verified Git push |
| 4 — YOLO model management | Extend supported model metadata and worker availability/preparation contracts | Supported model/version/size validation and verified availability before enabling database selections |
| 5 — RabbitMQ integration | Add explicit job/result/progress message contracts and worker consumers/publishers | Tested acknowledgements, idempotency, failure handling, and bounded execution |
| 6 — Spring Boot detection APIs | Add transactional detection services, job APIs, progress integration, and storage contracts | API validation, persistence/messaging integration, failure and recovery checks |
| 7 — Detection experience | Add frontend detection forms, progress, annotated previews, and downloads | End-to-end processing and useful user-facing failure states |
| 8 — History and insights | Detection history, filters, detection counts, and documented statistics semantics | Queries and statistics based on persisted results; no unique counts without tracking |
| 9 — Deployment and operations | Environment-specific security, authentication if required, CI, monitoring, retention, backups, and scaling | Deployment checks, operational procedures, dependency health, and recovery exercises |

These later scopes are a suggested sequence, not implemented features. A future phase may refine boundaries before coding.

## Phase 02 progress

The persistence implementation defines the three domain tables, model/job/result relationships, query indexes, database checks, and the nine job status names. The `yolo26s` seed is metadata only and remains disabled. Repository and response DTO foundations prepare future service work without adding detection APIs, queue consumers, model loading, or video processing.

Fast H2 tests and production PostgreSQL integration tests have separate roles. The latter run with `backend/mvnw.cmd -Ppostgres-it verify` against an isolated Testcontainers database when Docker is available. Actual execution results must be reported separately; an unavailable PostgreSQL run is **NOT RUN**. See [database-design.md](database-design.md) for schema details and commands.

Phase 03 adds the independent Python engine; its availability does not automatically enable the registered model for application selection.

## Phase 03 progress

The engine provides typed source requests, bounded local/YouTube input handling, lazy YOLO26s caching, CPU/automatic/explicit-CUDA selection, streaming annotated frames, cumulative box statistics, progress callbacks, H.264 MP4 export, JSON metadata, a CLI, and an explicitly invoked real inference smoke command. The HTTP health route remains lightweight and does not load a model.

The normal test suite uses fake models and mocked downloads. Real inference, output decoding, Docker startup, and live YouTube downloads must each be reported according to actual execution. See [ai-detection-engine.md](ai-detection-engine.md) for setup and testing, and [phase-03-validation.md](phase-03-validation.md) for the executed CPU smoke test, CLI run, and media verification. The database model remains disabled; no queue integration, detection API, frontend form, MinIO transfer, tracking, or unique-vehicle counting is included.

## Phase 04 progress

The catalog registers 20 pretrained detection checkpoints (YOLOv8, YOLO11, YOLO12, YOLO26 × n/s/m/l/x) through Flyway V6, all disabled. It serves them through read-only Spring Boot APIs and lets the engine select any approved key. Explicit worker commands list, inspect, and prepare models, and a verification record is written only after a successful load. See [yolo-model-management.md](yolo-model-management.md) and [phase-04-validation.md](phase-04-validation.md). Enablement remains an administrator database action, and no preparation endpoint is exposed.

## Phase 05 progress

Phase 05 adds asynchronous processing:

- **Submission:** an internal job submission service that requires an enabled model.
- **Publication:** a transactional outbox published with publisher confirms.
- **Topology:** durable quorum queues with delivery limits and a dead-letter queue.
- **Worker:** a Python consumer that keeps AMQP heartbeats alive during long inference, sends throttled progress and heartbeat events, stores artifacts in MinIO, and classifies failures as permanent or transient with bounded retries.
- **Lifecycle:** a forward-only, idempotent job lifecycle with persisted results, plus a lease monitor for silent jobs.

See [asynchronous-job-processing.md](asynchronous-job-processing.md) and [phase-05-validation.md](phase-05-validation.md), including the real end-to-end YOLO11n run. There is still no public job endpoint, cancellation, or download link.

## Phase 06 progress

Phase 06 adds the detection REST APIs on top of the Phase 05 submission service and outbox:

- **Submission:** create returns 202 with a `Location` header.
- **Reads:** details, paged and filtered history, and result metadata. Result counts are labelled as frame detections.
- **Progress:** Server-Sent Events backed by one shared database poller, with heartbeats, a connection cap, and terminal close.
- **Errors and docs:** RFC 9457 errors with stable codes, plus OpenAPI and Swagger UI.

No migration was needed. The API is unauthenticated and development-only. See [detection-rest-api.md](detection-rest-api.md) and [phase-06-validation.md](phase-06-validation.md).

Phase 07 integrates the React dashboard with these APIs.

## Phase 1 boundaries

Phase 1 intentionally contains no YouTube downloading, YOLO inference, detection job processing, video encoding, object tracking, detection statistics, authentication, uploads, or downloads. Dashboard feature pages are placeholders. Infrastructure availability and HTTP liveness do not imply that a video pipeline exists.

## Definition of a completed phase

Read `AGENTS.md`, inspect the existing repository and user changes, and synchronize `main` with `origin/main` using fast-forward updates. Keep service boundaries intact, configure through environment variables, and keep credentials and generated media out of Git.

Run and report relevant checks accurately, resolve known failures, inspect staged changes, commit the completed work, push without force, and verify the resulting remote hash and working tree. Missing tools or unavailable infrastructure must remain explicit validation limitations.
