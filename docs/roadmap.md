# Roadmap

The application starts with vehicle detection as its first use case. Model, class, and job contracts should allow general-purpose object detection as the product develops. Each future phase requires its own scoped implementation, relevant tests, one or more logical Conventional Commits, a push to `origin/main`, and verification of the remote result.

| Phase | Scope | Completion evidence |
| --- | --- | --- |
| 1 — Foundation | Monorepo, Spring Boot system API, FastAPI health, React dashboard, infrastructure, configuration, documentation | Service builds and tests, real backend connection state, health checks, Compose validation and startup where Docker is available, verified Git push |
| 2 — Domain and job foundation | Define model/class catalog contracts, job lifecycle, persistence schema, API validation, messaging contracts, and object storage integration | Migrations and API tests, explicit job states, verified asynchronous contracts and storage behavior |
| 3 — Video detection engine | Add permitted video acquisition, CPU-first YOLO inference, selected classes and confidence thresholds, video encoding, queue consumer, and result storage | Tested processing pipeline, bounded resource use, useful failure states, reproducible small video fixture checks |
| 4 — Detection experience | Implement video URL/model/size/class configuration, start processing, progress events, annotated previews, result downloads | End-to-end job workflow and recovery from worker/API failures |
| 5 — History and insights | Detection history, filters, object counts, and documented statistics semantics | Correct query behavior and statistics based on persisted detection results |
| 6 — Deployment and operations | Environment-specific security, authentication if required, CI, monitoring, retention, backups, and scaling | Deployment checks, operational procedures, dependency health, and recovery exercises |

These later scopes are a suggested sequence, not implemented features. A future phase may refine boundaries before coding.

## Phase 1 boundaries

Phase 1 intentionally contains no YouTube downloading, YOLO inference, detection job processing, video encoding, object tracking, detection statistics, authentication, uploads, or downloads. Dashboard feature pages are placeholders. Infrastructure availability and HTTP liveness do not imply that a video pipeline exists.

## Definition of a completed phase

Read `AGENTS.md`, inspect the existing repository and user changes, and synchronize `main` with `origin/main` using fast-forward updates. Keep service boundaries intact, configure through environment variables, and keep credentials and generated media out of Git.

Run and report relevant checks accurately, resolve known failures, inspect staged changes, commit the completed work, push without force, and verify the resulting remote hash and working tree. Missing tools or unavailable infrastructure must remain explicit validation limitations.
