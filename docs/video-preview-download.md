# Detection video preview, streaming, and downloads (Phase 09)

Completed jobs expose two artifacts written by the AI worker:

- the annotated MP4 (H.264, `yuv420p`, faststart, no audio)
- the worker's original `result.json`

Spring Boot serves both from the private MinIO bucket. The browser never talks to MinIO. It never receives object keys, bucket names, storage URLs, or credentials.

> **Development only.** These endpoints are for local development until authentication, authorization, rate limiting, and job ownership checks exist. Do not deploy them publicly without those protections. The default bind address remains `127.0.0.1`.

## 1. Media delivery architecture

```
<video> / download link / JSON viewer (React, same origin, relative /api/v1 URLs)
        │  GET /api/v1/detections/{jobId}/video   (Range: bytes=…)
        ▼
Spring Boot  DetectionArtifactController
        │  1. UUID path variable (400 otherwise)
        │  2. job exists (404) and is COMPLETED (409)
        │  3. detection_results row exists (500 RESULT_UNAVAILABLE otherwise)
        │  4. object key from that row only; must end with /<jobId>/detected.mp4 (or result.json)
        │  5. stat the object: exists (404) and is non-empty
        │  6. resolve the Range, then open exactly that byte window
        ▼
MinIO (private bucket, ranged GET via the MinIO Java SDK)
        │  bytes
        ▼
Spring Boot → 200 / 206 → browser
```

Steps 1–6 all finish before any response header is written. Every failure up to that point is therefore an RFC 9457 `application/problem+json` response, even for `Accept: video/mp4` requests.

The pieces:

| Component | Role |
| --- | --- |
| `storage/ObjectStorage`, `storage/MinioObjectStorage` | Read-only `stat` and ranged `open`. The client is created lazily, so the backend starts without storage. Nothing writes, lists, deletes, or changes bucket policy |
| `service/DetectionArtifactService` | Job, status, and result checks; key ownership check; object stat; bounded `result.json` validation |
| `service/ByteRange` | Pure `Range`/`If-Range` resolution (RFC 9110) |
| `controller/DetectionArtifactController` | Headers, status, and a bounded 64 KiB copy loop |
| `config/ObjectStorageProperties` | The same `MINIO_*` variables the worker uses |

No database migration was needed. Existing `detection_results.output_video_key` and `result_json_key` values are reused, so older completed jobs work as long as their objects exist.

## 2. Private MinIO access

| Variable | Default | Notes |
| --- | --- | --- |
| `MINIO_ENDPOINT` | `http://localhost:9000` | Compose: `http://minio:9000` |
| `MINIO_ACCESS_KEY` | `yolovision` | |
| `MINIO_SECRET_KEY` | *(empty)* | Without it, artifact requests answer 503; the rest of the API works |
| `MINIO_BUCKET` | `videos` | |
| `MINIO_REGION` | *(empty)* | |
| `MINIO_CONNECT_TIMEOUT` / `MINIO_READ_TIMEOUT` | `5s` / `30s` | |

Compose already passes these variables to the backend through the shared messaging anchor, so `compose.yaml` is unchanged.

The bucket stays private. No policy is applied, and an anonymous GET is refused with 403 (verified live). The secret is never logged: `ObjectStorageProperties.toString()` masks it, and storage failures log only the exception type.

## 3. Endpoints

| Method and path | Purpose | Success |
| --- | --- | --- |
| `GET`/`HEAD /api/v1/detections/{jobId}/video` | Inline MP4 for `<video>` | 200 or 206, `Content-Disposition: inline; filename="detection-<jobId>.mp4"` |
| `GET`/`HEAD …/video/download` | Same bytes as an attachment | 200 or 206, `attachment; filename="detection-<jobId>.mp4"` |
| `GET …/result.json` | The worker's original `result.json` | 200, `application/json`, `inline; filename="detection-<jobId>-result.json"` |
| `GET …/result.json/download` | Same bytes as an attachment | 200, `attachment; filename="detection-<jobId>-result.json"` |

The existing `GET …/result` metadata endpoint, read from PostgreSQL, is **unchanged**. Its DTO and the raw `result.json` are different representations; the UI labels them separately.

Common video response headers:

- `Content-Type: video/mp4`, a fixed per-artifact type that is never taken from storage metadata
- `Content-Length` from the real object size
- `Accept-Ranges: bytes`
- `ETag` from storage
- `Cache-Control: no-store`
- `X-Content-Type-Options: nosniff`

Filenames are generated from the canonical UUID only, so there is no header injection and no client-supplied name.

`HEAD` returns the same headers without opening the object.

