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

## Phase 07 progress

The React dashboard now uses the real APIs:

- **Dashboard:** KPI counts taken from pagination metadata, recent activity, and model families.
- **Models:** the catalog with server-side filters and a details view.
- **History:** paged, filtered history.
- **Job details:** live progress through `EventSource` with a conservative polling fallback, plus result statistics labelled as frame detection events.

All pages have consistent loading, empty, and error states. See [frontend-dashboard.md](frontend-dashboard.md) and [phase-07-validation.md](phase-07-validation.md).

## Phase 08 progress

The Detection route is now the Video Detection Workspace:

- **Source:** a YouTube URL pre-check that mirrors the backend rules and is never stricter.
- **Model:** version and size chosen from real catalog records. Disabled models are shown honestly and can never be submitted.
- **Settings:** COCO class selection (vehicle preset, all 80, search, clear), confidence slider and number, and image size presets.
- **Summary:** the exact configuration, where "Ready" means valid and enabled only.
- **Submission:** the existing `POST /api/v1/detections`, with duplicate-submit protection and no automatic retry. Ambiguous failures point to History.
- **After submission:** the existing job page, with live SSE progress.

No backend, worker, or schema change was needed. See [video-detection-workspace.md](video-detection-workspace.md) and [phase-08-validation.md](phase-08-validation.md).

## Phase 09 progress

Completed jobs can now be watched and downloaded:

- **Backend:** Spring Boot streams the annotated MP4 from the private MinIO bucket. Keys come from database records only, and only after job, status, result, and key-ownership checks. Single HTTP Range requests (206/416) make seeking work.
- **Downloads:** the MP4 and the worker's original `result.json` are available as safe attachments.
- **Frontend:** the job page has a native player with loading, missing-artifact, and storage-outage states, plain download links, and a raw JSON viewer.

The bucket stays private, and no migration was needed. See [video-preview-download.md](video-preview-download.md) and [phase-09-validation.md](phase-09-validation.md).

## Phase 10 — integration testing, security hardening, and deployment readiness

The final planned phase stabilized the existing architecture without adding features:

- **Deployment:** `compose.production.yaml` adds a hardened self-hosted layout. It serves a static nginx frontend with CSP and security headers and unbuffered SSE and Range proxying, publishes only the UI port on localhost, and disables Swagger.
- **Fixes:**
  - The Vite proxy now keeps `Host`, so UI requests are same-origin under any local hostname.
  - The backend sends baseline security headers, shuts down gracefully, and logs its storage target.
  - Worker error sanitization no longer leaks Windows or UNC paths.
- **Fixes found during live validation:**
  - nginx resolves the backend per request, so a recreated backend is found without restarting nginx.
  - A database outage returns 503 instead of 500.
  - The RabbitMQ health check waits for the AMQP listener.
- **Dependencies:** advisories in Tomcat, the PostgreSQL JDBC driver, the RabbitMQ client, Netty, Jackson, Log4j API, commons-lang3, and MinIO's transitive libraries are fixed by pinning fixed patch or minor versions.
- **CI:** a GitHub Actions workflow runs the frontend, backend, Python, and integration suites.
- **Docs:** [deployment-guide.md](deployment-guide.md), [operations-runbook.md](operations-runbook.md), and [phase-10-validation.md](phase-10-validation.md), which records the isolated full-stack Docker validation, failure tests, remaining risks, and the release-readiness classification.

**Release status (validated, see [phase-10-validation.md § 10](phase-10-validation.md#10-release-readiness)): READY FOR CONTROLLED SELF-HOSTED USE**, meaning a single trusted user or a trusted private network on a localhost or private bind, which includes local demos.

The supporting evidence:

- every automated suite passed (frontend 185, backend 329 + 64 integration, Python 312);
- a real full-stack Docker E2E with YOLO11n inference, browser playback, and byte-verified downloads passed;
- failure and recovery tests passed (worker SIGKILL, broker, storage, and database outages).

**Not ready for public or multi-user deployment.** That is blocked on authentication, authorization and job ownership, rate limiting, and TLS (see the deployment guide, § 28). The new CI workflow had not yet been verified on GitHub when this was written.

## Phase 1 boundaries

Phase 1 intentionally contains no YouTube downloading, YOLO inference, detection job processing, video encoding, object tracking, detection statistics, authentication, uploads, or downloads. Dashboard feature pages are placeholders. Infrastructure availability and HTTP liveness do not imply that a video pipeline exists.

## Definition of a completed phase

Read `AGENTS.md`, inspect the existing repository and user changes, and synchronize `main` with `origin/main` using fast-forward updates. Keep service boundaries intact, configure through environment variables, and keep credentials and generated media out of Git.

Run and report relevant checks accurately, resolve known failures, inspect staged changes, commit the completed work, push without force, and verify the resulting remote hash and working tree. Missing tools or unavailable infrastructure must remain explicit validation limitations.
