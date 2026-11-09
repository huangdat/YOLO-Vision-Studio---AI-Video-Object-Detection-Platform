# Detection REST API

Phase 06 exposes the asynchronous detection pipeline from Phase 05 over REST, with Server-Sent Events (SSE) for live progress.

- Submission goes through the existing `DetectionJobSubmissionService`, so every accepted job is written together with its transactional outbox command.
- Inference always runs in the Python worker via RabbitMQ; Spring Boot never waits for it.
- Read endpoints and SSE report job state persisted in PostgreSQL.

Interactive documentation:

- OpenAPI 3.1 document: `GET /api/v1/openapi`
- Swagger UI: `/api/v1/docs`, which redirects to `/api/v1/swagger-ui/index.html`

Both are enabled by default for development. Disable them with `API_DOCS_ENABLED=false`.

## 1. Overview

| Method | Path | Purpose | Success |
| --- | --- | --- | --- |
| POST | `/api/v1/detections` | Submit a YouTube video for detection | 202 + `Location` |
| GET | `/api/v1/detections` | Job history: paged, filtered, newest first | 200 |
| GET | `/api/v1/detections/{jobId}` | Persisted state of one job | 200 |
| GET | `/api/v1/detections/{jobId}/result` | Result metadata of a completed job | 200 |
| GET | `/api/v1/detections/{jobId}/events` | Progress stream (`text/event-stream`) | 200 stream |

Controllers never change job status. Status transitions belong to the Phase 05 lifecycle service. There is no cancellation endpoint.

## 2. Authentication and exposure

**The API has no authentication or authorization yet. Treat it as development-only.**

- Compose binds every published port to `127.0.0.1` (`BIND_ADDRESS`). Do not expose the backend to the internet.
- Anyone who can reach the API can submit jobs that consume CPU or GPU time.
- Production needs authentication, per-user authorization, rate limiting, quotas, and abuse protection first.
- Current safeguards:
  - Only single YouTube video URLs are accepted.
  - Request bodies are limited to 16 KiB (`DETECTION_API_MAX_REQUEST_BYTES`).
  - Page sizes are capped at 100.
  - Concurrent SSE streams are capped (`DETECTION_SSE_MAX_CONNECTIONS`).
  - Model enablement and preparation remain administrator actions, never API actions.

## 3. Create a detection job

`POST /api/v1/detections` with `Content-Type: application/json`:

```json
{
  "videoUrl": "https://www.youtube.com/watch?v=VIDEO_ID_11",
  "modelKey": "yolo11n",
  "confidence": 0.25,
  "imageSize": 640,
  "classes": [1, 2, 3, 5, 7]
}
```

| Field | Required | Rules | Default |
| --- | --- | --- | --- |
| `videoUrl` | yes | One YouTube video (see below) | |
| `modelKey` | yes | Registered, `DETECT` task, **enabled** (`GET /api/v1/models?enabled=true`) | |
| `confidence` | no | 0–1, at most 3 decimals | `0.25` |
| `imageSize` | no | 32–4096 and a multiple of 32 | `960` |
| `classes` | no | 1–100 unique integers 0–9999, validated against the loaded model by the worker | `[1,2,3,5,7]` (COCO bicycle, car, motorcycle, bus, truck) |

Any other property, such as `sourceType` or `source`, is rejected. The public API never accepts local paths or arbitrary URLs. Local-file jobs exist only through the development harness (`SPRING_PROFILES_ACTIVE=dev-harness`), which is not active by default.

**Accepted URL forms** match the worker's own validation, and the job stores the canonical `https://www.youtube.com/watch?v=<id>`:

- `https://www.youtube.com/watch?v=<id>`
- `https://m.youtube.com/watch?v=<id>` and `https://music.youtube.com/watch?v=<id>`
- `https://youtu.be/<id>`
- `https://www.youtube.com/shorts/<id>`
- `https://www.youtube.com/embed/<id>`

Here `<id>` is 11 characters from `[A-Za-z0-9_-]`. These are rejected:

- playlists, or any URL with a `list` parameter
- channels
- other hosts
- credentials in the URL, or a non-default port
- non-http(s) schemes

Model enablement is administrative only. It does not prove that the worker has cached the checkpoint. A worker that lacks it fails the job with `MODEL_NOT_PREPARED`.