## 4. HTTP Range requests

Exactly one byte range is supported:

| Request | Response |
| --- | --- |
| No `Range` | 200, full body |
| `bytes=0-1023`, `bytes=5000-5999`, `bytes=N-N` (last byte) | 206, `Content-Range: bytes a-b/size`, exact slice |
| `bytes=1024-` (open-ended) | 206 to the last byte |
| `bytes=-2048` (suffix) | 206, the last 2048 bytes (the whole object if larger) |
| `bytes=9000-999999` (end beyond size) | 206, end clamped to `size-1` |
| `bytes=size-`, `bytes=-0` | **416**, `Content-Range: bytes */size`, problem `RANGE_NOT_SATISFIABLE` |
| Malformed (`bytes=abc`, `bytes=20-10`, other units) | Range ignored: 200 with the full body (RFC 9110 permits this) |
| Multiple ranges (`bytes=0-10,20-30`) | Ignored: 200 with the full body. **multipart/byteranges is not implemented** and never claimed |
| `If-Range` not equal to the current strong ETag | Full body (200) |

The backend asks MinIO for only the requested window (ranged GET with offset and length), so unrelated bytes are never read.

## 5. Streaming efficiency and resource handling

- Bytes are copied from the storage stream to the servlet output in **64 KiB chunks**, so the video is never held in memory. The storage stream is closed by try-with-resources on completion, after a range ends, on a client disconnect, and on errors.
- **Client disconnect:** the write fails, the transfer stops quietly (debug log), and the stream is closed. A real-Tomcat test shows the storage stream is released and the server keeps serving.
- **Storage failure after the headers were sent:** the status can no longer change. `ArtifactTransferException` is propagated to the servlet container, which aborts the connection. The client sees an incomplete transfer, never a short body reported as success (verified on real Tomcat: the Java client receives an `IOException`).
- No transcoding: Spring Boot never runs FFmpeg and streams the stored bytes unchanged. Live SHA-256 checks confirm this.
- The `result.json` endpoints are the one bounded exception. The manifest is read fully, up to **2 MiB** (larger files are refused), because it is validated before serving.

## 6. `result.json` validation

The original bytes are returned unchanged only if they:

- are within the size limit;
- are valid UTF-8 and one JSON **object** with no trailing content;
- carry `jobId` equal to the requested job, when present;
- contain no field names that look like credentials (`password`, `secret`, `token`, `credential`, `accessKey`, `privateKey`);
- contain no string values that look like absolute filesystem paths (`/…`, `C:\…`, `\\…`).

Otherwise the response is `500 ARTIFACT_INVALID` and the reason is logged server-side.

The current worker manifest drops its only path field (`output`) and passes these checks. They guard against legacy or foreign files.

## 7. Error handling

| Situation | Status | `code` |
| --- | --- | --- |
| Malformed job ID | 400 | `INVALID_PARAMETER` |
| Unknown job | 404 | `JOB_NOT_FOUND` |
| Job not completed, failed, or cancelled | 409 | `RESULT_NOT_READY` (with `jobStatus`) |
| Completed job without a result row | 500 | `RESULT_UNAVAILABLE` |
| Key not recorded, not this job's artifact, object missing, or empty | 404 | `ARTIFACT_NOT_FOUND` (fixed message; the reason is logged) |
| Unsafe or malformed `result.json` | 500 | `ARTIFACT_INVALID` |
| Range starts at or beyond the size | 416 | `RANGE_NOT_SATISFIABLE` |
| MinIO unreachable, misconfigured, or secret missing | 503 + `Retry-After: 10` | `STORAGE_UNAVAILABLE` |
| Anything else before streaming | 500 | `INTERNAL_ERROR` |

Problem bodies never contain object keys, bucket names, endpoints, SQL, paths, or stack traces.

## 8. React integration

The job details page (`/detections/:jobId`) adds two sections for **completed** jobs only.

**Detected video** (`components/results/DetectionVideoPlayer.tsx`):

- a native `<video controls preload="metadata" playsInline>` labelled "Annotated detection video", with no autoplay
- the source is the relative `/api/v1/detections/{id}/video`, so it works through the Vite proxy, `vite preview`, and any same-origin deployment
- states: *Loading video…*, ready (showing the real duration), and error

When playback fails, a one-byte probe (`Range: bytes=0-0`) reads the backend's problem code without downloading the video again:

| Probe result | What the user sees |
| --- | --- |
| `ARTIFACT_NOT_FOUND` | "The detected video is missing". No retry, and the MP4 download is removed |
| `STORAGE_UNAVAILABLE` | Explanation and *Retry playback* |
| Probe succeeds | A network or decode explanation and *Retry playback*. The download stays |

