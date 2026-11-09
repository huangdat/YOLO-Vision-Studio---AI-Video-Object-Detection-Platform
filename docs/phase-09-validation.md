# Phase 09 validation

## Environment

- **Platform:** Windows 11.
- **Backend:** JDK 21.0.2 (`C:\Program Files\Java\jdk-21`) and Maven 3.9.16, run offline. The default `java` on `PATH` is 22, so JDK 21 was set for the validation shell only.
- **Frontend:** Node v24.19.0 / npm 11.17.0, the runtime bundled with IntelliJ IDEA, also used in Phases 07–08. It was placed first on `PATH` for the shell only, and nothing was installed. The system Node (v22.14.0) is unchanged.
- **Worker:** the existing `ai-worker/.venv` on CPU, with FFmpeg/FFprobe 9.0.2 (`D:\Tools\ffmpeg`) and the cached `yolo11n.pt`. No weights were downloaded.
- **Infrastructure:**
  - Disposable PostgreSQL 17, RabbitMQ 4.2, and MinIO containers (the project's pinned `yolo-vision-studio-minio` image), on unused ports with random credentials, all removed afterwards.
  - `yolo11n` was enabled in the disposable database only.
  - The user's `.env`, Compose containers, volumes, and ports 18080/15432 were not used or changed.
- **Browser:** headless Chrome with a throwaway profile, driven over the DevTools protocol.

## Dependency change

Backend `io.minio:minio:8.5.17`, for read-only access to the private bucket. 8.5.x uses OkHttp 4.12, which works with the Kotlin 1.9.25 managed by Spring Boot 3.5; 8.6.0's OkHttp 5 would require overriding that version. No frontend dependencies changed (`package.json` and the lockfile are untouched).

## Automated checks

| Check | Result |
| --- | --- |
| Backend unit + H2 (`mvn -o -Ppostgres-it clean verify`, surefire) | **PASS**: 322 tests (233 existing, 89 new) |
| Backend Testcontainers ITs (same run, failsafe) | **PASS**: 64 tests (53 existing, 11 new MinIO) |
| ↳ PostgreSQL ITs (persistence, model API, detection API, messaging with RabbitMQ) | **PASS**: 40 + 3 + 5 + 5 |
| ↳ `DetectionArtifactMinioIT` (real MinIO + PostgreSQL 17) | **PASS**: 11 |
| Backend JAR (`backend-1.0.0.jar`) | **PASS**: built by the same run |
| Frontend `npm test` (`vitest run`) | **PASS**: 185 tests in 16 files (163 existing, 22 new); 3 consecutive identical runs |
| Strict TypeScript (`tsc -b`) | **PASS** |
| Production build (`npm run build`) | **PASS**: 393 kB JS (123 kB gzip), 40 kB CSS |
| `docker compose config` (the user's `.env`, read-only) | **PASS**. The backend already receives `MINIO_ENDPOINT/ACCESS_KEY/SECRET_KEY/BUCKET`; ports 18080/15432 preserved; `compose.yaml` unchanged |
| ESLint | **NOT RUN**: not configured in this project |
| Python suite | **NOT RE-RUN**: no worker code changed |

New backend tests:

| Class | Tests | Covers |
| --- | --- | --- |
| `ByteRangeTest` | 27 | First, middle, and last byte; open-ended; suffix; beyond-end clamping; 416 cases; malformed, non-bytes, and multi-range input ignored; `If-Range` |
| `DetectionArtifactApiIntegrationTest` | 55 | Exact headers and bytes; slices plus the exact window opened in storage and its closing; 416; HEAD; download; every error code; key ownership; legacy rows; `result.json` validation (malformed, array, trailing content, other job, paths, secrets, non-UTF-8, inert HTML); unchanged `/result`; abort after commit |
| `DetectionArtifactHttpTransferTest` | 4 | Real Tomcat: 8 MiB byte-exact transfers; mid-transfer storage failure gives the client an `IOException`; a client disconnect releases the storage stream; problem+json for `Accept: video/mp4` |
| `MinioObjectStorageTest` | 3 | Missing secret or unreachable endpoint gives a client-safe 503; the secret is masked |
| `DetectionArtifactMinioIT` | 11 | Real MinIO: SHA-256-equal stream and download, six range slices, 416, `result.json` identity, missing object 404, anonymous access 403 |

New frontend tests: `api/artifacts.test.ts` (7) and `pages/DetectionResultMedia.test.tsx` (15). They cover:

- relative URLs
- text-only result handling and problem-code parsing
- the one-byte probe
- no player or downloads while processing or for failed jobs
- player attributes (no autoplay) and loading state
- downloads
- no recorded video
- missing video (no retry, MP4 link removed)
- storage outage with retry that does not touch the job
- network and decode errors
- live completion without a second `EventSource`
- JSON viewer: on-demand loading, escaped HTML, error and retry, malformed data, copying, absent `result.json`

### Existing tests changed deliberately

- `DetectionDetails.test.tsx`, completion test: two assertions expected the Phase 07 note "Video preview and download will be available in a future phase" and *no* download links. This phase replaces exactly that, so they now assert the player source and the download link.
- **Latent test race fixed (timing only).** Three page tests counted or grabbed `FakeEventSource` synchronously right after `findByText`, but the stream opens in a passive React effect. Under the heavier 16-file parallel run this intermittently failed (twice in about ten runs) in Phase 07/08 tests that passed in isolation five times. They now `await waitFor(...)` for the stream; no assertion was weakened or removed.

## Live end-to-end (real components; mocked YouTube download)

**Mocked download.** No authorized YouTube video was available. The worker ran through the validation-only launcher from Phase 06, which applies the real URL validation and copies a local 4 s fixture. **No request to YouTube was made, and live YouTube downloading was not tested.**

Everything else was real:

- **Real YOLO inference:** YOLO11n on CPU (240 person and 60 bus detection events over 60 frames).
- **Real FFmpeg encoding.**
- **Real MinIO storage.**
- **Real Spring Boot streaming:** the Phase 09 JAR.
- **Real browser playback:** Chrome, against both the Vite dev server and the **production build** (`vite preview`).

| Check | Result |
| --- | --- |
| Stored object (FFprobe) | **PASS**: MP4 (`ftyp isom`, `moov` immediately after, so faststart), H.264, `yuv420p`, 640×480, 4.0 s, 60 decodable frames, 332,437 bytes |
| Bucket privacy | **PASS**: no bucket policy (`NoSuchBucketPolicy`); anonymous GET of the object → 403 |
| HTTP checks against the stored object (18, via the production preview proxy **and** directly on Spring Boot) | **PASS** 18/18 on both paths. Full GET SHA-256 equal (`43ff56a2…`); inline/attachment dispositions; 206 slices for `0-1023`, `100000-199999`, last byte, `300000-`, `-2048`, `330000-9999999` byte-equal; 416 for `bytes=size-` and `bytes=-0` with `bytes */332437`; malformed and multi-range → 200 full; HEAD; `result.json` byte-identical; `/result` unchanged with no keys exposed |
| Browser: metadata | **PASS**: duration 4.0 s, 640×480, loading indicator cleared |
| Browser: play / pause / resume | **PASS**: playing at 1.21 s; paused and held; resumed and advanced to 1.92 s |
| Browser: seek | **PASS**: seek to 3.2 s landed at 3.2004 s (readyState 4) and Chrome issued a mid-file `206 bytes 229376-332436/332437`. It played to `ended`, sought back, and drew a non-blank decoded frame |
| Browser: MP4 download | **PASS**: suggested name `detection-<jobId>.mp4`, completed, SHA-256 equal to the stored object |
| Browser: JSON viewer | **PASS**: shows the stored JSON (jobId, `{bus: 60, person: 240}`, 60 frames) |
| Browser: JSON download | **PASS**: `detection-<jobId>-result.json`, SHA-256 equal to the stored object |
| Live completion | **PASS**: while processing (Detecting 66 → Encoding 85) there was no player and no downloads; after the SSE completion event the player and both downloads appeared without a reload |
| Missing MP4 (deleted from disposable MinIO for a test-owned job) | **PASS**: "The detected video is missing", no retry, no `<video>`, the MP4 download removed, statistics and JSON download kept |
| Storage outage (disposable MinIO stopped) | **PASS**: 503 → "Video storage is temporarily unavailable" with *Retry playback*; statistics kept; the JSON viewer shows its own error with *Try again* |
| Console | **PASS**: no errors except the deliberate 404 and 503 responses in the two failure scenarios |
| Logs | **PASS**: the MinIO secret appears in neither backend nor worker logs; storage failures log only the exception type |

Responsive layout, production build:

| Viewport | Result |
| --- | --- |
| Job page 360, 390, 768, 1440 | **PASS**: no page overflow |
| JSON viewer open at 360 | **PASS**: 555 px of JSON scrolls inside a 292 px box; the page stays at 360; downloads go full width |
| Mobile playback at 390 | **PASS**: play, pause, resume, seek (3.2002 s), end, both downloads |
| Dashboard, History, Workspace, Models at 390 | **PASS**: no page overflow; tables still scroll in their own container (Phase 07 fix intact) |

## Interrupted session and process failures

The first validation session was interrupted. Five background processes reported exit code 4 (Vite preview, Vite dev, Spring Boot, the worker, and headless Chrome). Investigation showed:

- every log ended with normal activity and none contained an application error or shutdown;
- all five reported the identical code at the same moment;
- the `--rm` disposable containers had disappeared;
- Windows reported a new boot (2026-11-09 01:37), and Docker's event history had restarted.

The processes were terminated externally by the interrupted session and host restart; these were **not application failures**. The stack was started again one service at a time, each verified before the next, using a fresh completed job. The validation then completed as recorded above.

A cleanup command for an old download folder was blocked by a safety check and was not retried. That scratch folder (outside the repository) was left untouched, and fresh folders were used instead.

## Cleanup

Removed after validation:

- disposable containers (Testcontainers' own were reaped automatically)
- backend, worker, preview, and Chrome processes
- the empty `ai-worker/temp/p09-work`

Only the user's own (stopped) Compose containers remain. Scripts and logs stay in the session scratch directory outside the repository.

## Not run

- **Live YouTube downloading:** intentionally not performed (see above).
- **Other browsers and physical devices:** not available. Only Chrome (headless) and device emulation were used.
- **Docker Compose frontend/backend containers:** images unchanged in structure; validation used the JAR, `vite`, and `vite preview` against disposable infrastructure.
- **Very large videos:** memory efficiency is shown by the chunked design, the 8 MiB real-Tomcat test, and the storage-window assertions, not by a multi-GB run.