**202 Accepted** has a `Location: /api/v1/detections/{jobId}` header:

```json
{"jobId":"596b71b1-ea62-4d75-8f34-679e3bd0b5c9","status":"PENDING","progress":0,
 "modelKey":"yolo11n","message":"Detection job accepted"}
```

`status` is the value committed with the job, normally `PENDING`. The job and its outbox command are written in one transaction, and the 202 is built inside it. Any failure before commit, such as an unavailable database (503), leaves nothing behind. A 202 always means the job was durably accepted.

## 4. Job details

`GET /api/v1/detections/{jobId}`:

```json
{"jobId":"596b71b1-…","modelKey":"yolo11n","modelVersion":"YOLO11","sourceType":"YOUTUBE_URL",
 "videoUrl":"https://www.youtube.com/watch?v=VIDEO_ID_11","status":"DETECTING","progress":65,
 "confidence":0.250,"imageSize":320,"classes":[1,2,3,5,7],
 "createdAt":"2026-11-08T11:13:21.042762Z","startedAt":"2026-11-08T11:13:28.499531Z",
 "completedAt":null,"updatedAt":"2026-11-08T11:13:35.620660Z","errorCode":null,"errorMessage":null}
```

`videoUrl` is returned only for YouTube sources; development local-file sources return `null`. `errorCode` and `errorMessage` hold the stored, sanitized worker failure. No storage keys, paths, or credentials are included.

| Status | Meaning |
| --- | --- |
| `PENDING` | Accepted; the command is not yet confirmed by RabbitMQ |
| `QUEUED` | Command confirmed; waiting for a worker |
| `DOWNLOADING` | Worker is acquiring the video |
| `DETECTING` | YOLO inference is running |
| `ENCODING` | FFmpeg is encoding the annotated video |
| `UPLOADING` | Artifacts are being stored |
| `COMPLETED` | Artifacts and result metadata are stored. `progress` is 100 |
| `FAILED` | Ended unsuccessfully. See `errorCode` (for example `VIDEO_DOWNLOAD_FAILED`, `MODEL_NOT_PREPARED`, `PROCESSING_TIMEOUT`) |
| `CANCELLED` | Terminal. Reserved; this API never cancels jobs |

Stages only move forward, progress never decreases, and terminal states never change.

## 5. Job history

`GET /api/v1/detections?page=0&size=10&status=COMPLETED&modelKey=yolo11n`

| Parameter | Default | Rules |
| --- | --- | --- |
| `page` | 0 | ≥ 0 |
| `size` | 10 | 1–100 |
| `status` | — | Any status from §4 |
| `modelKey` | — | Model key format; an unknown key returns an empty page |

Results are sorted by `createdAt` descending, then `jobId` descending for a stable order. The page is fetched with one SQL query plus a count query, with models loaded in the same query (no N+1).

```json
{"content":[{"jobId":"596b71b1-…","modelKey":"yolo11n","status":"COMPLETED","progress":100,
  "createdAt":"2026-11-08T11:13:21.042762Z","completedAt":"2026-11-08T11:13:38.874132Z","errorCode":null}],
 "page":0,"size":10,"totalElements":1,"totalPages":1}
```

## 6. Result metadata

`GET /api/v1/detections/{jobId}/result`, available once the job is `COMPLETED`:

```json
{"jobId":"596b71b1-…","status":"COMPLETED","modelKey":"yolo11n","modelVersion":"YOLO11",
 "totalFrames":60,"totalDetections":60,"processingTimeMs":10317,"detectionSummary":{"bus":60},
 "countSemantics":"BOUNDING_BOX_DETECTIONS_ACROSS_FRAMES","outputVideoAvailable":true,
 "resultMetadataAvailable":true,"createdAt":"2026-11-08T11:13:38.873066Z","completedAt":"2026-11-08T11:13:38.874132Z"}
```

- **Counts are bounding-box detections summed over all processed frames, not unique objects.** A bus visible in 60 frames counts 60 times.
- All values come from the persisted `DetectionResult`.
- Object keys and MinIO locations are not exposed. `outputVideoAvailable` only reports that an annotated-video key was recorded. The artifacts themselves are served by the Phase 09 endpoints in [video-preview-download.md](video-preview-download.md).

