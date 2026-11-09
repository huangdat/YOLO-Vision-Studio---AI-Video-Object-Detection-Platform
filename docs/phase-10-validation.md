# Phase 10 validation and release readiness

Phase 10 is the final planned phase: integration testing, security hardening, and deployment readiness of the existing architecture. No features were added.

## 1. Environment

| Item | Version |
| --- | --- |
| OS | Windows 11 (host RAM 13.9 GB, 12 logical CPUs) |
| Docker | Docker Desktop 4.98.0, Engine 29.9.2, Compose v5.6.1, WSL 2 VM with 7.2 GB / 12 CPUs |
| Java / Maven | JDK 21.0.2 (host; `JAVA_HOME` set for the shell only), Temurin 21.0.13 (backend image); Maven 3.9.16 offline |
| Node.js / npm | 24.19.0 / 11.17.0 (existing IntelliJ runtime, first on `PATH` for the shell only); `node:24-alpine` in images |
| Python | 3.11.15 (`ai-worker/.venv`), `python:3.11-slim-bookworm` image |
| AI stack | Ultralytics 8.4.207, Torch 2.13.0+cpu |
| FFmpeg | 9.0.2 (host), 5.1.9 Debian package (worker image) |
| Services | PostgreSQL 17, RabbitMQ 4.2 (quorum queues), MinIO `RELEASE.2025-10-15T17-29-55Z` built from source, nginx 1.28 (unprivileged), Spring Boot 3.5.16 |

Every Docker validation ran in a **separate Compose project**, `yolo-vision-studio-p10-test`:

- test-only random credentials in an env file outside the repository, and distinct host ports;
- isolated volumes, removed afterwards with `down -v` scoped to that project;
- the user's `.env`, the `yolo-vision-studio` project, its containers, and its volumes were never used or changed.

## 2. Changes made in Phase 10

| Area | Change | Why |
| --- | --- | --- |
| Deployment | `compose.production.yaml`. The frontend is the static production build behind unprivileged nginx (CSP and security headers, unbuffered SSE and Range proxying, 64 KiB body cap, `/actuator` hidden). It publishes **only** the UI port on `BIND_ADDRESS` (127.0.0.1), removes PostgreSQL, RabbitMQ, MinIO, backend, and worker host ports, and disables Swagger | The Compose stack previously ran the Vite dev server and published every service; there was no production-style layout |
| Frontend image | Multi-stage `frontend/Dockerfile` (`production` nginx target; `dev` remains the default), `frontend/nginx.conf`, `*.tsbuildinfo` excluded from the build context | Same as above; the development flow is unchanged |
| **Fix:** nginx upstream resolution | `resolver 127.0.0.11` with a variable upstream | Found by `nginx -t`: `backend` was resolved once at startup, so a recreated backend container (new IP) would have produced 502s until nginx restarted |
| **Fix:** Vite proxy | `changeOrigin: false` (keeps `Host`) | UI requests reached the backend as cross-origin, so opening the UI as `127.0.0.1` instead of `localhost` gave 403 (seen in Phase 08). Verified: same-origin requests now pass under any local hostname, and a foreign origin is still 403 |
| **Fix:** database outage status | `CannotCreateTransactionException` mapped to `503 SERVICE_UNAVAILABLE` like `DataAccessException`, plus a test | Found live: with PostgreSQL stopped, the API returned `500 INTERNAL_ERROR` because the failure occurs when opening the transaction |
| **Fix:** RabbitMQ health check | `rabbitmq-diagnostics check_port_connectivity` instead of `ping` | Found live: `ping` turned healthy about 230 ms before the AMQP listener accepted connections, so dependents logged a spurious connection error at startup |
| **Fix:** worker error sanitization | Windows drive and UNC paths are redacted to the end of the message | Found by probing: `C:\Users\First Last\…` leaked everything after the space, and UNC paths were not redacted |
| Backend hardening | `SecurityHeadersFilter` (`nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`; no duplicate headers); graceful shutdown (`server.shutdown: graceful`, 20 s phase, 30 s Compose stop period); startup log of the artifact storage endpoint and bucket (never the secret) | Baseline hardening and operability |
| Dependencies | Pinned fixed patch or minor versions (same major lines) of Tomcat 10.1.59, PostgreSQL JDBC 42.7.12, RabbitMQ amqp-client 5.37.1, Netty 4.1.137, Jackson 2.22.3, Log4j API 2.25.5, commons-lang3 3.18.0, BouncyCastle 1.84, Guava 33.7.2, snappy-java 1.1.10.9 | OSV advisories (see § 6) |
| CI | `.github/workflows/ci.yml`: frontend, backend, Python, and integration (Testcontainers) jobs; `contents: read`; no secrets | There was no CI |
| Docs | [deployment-guide.md](deployment-guide.md), [operations-runbook.md](operations-runbook.md), this report; README and roadmap updated | Deployment and operations were undocumented |

