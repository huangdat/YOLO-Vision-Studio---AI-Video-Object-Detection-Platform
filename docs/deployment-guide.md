# Deployment guide

This guide takes a new reader from a fresh checkout to a running YOLO Vision Studio, then through submitting a detection job and downloading its results.

> **Security boundary.** The application has **no authentication, authorization, job ownership, or rate limiting**. It is meant for a single trusted user on `localhost`, or on a trusted private network. Every host port is bound to `127.0.0.1` by default; keep it that way unless the network is trusted. Requirements for any wider deployment are listed in [§ 28](#28-production-deployment-prerequisites).

## 1. System requirements

| Resource | Minimum | Recommended |
| --- | --- | --- |
| CPU | 4 cores | 8 cores (YOLO runs on CPU by default) |
| Memory available to Docker | 6 GB | 8 GB or more |
| Disk | 15 GB free (images about 4 GB, plus volumes and the build cache) | 30 GB |
| GPU | Not required | CUDA is used only when available and `AI_DEVICE` allows it |

The default worker processes **one job at a time** (`WORKER_CONCURRENCY=1`, prefetch 1). Inference time depends on the video length, image size, and model size.

**Measured idle footprint** (Phase 10, CPU, yolo11n):

| Container | Memory |
| --- | --- |
| backend | about 0.4–0.5 GB |
| detection consumer | about 0.5 GB, plus a temporary rise during inference |
| nginx frontend | about 10 MB |

On Windows the WSL 2 VM that hosts Docker gets up to half of host memory by default. On a 14 GB host running an IDE and a browser next to CPU inference, the VM was observed to restart (see the [runbook](operations-runbook.md#docker-desktop-vm-restarted-host-ports-stop-answering)). Prefer 16 GB or more of host memory, or close heavy applications while processing videos.

## 2. Windows and Docker Desktop prerequisites

1. Windows 10/11 with WSL 2 enabled.
2. Docker Desktop with the WSL 2 engine. Under **Settings → Resources**, give Docker at least 6 GB of memory.
3. Git for Windows.
4. Leave the default ports free, or change them in `.env`: 5173, 8080, 8000, 5432, 5672, 15672, 9000, and 9001.

Linux and macOS work the same way with Docker Engine or Docker Desktop.

## 3. Required software versions

| Tool | Version | Needed for |
| --- | --- | --- |
| Docker Engine / Desktop | 24+ with Compose v2.24+ (validated: Docker 29.9.2, Compose v5.6.1) | Running the stack; the `!reset` and `!override` tags in `compose.production.yaml` |
| Java | 21 (Temurin recommended) | Building or running the backend outside Docker |
| Maven | 3.9.x (the wrapper `backend/mvnw` downloads 3.9.16) | Same |
| Node.js | `^22.22.2`, `^24.15.0`, or `>=26` (validated: 24.19.0) | Frontend development and tests |
| Python | 3.11 | Worker development and tests |
| FFmpeg | 6+ (validated: 9.0.2 on Windows; Debian's package in the image) | Worker outside Docker |

The containers include their own Java, Node.js, Python, and FFmpeg. A Docker-only deployment needs **only Docker**.

## 4. Repository setup

```powershell
git clone https://github.com/huangdat/YOLO-Vision-Studio---AI-Video-Object-Detection-Platform.git
cd YOLO-Vision-Studio---AI-Video-Object-Detection-Platform
```

## 5. Environment configuration

```powershell
Copy-Item .env.example .env
```

Edit `.env` and set the **three required passwords**, each to a different long random value. Compose refuses to start without them.

| Variable | Purpose |
| --- | --- |
| `DB_PASSWORD` | PostgreSQL password for the application user |
| `RABBITMQ_PASSWORD` | RabbitMQ user (`RABBITMQ_USERNAME`, default `yolovision`; the `guest` user is never used) |
| `MINIO_ROOT_PASSWORD` | MinIO root password, used by the backend (read-only usage) and the worker |

One way to generate a value in PowerShell:

```powershell
-join ((48..57)+(97..122) | Get-Random -Count 32 | ForEach-Object {[char]$_})
```

`.env` is git-ignored; never commit it.

Other settings to review:

| Variable | Default | Notes |
| --- | --- | --- |
| `BIND_ADDRESS` | `127.0.0.1` | Host interface for every published port. **Do not set `0.0.0.0` on an untrusted network** |
| `FRONTEND_PORT`, `BACKEND_PORT`, `AI_WORKER_PORT`, `POSTGRES_PORT`, `RABBITMQ_PORT`, `RABBITMQ_MANAGEMENT_PORT`, `MINIO_API_PORT`, `MINIO_CONSOLE_PORT` | 5173, 8080, 8000, 5432, 5672, 15672, 9000, 9001 | **Host** ports only (change these for conflicts) |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:5173` | Only needed for cross-origin API clients; the bundled UI proxies `/api` same-origin |
| `AI_DEVICE` | `auto` | `cpu`, `cuda`, or `auto` |
| `AI_MAX_VIDEO_DURATION_SECONDS` / `AI_MAX_VIDEO_SIZE_MB` / `AI_MAX_DOWNLOAD_HEIGHT` | 300 / 200 / 720 | Input limits enforced by the worker |
| `AI_MAX_INTERMEDIATE_SIZE_MB` | 4096 | Disk budget for the worker's temporary normalized input and annotated intermediate |
| `AI_PROCESSING_TIMEOUT_SECONDS` | 1800 | Upper bound for one job |
| `WORKER_CONCURRENCY` / `WORKER_PREFETCH_COUNT` | 1 / 1 | Keep these conservative on CPU |
| `WORKER_ALLOW_MODEL_DOWNLOAD` | `false` | Jobs never download weights; prepare models explicitly (§ 12) |
| `API_DOCS_ENABLED` | `true` | Swagger UI; disabled by `compose.production.yaml` |

Host ports and internal ports are different things. Inside the Compose network, services always use their internal names and ports:

| From | To (internal address) |
| --- | --- |
| frontend | `backend:8080` |
| backend | `postgres:5432`, `rabbitmq:5672`, `minio:9000` |
| ai-worker, ai-detection-consumer | `rabbitmq:5672`, `minio:9000` |

Changing a host port never requires changing these.

## 6. Docker Compose setup

There are two layouts, both bound to `127.0.0.1`:

| Layout | Command | Frontend | Published ports |
| --- | --- | --- | --- |
| **Development** (default) | `docker compose up -d --build` | Vite dev server with hot reload | All services, on localhost |
| **Self-hosted** (hardened) | `docker compose -f compose.yaml -f compose.production.yaml up -d --build` | Static build served by unprivileged nginx (CSP, no-sniff, no-frame headers; unbuffered SSE and video ranges; `backend` re-resolved through Docker DNS, so a recreated backend is found without restarting nginx; bodies over 64 KiB rejected; `/actuator` not exposed) | **Only the frontend** (`FRONTEND_PORT`, container port 8080); Swagger off |

Validate the configuration first:

```powershell
docker compose config --quiet
docker compose -f compose.yaml -f compose.production.yaml config --quiet
```

## 7. Container startup

```powershell
docker compose build            # first build takes 10–20 minutes (PyTorch CPU wheels, MinIO from source)
docker compose up -d
docker compose ps               # wait until every service is "healthy"
```

| Service | Role | Health check |
| --- | --- | --- |
| `postgres` | Job, result, and model metadata | `pg_isready` |
| `rabbitmq` | Job commands and worker events | `rabbitmq-diagnostics ping` |
| `minio` | Private artifact storage (built from the pinned upstream release) | `/minio/health/ready` |
| `backend` | Spring Boot REST, SSE, and artifact streaming | `/actuator/health/readiness` (database and broker) |
| `ai-worker` | FastAPI health service and CLI host (loads no models at startup) | `GET /health` |
| `ai-detection-consumer` | The RabbitMQ consumer that runs YOLO jobs | Heartbeat file updated while connected |
| `frontend` | UI (dev server or nginx) | HTTP `GET /` |

Startup order is enforced with `depends_on: condition: service_healthy`.

## 8. Database migration behavior

Flyway applies `backend/src/main/resources/db/migration/V1`–`V7` automatically when the backend starts, and Hibernate then validates the schema (`ddl-auto: validate`). Migrations are never edited after release; schema changes go into new versioned files. V6 seeds the 20-model catalog: YOLOv8, YOLO11, YOLO12, and YOLO26, each in sizes n/s/m/l/x, **all disabled**.

## 9. RabbitMQ setup

No manual setup is needed. The backend declares durable quorum queues for commands and events, plus a dead-letter queue; the worker declares what it consumes. The management UI is available at `http://127.0.0.1:${RABBITMQ_MANAGEMENT_PORT}` in the development layout only. Delivery is **at-least-once**; duplicates are handled idempotently (see [asynchronous-job-processing.md](asynchronous-job-processing.md)).

## 10. MinIO setup

The worker creates the `MINIO_BUCKET` bucket (default `videos`) on first upload. The bucket stays **private**: no policy is ever applied, and anonymous reads return 403. The browser never talks to MinIO; Spring Boot streams artifacts. In the development layout the console is at `http://127.0.0.1:${MINIO_CONSOLE_PORT}`.

## 11. Python worker startup

`ai-worker` and `ai-detection-consumer` start from the same image. The consumer logs `Consuming vision.detection.jobs (concurrency 1, prefetch 1)` once connected:

```powershell
docker compose logs -f ai-detection-consumer
```

## 12. Model preparation

Catalog registration is **not** runtime readiness. A model can serve jobs only when it is registered, enabled (§ 13), **and** prepared in the worker cache (the `ai-model-cache` volume).

```powershell
docker compose exec ai-detection-consumer python -m app.cli models list
docker compose exec ai-detection-consumer python -m app.cli models prepare --model yolo11n --device cpu
docker compose exec ai-detection-consumer python -m app.cli models status --model yolo11n
```

`prepare` downloads the checkpoint once, only if it is missing, then loads and verifies it. To prepare offline, copy an existing checkpoint into the volume first; `prepare` then verifies it without downloading:

```powershell
docker compose cp .\yolo11n.pt ai-detection-consumer:/data/models/yolo11n.pt
docker compose exec ai-detection-consumer python -m app.cli models prepare --model yolo11n --device cpu
```

Weights on the Windows host are **not** visible inside Docker until copied like this.

## 13. Administrative model enablement

There is intentionally **no API** to enable models, because it would be unauthenticated. Enable a model only after it is prepared:

```powershell
docker compose exec postgres psql -U yolovision -d yolovision -c "UPDATE model_configs SET enabled = TRUE, updated_at = CURRENT_TIMESTAMP WHERE model_key = 'yolo11n';"
```

Disable a model with `enabled = FALSE`. An enabled model that is not prepared fails its jobs with `MODEL_NOT_PREPARED`, and no job is ever reported as successful without real output.

## 14. Frontend access

| Layout | URL |
| --- | --- |
| Development | `http://localhost:5173` (or `FRONTEND_PORT`) |
| Self-hosted | `http://localhost:5173` (or `FRONTEND_PORT`), served by nginx |

## 15. API access

- Development: `http://localhost:8080/api/v1/...` directly, or through the frontend at `/api/v1/...`.
- Self-hosted: only through the frontend at `http://localhost:5173/api/v1/...`.

Endpoints are listed in [detection-rest-api.md](detection-rest-api.md) and [video-preview-download.md](video-preview-download.md).

## 16. Swagger UI

Development only: `http://localhost:8080/api/v1/docs` (OpenAPI JSON at `/api/v1/openapi`). It is disabled with `API_DOCS_ENABLED=false`, which `compose.production.yaml` sets.

## 17. Health checks

```powershell
docker compose ps
curl.exe -s http://localhost:8080/actuator/health/readiness   # development layout
curl.exe -s http://localhost:8000/health                       # development layout
docker compose exec backend curl -s http://localhost:8080/actuator/health/readiness   # any layout
```

Health responses never include details or credentials (`show-details: never`).

## 18. Log inspection

```powershell
docker compose logs -f backend
docker compose logs -f ai-detection-consumer
docker compose logs --since 30m backend | Select-String "<job-id>"
```

Logs carry the job ID through submission, outbox publication, worker processing, completion, and artifact access. Worker logs are JSON lines. Secrets are never logged; storage errors log only the exception type. On startup the backend logs its artifact storage endpoint and bucket, and whether credentials are configured.

## 19. Detection job submission

1. Open **Detection** in the sidebar.
2. Paste a YouTube URL for a single video you are **authorized** to process.
3. Choose an enabled model, classes, confidence, and image size.
4. Select **Start detection**.

The job page then follows progress live over Server-Sent Events.

## 20. Video preview

On a completed job's page, the **Detected video** panel plays the annotated MP4 with native controls and seeking (HTTP Range).

## 21. MP4 download

**Download detected video** saves `detection-<jobId>.mp4`. This is the exact stored file, streamed through the backend.

## 22. JSON download

**Download JSON** saves `detection-<jobId>-result.json`. This is the worker's original file. **View JSON result** shows it in the page, separately from the database statistics.

## 23. Data persistence

| Volume | Contents |
| --- | --- |
| `postgres-data` | Jobs, results, model catalog and enablement |
| `rabbitmq-data` | Queues and definitions |
| `minio-data` | Annotated videos and `result.json` files |
| `ai-model-cache` | Prepared YOLO checkpoints and verification records |
| `ai-temp-data`, `ai-output-data` | Worker scratch space (safe to lose) |

`docker compose down` keeps all volumes. **`docker compose down -v` deletes them, including all jobs, videos, and prepared models. Do not use it unless you intend to erase everything.**

## 24. Backup considerations

Back up PostgreSQL and MinIO together; a job row without its artifacts serves `ARTIFACT_NOT_FOUND`.

```powershell
docker compose exec postgres pg_dump -U yolovision -d yolovision -Fc -f /tmp/yolovision.dump
docker compose cp postgres:/tmp/yolovision.dump .\backup\yolovision.dump
docker run --rm -v yolo-vision-studio_minio-data:/data:ro -v ${PWD}\backup:/backup alpine tar czf /backup/minio-data.tgz -C /data .
```

(The volume name is `<COMPOSE_PROJECT_NAME>_minio-data`.) Restore into a stopped, empty stack. Model weights can be prepared again and need no backup.

## 25. Graceful shutdown

```powershell
docker compose stop          # or: docker compose down (keeps volumes)
```

- The backend finishes in-flight requests (graceful shutdown, up to 20 s within a 30 s stop period).
- The consumer stops taking new jobs, settles its current message, and exits within `WORKER_STOP_GRACE_PERIOD` (90 s).
- Unacknowledged jobs are redelivered after restart.

## 26. Troubleshooting

See the [operations runbook](operations-runbook.md) for symptoms, diagnostics, and safe recovery steps.

## 27. Security limitations

- No authentication, authorization, job ownership, or rate limiting. Anyone who can reach the UI can submit jobs, read every job, and download every artifact.
- The YouTube downloader fetches only validated single-video YouTube URLs. Processing third-party content may still be restricted by its terms or copyright; submit only content you are authorized to process.
- Development-layout services (PostgreSQL, RabbitMQ, the MinIO console, Swagger) are reachable from the host through localhost. Use the self-hosted layout to publish only the UI.
- TLS is not configured. Put a TLS-terminating reverse proxy in front if the UI leaves the local machine.

## 28. Production deployment prerequisites

These are **release blockers for any public or multi-user deployment**:

1. Authentication and per-user authorization, including job ownership checks in `DetectionArtifactService.resolve` and the job queries.
2. Rate limiting and quotas for submissions and artifact downloads.
3. TLS with HSTS and a hardened reverse proxy.
4. Secrets in a secret manager (not `.env`) and rotated credentials; a dedicated least-privilege MinIO user for the backend (read-only) and the worker (write) instead of the root user.
5. Monitoring and alerting, log retention, and tested backups.
6. A legal review of content download and processing.