| Situation | Response |
| --- | --- |
| Unknown job | 404 `JOB_NOT_FOUND` |
| Job not `COMPLETED` (including `FAILED` and `CANCELLED`) | 409 `RESULT_NOT_READY`, with `jobStatus` |
| `COMPLETED` but the result row is missing (consistency error) | 500 `RESULT_UNAVAILABLE`. Logged server-side; nothing is fabricated |

## 7. Validation and errors

Every error is an RFC 9457 problem (`application/problem+json`) with a stable `code` and a `timestamp`. Field validation adds an `errors` map:

```json
{"type":"about:blank","title":"Bad Request","status":400,"detail":"Detection request validation failed.",
 "instance":"/api/v1/detections","errors":{"videoUrl":"must be a supported YouTube video URL",
 "imageSize":"must be a multiple of 32"},"code":"INVALID_DETECTION_REQUEST","timestamp":"2026-11-08T11:13:58.123Z"}
```

| HTTP | `code` | When |
| --- | --- | --- |
| 400 | `INVALID_DETECTION_REQUEST` | A submission field is invalid (see `errors`) |
| 400 | `MALFORMED_REQUEST` | Body is not valid JSON, has wrong types, or has unsupported properties |
| 400 | `VALIDATION_FAILED` | Invalid query parameters (history, model catalog) |
| 400 | `INVALID_PARAMETER` | Malformed path value, for example a job id that is not a UUID |
| 404 | `MODEL_NOT_FOUND` | Model key not registered |
| 404 | `JOB_NOT_FOUND` | Unknown job id |
| 405 / 415 | `METHOD_NOT_ALLOWED` / `UNSUPPORTED_MEDIA_TYPE` | Wrong method or content type |
| 409 | `MODEL_DISABLED` | Model registered but not enabled |
| 409 | `MODEL_NOT_SUPPORTED` | Model is not an object detection model |
| 409 | `RESULT_NOT_READY` | Result requested before successful completion |
| 413 | `PAYLOAD_TOO_LARGE` | Body larger than 16 KiB |
| 500 | `RESULT_UNAVAILABLE` | Completed job without result metadata |
| 500 | `INTERNAL_ERROR` | Unexpected error (details only in server logs) |
| 503 | `SERVICE_UNAVAILABLE` | Database unavailable; no job was accepted |
| 503 | `STREAM_CAPACITY_EXCEEDED` | Too many open SSE streams (`Retry-After: 10`) |

Responses never include SQL text, paths, credentials, stack traces, or the rejected input. The model catalog API keeps its existing responses and gains the same `code` and `timestamp` fields.

## 8. Server-Sent Events

`GET /api/v1/detections/{jobId}/events` with `Accept: text/event-stream` returns:

- `Content-Type: text/event-stream`
- `Cache-Control: no-store`
- `X-Accel-Buffering: no`, so nginx-style proxies don't buffer the stream. The Vite development proxy streams it unchanged.

| Event | When | Data |
| --- | --- | --- |
| `detection.progress` | Any non-terminal status or progress change | `{jobId, status, progress, message, errorCode: null, timestamp}` |
| `detection.completed` | Job reached `COMPLETED` | Same shape; `progress: 100` |
| `detection.failed` | Job reached `FAILED` | `errorCode` and the stored sanitized error in `message` |
| `detection.cancelled` | Job reached `CANCELLED` | Same shape |

Example from the live validation run:

```
event:detection.progress
data:{"jobId":"596b71b1-…","status":"DETECTING","progress":51,"message":"Detecting objects in video frames","errorCode":null,"timestamp":"2026-11-08T11:13:35.620660Z"}

event:detection.completed
data:{"jobId":"596b71b1-…","status":"COMPLETED","progress":100,"message":"Detection completed","errorCode":null,"timestamp":"2026-11-08T11:13:38.874673Z"}
```

How the stream behaves:

- **Source of truth.** The RabbitMQ event consumer from Phase 05 updates PostgreSQL. A single background poller (`DETECTION_SSE_POLL_INTERVAL_MS`, default 1000 ms) reads the current state of *all* watched jobs in one query per tick. There is no query per frame or per connection, and RabbitMQ consumers never wait for browsers.
- **Events.** The first event is the current snapshot, carrying a `retry: 3000` reconnect hint. After that, an event is sent only when status, progress, or error code changes. Unchanged ticks send nothing except a `:heartbeat` comment every `DETECTION_SSE_HEARTBEAT_SECONDS` (15 s).
- **Closing.** The server closes the stream after a terminal event. A stream for an already finished job sends one terminal event and closes. A deleted job closes its streams.
- **Timeouts and disconnects.** After `DETECTION_SSE_TIMEOUT_SECONDS` (30 min) the stream completes and `EventSource` reconnects automatically. A failed write (client gone) or a container error releases the slot. Shutdown completes every stream.
- **Limits.** At most `DETECTION_SSE_MAX_CONNECTIONS` (100) streams; beyond that the response is 503 `STREAM_CAPACITY_EXCEEDED`. Unknown jobs return 404 JSON before any stream opens.

## 9. Reconnection semantics

Streams carry **current state, not history**:

- Events have no `id`, and `Last-Event-ID` is not used. There is no durable event log, so missed intermediate transitions are not replayed.
- A reconnecting client immediately receives the latest snapshot, which is enough to render the current status.
- Fast transitions shorter than the poll interval may be skipped. For example, a sub-second download may appear as a jump straight to `DETECTING`.
- `GET /api/v1/detections/{jobId}` always returns the same state as the stream.

## 10. Postman

Import `http://localhost:8080/api/v1/openapi`; use your `BACKEND_PORT`, for example 18080. Postman shows SSE responses as a stream in its response viewer.

## 11. PowerShell

```powershell
$api = 'http://localhost:18080/api/v1/detections'   # use your BACKEND_PORT
$body = @{ videoUrl = 'https://www.youtube.com/watch?v=VIDEO_ID_11'; modelKey = 'yolo11n'; imageSize = 640 } |
  ConvertTo-Json
$job = Invoke-RestMethod -Method Post -Uri $api -ContentType 'application/json' -Body $body
Invoke-RestMethod "$api/$($job.jobId)"
Invoke-RestMethod "$api?status=COMPLETED&size=5"
Invoke-RestMethod "$api/$($job.jobId)/result"          # 409 RESULT_NOT_READY until COMPLETED
curl.exe -N -H "Accept: text/event-stream" "$api/$($job.jobId)/events"
```

Replace `VIDEO_ID_11` with a video you are permitted to process. A worker that can reach YouTube must be running (`ai-detection-consumer`), with the model prepared in its cache.

## 12. Example lifecycle

This lifecycle was observed during validation (see [phase-06-validation.md](phase-06-validation.md)):

1. `POST` → `202 PENDING`
2. The outbox confirms the command → `QUEUED`
3. The worker starts → `DETECTING 15 … 71`
4. `ENCODING 85`, then `UPLOADING 96`
5. `COMPLETED 100`, emitted as `detection.completed`; the stream closes
6. `GET …/result` returns 60 frames and `{"bus":60}`

## 13. Future React integration

The React integration (Phases 07 and 08) can use these endpoints as follows:

| Need | API |
| --- | --- |
| Model selector | `GET /api/v1/models?enabled=true` |
| Submit | `POST /api/v1/detections`; navigate to the `Location` |
| Live status | `new EventSource('/api/v1/detections/' + id + '/events')`, listening for the four named events. Close it on `detection.completed`, `detection.failed`, or `detection.cancelled`. On `onerror`, `EventSource` reconnects and receives a fresh snapshot |
| History | `GET /api/v1/detections?page=&size=` |
| Statistics | `GET /api/v1/detections/{id}/result`, labelling counts as frame detections |

The Vite proxy (`/api`) and the CORS configuration (now `GET`, `POST`, and `OPTIONS` for `CORS_ALLOWED_ORIGINS`) already cover these calls. No frontend changes are part of Phase 06.

## 14. Known limitations

- No authentication, ownership, or rate limiting; development use only (§2).
- SSE reports snapshots, not replayable history. Transitions faster than the poll interval may be skipped. Each backend instance polls independently, with one query per instance per tick.
- No cancellation, retry, or delete endpoints. (Video preview and download endpoints were added in Phase 09.)
- Live YouTube downloading through this API has not been validated, because no authorized test URL was available. Validation used a controlled stand-in for the downloader (see the validation report).