## 3. Automated tests (final runs)

| Suite | Result | Notes |
| --- | --- | --- |
| Frontend (`vitest run`) | **PASS**: 185 passed, 0 failed, 0 skipped | Three consecutive identical runs |
| Frontend strict TypeScript (`tsc -b`) | **PASS** | |
| Frontend production build | **PASS** | 393 kB JS (123 kB gzip), 40 kB CSS |
| `npm audit` | **PASS**: 0 vulnerabilities | |
| Backend unit and H2 (`mvn -Ppostgres-it clean verify`, surefire) | **PASS**: 329 passed, 0 failed, 0 skipped | 322 baseline, plus 6 security-header tests and 1 database-outage test |
| Backend integration (same run, failsafe, Testcontainers) | **PASS**: 64 passed, 0 failed, 0 skipped | PostgreSQL 17: persistence 40, model API 3, detection API 5. RabbitMQ messaging 5. MinIO artifacts 11 |
| Backend JAR | **PASS** | Built by the same run, with all dependency pins |
| Python (`pytest`, with `IT_RABBITMQ_*`/`IT_MINIO_*` set against the isolated stack) | **PASS**: 312 passed, 0 failed, 0 skipped | 302 baseline, 5 new sanitizer tests, and the 5 broker/storage integration tests that are skipped without infrastructure (they ran against real RabbitMQ quorum queues and MinIO) |
| Python without infrastructure | **PASS**: 307 passed, 5 skipped | The configuration CI uses |
| `docker compose config` (development and production layouts, user `.env`, read-only) | **PASS** | |
| `actionlint` 1.7.7 on `ci.yml` | **PASS** | Run once from its container image; not added to the project |
| ESLint | **NOT RUN** | Not configured in this project |
| GitHub Actions remote run | **NOT VERIFIED** | The workflow is new; see § 9 |

## 4. Docker deployment (isolated project)

| Check | Result |
| --- | --- |
| Image builds | **PASS**: `backend` (Maven inside Docker, Java 21), `frontend-production` (tsc and vite build, then nginx), `ai-worker` and `ai-detection-consumer` (CPU PyTorch, FFmpeg), `minio` (from pinned source). An earlier parallel build attempt failed with a BuildKit connection EOF; the builds were rerun sequentially |
| `nginx -t` in the production image | **PASS** (after the resolver fix) |
| Images run as non-root | **PASS**: backend `yolovision`, frontend `nginx` (101), worker `worker` (10001), MinIO `minio` |
| Startup (production layout, `up --wait`) | **PASS**: all 7 services healthy |
| Published ports (production layout) | **PASS**: only `127.0.0.1:25173 → 8080` (frontend); the others have none |
| Published ports (development layout) | **PASS**: all on `127.0.0.1` |
| Flyway on empty PostgreSQL 17 | **PASS**: V1–V7 applied, schema validated, 20 models seeded (YOLOv8, YOLO11, YOLO12, YOLO26 × n/s/m/l/x), all disabled |
| RabbitMQ topology | **PASS**: `vision.detection.jobs`, `vision.detection.events.backend`, `vision.detection.dead-letter` (quorum); 1 consumer each on the jobs and events queues |
| FastAPI health | **PASS**: `{"service":"ai-worker","status":"UP"}` |
| Consumer | **PASS**: `Consuming vision.detection.jobs (concurrency 1, prefetch 1)` |
| Backend startup log | **PASS**: `Artifact storage: endpoint=http://minio:9000, bucket=videos, credentials configured` |
| Model readiness | **PASS**: `yolo11n` was `NOT_CACHED`; the cached checkpoint was copied into the isolated volume; `models prepare` verified it offline → `VERIFIED` (cpu); no download |
| Development layout (Vite) | **PASS**: UI 200, same-origin request from `127.0.0.1` reaches the backend, Swagger 200 |

## 5. End-to-end (real stack, production layout)

**Stubbed step:** the YouTube download only. The consumer ran through a test-only launcher, kept outside the repository. It applies the worker's real URL validation, then copies a local 4 s authorized fixture. **No YouTube request was made; live YouTube downloading was not tested.**