Retrying only reloads the media element; it never touches or resubmits the job.

**Downloads:** *Download detected video* and *Download JSON* are ordinary same-origin links with `download`, and the server's `Content-Disposition` names the file. No Blob, base64, or in-memory copy is made. The MP4 link is shown only when the metadata records a video and it is not known to be missing. The JSON link appears only when a `result.json` key is recorded.

**Result JSON** (`components/results/ResultJsonViewer.tsx`):

- collapsed by default and loaded on demand as text through the shared Axios client
- parsed, then shown re-indented in an escaped `<pre>` with no `dangerouslySetInnerHTML`, so embedded HTML stays inert
- offers *Copy JSON*, and loading and error states with a retry
- labelled as the raw worker file, distinct from the statistics above it

Jobs that are still processing show only the existing progress UI, and failed jobs keep their failure details. Neither offers media or downloads. The page keeps the single existing `EventSource`; when a job completes live, the media appears without a reload. History and Dashboard are unchanged and never request artifacts.

## 9. Testing

| Suite | Scope |
| --- | --- |
| `ByteRangeTest` (27) | Every range form, 416, malformed and multi-range input, `If-Range` |
| `DetectionArtifactApiIntegrationTest` (55, H2 + MockMvc + in-memory storage) | Headers, exact bytes and slices, the opened window and stream closing, every error code, key ownership, legacy rows without a JSON key, `result.json` validation, HTML inside JSON, the unchanged metadata endpoint, abort after commit |
| `DetectionArtifactHttpTransferTest` (4, real embedded Tomcat) | Byte-exact full and ranged transfers, mid-transfer storage failure visible to the client, client disconnect releasing the stream, problem+json for `Accept: video/mp4`, 416 |
| `MinioObjectStorageTest` (3) | Missing secret and unreachable endpoint map to a client-safe 503; the secret never appears in `toString` |
| `DetectionArtifactMinioIT` (11, **real MinIO + PostgreSQL 17** via Testcontainers) | SHA-256-equal stream and download, six exact range slices, 416, `result.json` identity, missing object, anonymous access refused (bucket private) |
| Frontend `artifacts.test.ts` (7) and `DetectionResultMedia.test.tsx` (15) | URLs, text handling, probe, player states and retry, downloads, JSON viewer safety, no extra `EventSource` |

Run them:

```powershell
# Backend (JDK 21). The MinIO IT uses the project's pinned image: build it once with
#   docker compose build minio   (or pass -Dminio.it.image=<image>)
cd backend; mvn -Ppostgres-it clean verify
# Frontend (Node ^22.22.2 || ^24.15.0 || >=26)
cd frontend; npm test; npm run build
```

Executed results are recorded in [phase-09-validation.md](phase-09-validation.md).

## 10. Local development

```powershell
$env:MINIO_ENDPOINT = "http://localhost:9000"; $env:MINIO_SECRET_KEY = "<local MinIO password>"
cd backend; mvn spring-boot:run
cd frontend; $env:VITE_PROXY_TARGET = "http://localhost:8080"; npm run dev
```

Open a completed job from *History*. The player, downloads, and JSON viewer appear when the job is `COMPLETED`.

## 11. Docker development

`docker compose up` needs no changes: the backend receives `MINIO_ENDPOINT=http://minio:9000`, the root credentials, and `MINIO_BUCKET` from `.env`. The frontend container proxies `/api` to the backend, so media URLs remain same-origin.

## 12. Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| 503 `STORAGE_UNAVAILABLE` | MinIO is down, `MINIO_ENDPOINT` is wrong, or `MINIO_SECRET_KEY` is unset in the backend environment |
| 404 `ARTIFACT_NOT_FOUND` on an old job | The object was deleted, or the stored key does not name that job's artifact. Check the backend log for the reason |
| 409 `RESULT_NOT_READY` | The job has not completed (or failed); wait for `COMPLETED` |
| Player shows "could not play" while download works | The browser cannot decode the file; the worker output is H.264/`yuv420p`, which mainstream browsers support |
| Seeking jumps back to the start through a custom proxy | The proxy strips `Range` or rewrites `206`; the Vite dev and preview proxies forward them correctly |

## 13. Future authentication integration

All access goes through `DetectionArtifactService.resolve(jobId, artifact)`. A future ownership or authorization check belongs there, before any storage call. Rate limiting and authentication belong in front of the `/api/v1/detections/{id}/…` routes. Short-lived signed URLs could replace backend streaming later, but they are deliberately not used now.
