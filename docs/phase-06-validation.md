# Phase 06 validation

## Environment

- **Platform:** Windows 11.
- **Backend:** JDK 21 and Maven 3.9.16, run offline from the local install.
- **Container runtime:** Docker Desktop 29.9.2.
- **Worker:** the existing `ai-worker/.venv` (unchanged in this phase) and FFmpeg 9.0.2.
- **Device:** CPU only.

Live checks used **disposable** containers on unused host ports with random credentials:

- PostgreSQL 17
- RabbitMQ 4.2
- the project's MinIO image

The user's `.env`, Compose stack, volumes, and host ports 18080/15432 were not used or changed.

## Automated tests

| Check | Result |
| --- | --- |
| Backend unit + H2 (`mvn -B -o -Ppostgres-it clean verify`) | **PASS**: 233 tests (119 existing, 114 new) |
| ↳ REST API, controller + H2 (`DetectionApiIntegrationTest`) | **PASS**: 66 tests covering creation, validation, model errors, details, history, results, the SSE endpoint, CORS, and OpenAPI |
| ↳ SSE service, deterministic: manual clock, explicit polls, no sleeps (`DetectionProgressStreamServiceTest`) | **PASS**: 18 tests (listed below) |
| ↳ YouTube URL canonicalisation (`YouTubeVideoUrlTest`) | **PASS**: 30 tests |
| PostgreSQL 17 Testcontainers ITs (same run) | **PASS**: 53 tests (48 existing, 5 new `DetectionApiPostgreSQLIT`: outbox persistence, disabled seed rejection, history paging/filtering/sorting with at most 2 SQL statements per page (no N+1), the completed lifecycle through details/result/SSE, and failed jobs) |
| Existing RabbitMQ messaging ITs | **PASS**: unchanged, 5 |
| Backend packaging | **PASS** |
| Python suite (no Python changes) | **PASS**: 302 passed, 5 opt-in skipped |
| `docker compose config` (example env and the user's `.env`) | **PASS**. Host ports 18080/15432 preserved |

The 18 SSE service tests cover:

- the initial snapshot, updates, and deduplication
- heartbeats
- completion, failure, and cancellation events
- disconnects, error callbacks, and timeouts
- reconnecting with the latest state
- unknown jobs
- multiple listeners sharing one query
- the connection cap
- deleted jobs, database failures, and shutdown

## Live REST + RabbitMQ + real inference (PASS)

The backend JAR, the RabbitMQ worker, PostgreSQL, RabbitMQ, and MinIO ran as separate processes. `yolo11n` was enabled with SQL in the disposable database only.

**Controlled YouTube download.** No authorized YouTube URL was available, so the worker ran through a validation-only launcher. The launcher replaced `YouTubeDownloader.download` with a stand-in that still applied the real URL validation and then copied a local 4 s clip. **No YouTube request was made.** Everything else was real: the public API submission, the outbox, RabbitMQ, YOLO11n CPU inference, FFmpeg, MinIO, events, the REST reads, and SSE.

| Observation | Result |
| --- | --- |
| `POST /api/v1/detections` (`https://youtu.be/<id>?t=3`) | 202 with `Location` and body `PENDING 0`. The worker received the canonical `https://www.youtube.com/watch?v=<id>` |
| `GET /detections/{id}` polled | `PENDING → QUEUED → DETECTING 15…77 → ENCODING 85 → COMPLETED 100` in about 18 s |
| SSE stream (`curl -N`) | `text/event-stream`, `no-store`, `X-Accel-Buffering: no`. The first event was a snapshot with `retry:3000`, followed by 12 distinct progress events and a heartbeat. The final `detection.completed` closed the stream |
| SSE reconnect after completion | Immediate `detection.completed` snapshot, then closed |
| `GET …/result` | 60 frames, `{"bus":60}`, 10,317 ms, `countSemantics` set, no storage keys |
| `GET /detections?size=5` | One job, with correct paging metadata |
| MinIO | `detected.mp4` (H.264, `yuv420p`, 60 decoded frames) and `result.json`. The bucket has no public policy and the manifest contains no local paths |
| Live errors | Disabled model 409 `MODEL_DISABLED`. Bad URL plus bad image size 400 with both field errors. Unknown job 404. Malformed UUID 400. `size=500` 400. Nothing persisted for rejected requests |
| Swagger UI / OpenAPI | `/api/v1/docs` → 302 → 200. The OpenAPI 3.1 document lists the four detection paths |

## Not run

- **Live YouTube downloading:** no authorized test URL was provided.
- **GPU inference.**
- **SSE through the Vite proxy in a browser:** the frontend belongs to Phase 07.
- **Full `docker compose up` of the user's stack:** not run, so the user's environment was left untouched.

## Defects found and fixed during validation

- **Unknown properties were silently ignored.** `@JsonIgnoreProperties(ignoreUnknown = false)` cannot override Spring Boot's global setting, so unsupported fields such as `sourceType` were accepted and discarded. The submission DTO now rejects unknown properties through a scoped `@JsonAnySetter`. It was not exploitable before, because the service always submits YouTube jobs, but the documented contract is now enforced.
- **Test-only stale reads.** Some tests modified rows with raw JDBC while the entity was still cached in the persistence context. The tests now clear the context after those updates.