Everything else was real: the React production build behind nginx, Spring Boot, PostgreSQL, the outbox, RabbitMQ, **YOLO11n CPU inference**, FFmpeg, MinIO, events, SSE, and Chrome (headless, throwaway profile).

| Step | Result |
| --- | --- |
| Workspace | **PASS**: catalog loaded ("YOLO11 (1 enabled)"); client-side URL validation ("Only YouTube video URLs are supported."); "Ready to submit" |
| Submission | **PASS**: double click produced **one** `POST` with exactly `{videoUrl, modelKey: yolo11n, confidence 0.25, imageSize 640, classes [0,1,2,3,5,7]}` and a real job ID |
| Persistence and outbox | **PASS**: job stored; outbox command `PUBLISHED` |
| Live SSE (browser, through nginx) | **PASS**: `Pending → Detecting 20 → 41 → 61 → Encoding 85 → Completed 100`, then the player appeared; 0 console problems |
| Inference result | **PASS**: 60 frames, 4.2 s, `{bus: 60, person: 240}` detection events; one result row |
| Stored MP4 (FFprobe in the worker image) | **PASS**: MP4 with faststart, **H.264**, **yuv420p**, 640×480, 4.0 s, 60 decodable frames, 332,116 bytes |
| MinIO | **PASS**: objects at `detections/<jobId>/…`; no bucket policy; anonymous GET → 403 even inside the network; MinIO not published on the host |
| HTTP checks through nginx (18) | **PASS 18/18**: full GET SHA-256 equal (`b86cb006…`); 206 slices (first KB, middle, last byte, open-ended, suffix, clamped) byte-equal; 416 with `bytes */332116`; malformed and multi-range ignored (200); HEAD; inline and attachment filenames; `result.json` byte-identical; `/result` unchanged |
| Browser playback, desktop 1440 and mobile 390 | **PASS**: metadata 4 s; pause held; resume advanced; seek to 3.2 s landed at 3.2003 s; played to the end; sought back; decoded frame non-blank; Chrome used 206 ranges through nginx |
| MP4 and JSON downloads (browser) | **PASS**: `detection-<id>.mp4` and `detection-<id>-result.json` completed, both SHA-256 equal to the MinIO objects |
| Responsive layout (Dashboard, Workspace, History, Models, Job) at 360/390/768/1440 | **PASS**: no page overflow and no console problems (so no CSP violations) |

## 6. Security

**Verified behaviour:**

- **Production edge:**
  - security headers are sent exactly once;
  - CSP `default-src 'self'` (inline styles only), `frame-ancestors 'none'`;
  - `Server: nginx` hides its version;
  - Swagger and OpenAPI return 404, and `/actuator` returns 404;
  - a 70 KB body gets 413.
- **CORS:** a foreign-origin POST gets 403 in both layouts. A same-origin UI request works under `localhost` and `127.0.0.1`.
- **Input validation (live):** each is rejected before anything is stored:
  - a foreign host or an SSRF target (`http://minio:9000/…`);
  - a `file://` URL or a playlist;
  - an unknown model (404), a malformed model key, or a disabled model (409);
  - out-of-range confidence, image size, or classes;
  - injected `sourceType`/`source` fields (400 `MALFORMED_REQUEST`);
  - artifact requests with a malformed ID or a traversal attempt.
- **Artifacts:** keys come only from database rows; the bucket is private; no credentials appear in responses or logs (the backend logs only the storage endpoint and bucket).
- **Error messages:** problem details carry no stack traces, SQL, or paths. Worker failure messages are sanitized, now including Windows and UNC paths.
- **Credentials:** none committed. Compose requires the three passwords; RabbitMQ uses a named user, never `guest`. `VITE_` variables contain no secrets.

**Dependency scan:** OSV.dev batch lookup of the exact runtime versions of 119 Maven and 72 Python packages.

| | Findings |
| --- | --- |
| Before Phase 10 | 47 advisories in 13 packages (Tomcat, Jackson, RabbitMQ client, PostgreSQL JDBC, Netty, Log4j API, commons-lang3, BouncyCastle, Guava, snappy-java, MinIO SDK, Spring, setuptools) |
| Fixed | All with a fix in the same major line (see § 2) |
| **Remaining** | Listed below |

Remaining advisories:

| Package | Advisory | Why it remains | Exploitability here |
| --- | --- | --- | --- |
| spring-webmvc 6.2.19 | CVE-2026-47890 (SSE stream corruption when rendering view fragments) | Fixed only in Spring Framework 7.x (Spring Boot 4) | The SSE emitters send JSON data events; no fragment or view rendering is used |
| spring-webmvc 6.2.19 | CVE-2026-47884 (XsltView path) | Same | XsltView is not used |
| minio (Java) 8.5.17 | CVE-2025-59952 (XML tag value substitution) | 8.6.0 needs OkHttp 5 and Kotlin 2.x, which conflict with Spring Boot 3.5's Kotlin 1.9 | Requires a malicious S3 server; the backend talks only to the project's private MinIO on the internal network |
| bcprov-jdk18on 1.84 | CVE-2026-8763, CVE-2026-13506 | Fixed only in 2.x | Pulled in by the MinIO SDK; certificate name constraints and ASN.1 parsing are not used (plain HTTP inside the network) |
| setuptools 78.1.0 | CVE-2025-47273 and others | A build tool in the local development venv, not a worker runtime dependency | Not used at runtime |

`httpx2==2.16.0` in `requirements-dev.txt` was checked for typosquatting. It is the official `pydantic/httpx2` package, which Starlette 1.10's TestClient imports.

**Public-deployment blockers (unchanged by design; out of Phase 10 scope):**

- no authentication;
- no authorization or job ownership (anyone who can reach the UI can read every job and download every artifact);
- no rate limiting or quotas;
- no TLS;
- root MinIO credentials shared by the backend and worker;
- no secret manager, monitoring, or alerting;
- no legal review of third-party video processing.

See [deployment-guide.md § 28](deployment-guide.md#28-production-deployment-prerequisites).

## 7. Reliability and failure tests (isolated stack)

| Scenario | Result |
| --- | --- |
| Model enabled but not prepared (`yolo26s`) | **PASS**: job `FAILED` with `MODEL_NOT_PREPARED` and the exact `prepare` command; no result row; artifact endpoints 409 `RESULT_NOT_READY` |
| Worker graceful stop mid-job (`restart -t 30`) | **PASS**: the in-flight job finished before exit (drain); 1 result row |
| **Worker `SIGKILL` mid-job** | **PASS**: the command returned to the queue (1 ready, 0 consumers); the job stayed honestly at `DETECTING 15`; after restart it was reprocessed with monotonic progress to `COMPLETED`; **exactly 1** result row; dead-letter queue empty |
| **RabbitMQ down at submission** | **PASS**: `202` accepted, job `PENDING`, outbox `last_error = Broker unavailable: AmqpIOException`; after restart published on attempt 3 → `COMPLETED`, 1 result row |
| RabbitMQ recreated during a live UI job | **PASS**: outbox `AmqpConnectException` ×3 with 2/4/8 s backoff, published on attempt 4; the job completed and the UI showed it |
| MinIO down | **PASS**: `/video`, `/video/download`, `/result.json` → `503 STORAGE_UNAVAILABLE` with `Retry-After: 10`, no internals; `/result` metadata still 200; recovery automatic (206 after restart) |
| PostgreSQL down | **PASS after fix**: initially 500 `INTERNAL_ERROR` (defect); now 503 `SERVICE_UNAVAILABLE` for job, result, and history; readiness `DOWN`; full recovery after restart |
| **Unplanned Docker VM restart during inference** | **PASS (recovery)**: the WSL 2 VM hosting Docker exited (see § 8); after Docker restarted the containers, the in-flight job was redelivered and **completed by itself** |
| SSE interruption in the browser | **PASS**: during that VM restart the UI showed "Reconnecting to live updates…", then "Live updates unavailable; checking every few seconds" (polling fallback) and never claimed completion |
| Duplicate commands and completion events | **PASS** (automated): covered by the existing messaging and lifecycle tests and the Python broker ITs (redelivery, dead-lettering) that ran against real RabbitMQ |
| Client disconnects during video download | **PASS**: 10 downloads aborted after 4 KiB through nginx; the server kept serving exact ranges; no errors logged |
| Multiple SSE listeners | **PASS**: 20 concurrent listeners each received `detection.completed` and closed |
| Lightweight load | **PASS**: 100 sequential requests each to the catalog, history, and result: median about 9 ms, p95 about 32 ms (through nginx, warm) |
| Resource use | **PASS**: backend 406 → 478 MiB and 68 → 84 → 80 threads during and after the smoke test (pool growth, then settling); consumer about 0.5 GB idle; nginx about 10 MB |

**Delivery semantics:** commands and events are **at-least-once**, made safe by job-scoped artifact keys, idempotent completion handling, and monotonic status. Exactly-once execution is not claimed.

## 8. Environment incidents (not application defects)

- **Docker Desktop VM restart.** At 05:32:36 UTC the WSL 2 VM hosting Docker exited during CPU inference (`guest exited`, multiplexer offline in the Docker Desktop logs; a new VM log started at 05:32:50). The host had 2.1 GB of free RAM of 13.9 GB, with an IDE and a browser running. Windows logged no explicit resource-exhaustion event, so host memory pressure is the most likely cause but is not proven.
- **Consequences:**
  - all containers restarted (restart count 0);
  - Docker Desktop's host port forwarding stayed stale (empty replies) until the published service was recreated;
  - `docker logs` for the restarted containers became partially unreadable;
  - the consumer's post-restart log could not be retrieved, so the worker-side "MOCKED DOWNLOAD" marker for the final job was evidenced indirectly (fixture-identical 60-frame 640×480 4 s output).
- **Documentation:** the runbook gained an incident entry with safe recovery, and the deployment guide gained memory guidance.
- **BuildKit:** an earlier parallel image build lost its connection to BuildKit (`rpc error … EOF`); sequential builds succeeded.

## 9. CI

- **Workflow:** `.github/workflows/ci.yml`, triggered by pushes to `main`, pull requests, and manual dispatch.
  - **frontend:** Node 24, `npm ci`, tests, build with strict TypeScript.
  - **backend:** Temurin 21, `./mvnw -B verify`.
  - **python:** Python 3.11, FFmpeg, CPU Torch, pytest; infrastructure ITs skip.
  - **integration:** builds the pinned MinIO image, then `./mvnw -B -Ppostgres-it verify`.
- **Permissions and limits:** `contents: read` only; no secrets; no YouTube downloads; no YOLO weights.
- **Local validation:** `actionlint` passes, and every command it runs passed locally (§ 3).
- **Remote status:** **NOT VERIFIED** at the time of writing. The first remote run starts when this commit is pushed; a successful local run does not prove the remote one.

## 10. Release readiness

| Area | Status | Evidence |
| --- | --- | --- |
| Functional completeness (Phases 01–09) | ✅ | § 5 E2E |
| Regression tests | ✅ | § 3: 185 + 329 + 64 + 312, 0 failures |
| Build reproducibility | ✅ | Docker images and JAR built; lockfiles respected |
| Docker startup | ✅ | § 4, both layouts healthy |
| Database migrations | ✅ | V1–V7 on empty PostgreSQL 17 + Testcontainers ITs |
| RabbitMQ functionality | ✅ | E2E, outages, SIGKILL redelivery, Python broker ITs |
| MinIO storage | ✅ | Private bucket, byte-exact artifacts, outage handling |
| Model preparation | ✅ | Offline `prepare` → VERIFIED; `MODEL_NOT_PREPARED` path |
| Media playback and download integrity | ✅ | Browser playback and seek; SHA-256 equality |
| Logging | ✅ | Job IDs across outbox, lifecycle, and artifacts; no secrets; storage target logged |
| Documentation | ✅ | Deployment guide, runbook, this report |
| Security defaults | ✅ local / ❌ public | Localhost-only, hardened edge; no authentication (§ 6) |
| Operational recovery | ✅ | § 7 |
| CI | ⚠️ | Defined and locally validated; remote run not yet verified |

**Classification: READY FOR CONTROLLED SELF-HOSTED USE.** This covers a single trusted user or a trusted private network, using `compose.production.yaml` on a localhost or private bind, which also covers local demos.

Every required automated, integration, end-to-end, browser, security, and failure check passed on the real stack after the fixes above. The application is **not ready for public or multi-user Internet deployment**: authentication, authorization and job ownership, rate limiting, and TLS are release blockers for that.

## 11. Known limitations

- Live YouTube downloading was not tested (stubbed download step).
- Headless Chrome only; other browsers and physical devices were not tested.
- The remote GitHub Actions run was not verified before pushing.
- Docker Desktop on hosts with about 14 GB of RAM can restart its VM under combined load (§ 8).
- Multi-range HTTP requests return the full body; `result.json` is capped at 2 MiB (by design, Phase 09).
- The five remaining dependency advisories need major upgrades (§ 6).
- No load or soak testing beyond the lightweight smoke test; GPU inference was not tested.
