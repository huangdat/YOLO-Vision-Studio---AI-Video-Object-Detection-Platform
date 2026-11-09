# Operations runbook

Each incident lists its symptoms, the commands to diagnose it, the likely causes, and safe recovery steps. Commands assume the repository root and the default project name. Add `-f compose.yaml -f compose.production.yaml` when running the self-hosted layout.

> **Data-safety rules.**
> - `docker compose down` and `docker compose restart <service>` are safe; volumes survive.
> - **`docker compose down -v`, `docker volume rm`, `docker system prune --volumes`, and deleting MinIO objects destroy jobs, videos, or prepared models.** Use them only to erase data deliberately, after a backup ([deployment-guide.md § 24](deployment-guide.md#24-backup-considerations)).
> - Never edit applied Flyway migrations.

Useful everywhere:

```powershell
docker compose ps
docker compose logs --since 15m <service>
docker compose exec postgres psql -U yolovision -d yolovision -c "SELECT id, status, progress, error_code, updated_at FROM detection_jobs ORDER BY created_at DESC LIMIT 10;"
```

---

## Docker Desktop unavailable

- **Symptoms:** `error during connect` or `The system cannot find the file specified` from any `docker` command.
- **Diagnose:** `docker info`, and check the Docker Desktop tray icon. `wsl --status`.
- **Causes:** Docker Desktop not started, the WSL 2 backend stopped, or a host restart.
- **Recover:** start Docker Desktop and wait for "Engine running", then `docker compose up -d`. Containers with `restart: unless-stopped` come back on their own; volumes are untouched.

## Docker Desktop VM restarted; host ports stop answering

Observed during Phase 10 validation on a 13.9 GB Windows host running CPU inference, a browser, and an IDE at once.

- **Symptoms:**
  - Every container shows a new start time, but the restart count stays 0.
  - The UI briefly shows "Reconnecting to live updates…".
  - Afterwards, browser or `curl` requests to a published port fail with an empty reply (`ERR_EMPTY_RESPONSE`, curl exit 52) even though `docker compose ps` reports every service healthy.
- **Diagnose:**
  - `docker compose ps` (healthy).
  - `curl.exe -s -o NUL -w "%{http_code}" http://127.0.0.1:<FRONTEND_PORT>/` (000).
  - The VM log folder `%LOCALAPPDATA%\Docker\log\vm\` contains a freshly rotated `init.log.<timestamp>`, and `%LOCALAPPDATA%\Docker\log\host\com.docker.backend.exe.log` shows `guest exited` / `multiplexer is offline`.
  - `docker compose exec frontend wget -q -O - http://127.0.0.1:8080/api/v1/system/info` still works inside the network.
- **Causes:** the WSL 2 VM that hosts Docker Desktop exited, most likely under host memory pressure. Docker restarted it and the containers, but the host-side port forwarders stayed stale.
- **Recover (safe; no data is touched):**
  - Recreate only the service that publishes the port: `docker compose up -d --force-recreate frontend` (add `-f compose.production.yaml` for that layout). In the development layout, recreate each service whose published port is affected.
  - Jobs survive: commands are durable and unacknowledged work is redelivered. In Phase 10 an in-flight job completed by itself after the VM restart.
  - To prevent it, give Docker Desktop enough memory and avoid running heavy workloads next to inference on small hosts (see [deployment-guide.md § 1](deployment-guide.md#1-system-requirements)).

## Container health check failure

- **Symptoms:** `docker compose ps` shows `unhealthy`, or `up` reports `dependency failed to start`.
- **Diagnose:** `docker inspect --format "{{json .State.Health}}" <container>` and `docker compose logs <service>`.
- **Causes:** a dependency is not ready, missing passwords in `.env`, or a port conflict (see below).
- **Recover:** fix the cause shown in the logs, then `docker compose up -d <service>`. Health checks retry; services waiting on `service_healthy` start automatically.

## PostgreSQL connection failure

- **Symptoms:** the API answers `503 SERVICE_UNAVAILABLE` ("The data store is temporarily unavailable."); the backend logs `Connection to postgres:5432 refused`, `CannotCreateTransactionException`, or `password authentication failed`; readiness is `DOWN`.
- **Diagnose:** `docker compose exec postgres pg_isready -U yolovision -d yolovision`, then `docker compose logs postgres`.
- **Causes:** PostgreSQL still starting, or `DB_PASSWORD` changed after the volume was initialized (the password is set only on first initialization).
- **Recover:** wait for health. For a changed password, restore the previous value in `.env`, or change it inside PostgreSQL with `ALTER USER yolovision PASSWORD '...'` via `psql`. Do **not** delete the volume.

## Flyway migration failure

- **Symptoms:** the backend exits with `FlywayValidateException` or `Migration ... failed`.
- **Diagnose:** `docker compose logs backend | Select-String Flyway`, then `docker compose exec postgres psql -U yolovision -d yolovision -c "SELECT version, success FROM flyway_schema_history ORDER BY installed_rank;"`.
- **Causes:** a modified migration file (checksum mismatch), a manual schema edit, or an older backend image against a newer schema.
- **Recover:**
  - Restore the original migration file from Git and rebuild the backend.
  - Never "repair" by deleting history rows without understanding the cause.
  - A failed partial migration on a disposable database can be recreated; on real data, restore the backup.

## RabbitMQ connection failure

- **Symptoms:** the backend logs `AmqpConnectException`, the outbox retries (`Publishing command ... failed`), the consumer health file is stale, and jobs stay `PENDING`.
- **Diagnose:** `docker compose exec rabbitmq rabbitmq-diagnostics -q ping`, `docker compose exec rabbitmq rabbitmqctl list_queues name messages consumers`, and `docker compose logs rabbitmq`.
- **Causes:** broker restarting, or wrong `RABBITMQ_USERNAME`/`RABBITMQ_PASSWORD` (also set only when the volume is first initialized).
- **Recover:** wait for the broker.
  - Submissions made during the outage are still accepted (`202`) and stay `PENDING`; their outbox row records `Broker unavailable: …`.
  - The outbox republishes with bounded backoff, and the consumer reconnects automatically.
  - Accepted jobs are not lost; they stay in the outbox until confirmed. This was verified in Phase 10 by stopping RabbitMQ, submitting, and restarting it.
  - The broker health check (`check_port_connectivity`) turns healthy only when the AMQP listener accepts connections.

## Job stuck in QUEUED

- **Symptoms:** a job stays `QUEUED` with progress 0.
- **Diagnose:** `docker compose ps ai-detection-consumer`, `docker compose logs --since 10m ai-detection-consumer`, and `rabbitmqctl list_queues name messages consumers` (the command queue should show 1 consumer).
- **Causes:** the consumer is stopped or crashing, the worker is busy with a long job (concurrency 1), or the broker is unreachable from the worker.
- **Recover:** `docker compose up -d ai-detection-consumer`. If it stays queued longer than `JOB_QUEUE_TIMEOUT_SECONDS` (24 h), the lease monitor fails it with `QUEUE_TIMEOUT`, and the user can submit it again.

## Job stuck in DETECTING (or ENCODING/UPLOADING)

- **Symptoms:** progress stops advancing.
- **Diagnose:** the consumer logs for the job ID; `docker stats` for CPU and memory.
- **Causes:** a long video on CPU, the worker was OOM-killed, or the container restarted mid-job.
- **Recover:**
  - A restarted worker gets the unacknowledged command back and reprocesses it, with at-least-once delivery and job-scoped artifact keys.
  - A job with no worker activity (progress events or heartbeats) for `JOB_PROCESSING_TIMEOUT_SECONDS` is failed by the lease monitor with `PROCESSING_TIMEOUT`. A long but active job keeps its lease.
  - Give Docker more memory, or use a smaller model or image size.

## Dead-letter messages

- **Symptoms:** `vision.detection.dead-letter` has messages, and the related job has failed or is stuck.
- **Diagnose:** `rabbitmqctl list_queues name messages | Select-String dead-letter`. In the development layout, inspect messages in the management UI (Queues → `vision.detection.dead-letter` → Get messages, with **Ack mode: Nack requeue true** to leave them in place).
- **Causes:** a malformed or unsupported message, or a command that failed more than `RABBITMQ_DELIVERY_LIMIT` (5) times.
- **Recover:**
  - Fix the cause, then submit a new job for the same video; dead-lettered commands are not replayed automatically.
  - Purge the dead-letter queue only after reviewing it.

## Worker missing model weights

- **Symptoms:** the job fails with `MODEL_NOT_PREPARED`.
- **Diagnose:** `docker compose exec ai-detection-consumer python -m app.cli models status --model <key>`.
- **Causes:** the model was enabled in the database but never prepared in this worker's cache (host weights are not visible in Docker).
- **Recover:** prepare it ([deployment-guide.md § 12](deployment-guide.md#12-model-preparation)), then submit a new job.

## YOLO model download failure

- **Symptoms:** `models prepare` reports a download or HTTP error.
- **Diagnose:** outbound HTTPS access from the container, for example `docker compose exec ai-worker python -c "import urllib.request; urllib.request.urlopen('https://github.com', timeout=10)"`.
- **Causes:** no internet access, a proxy, or rate limiting.
- **Recover:** retry later, or copy a trusted checkpoint into the volume and run `prepare` to verify it offline. Never set `WORKER_ALLOW_MODEL_DOWNLOAD=true` as a workaround.

## CUDA unavailable

- **Symptoms:** logs show device `cpu` although `AI_DEVICE=cuda`, or a job fails with a device error.
- **Diagnose:** `docker compose exec ai-detection-consumer python -c "import torch; print(torch.cuda.is_available())"`.
- **Causes:** the image is CPU-only (default `requirements-ai-cpu.txt`), and no GPU passthrough is configured.
- **Recover:** use `AI_DEVICE=auto` or `cpu`. GPU support needs a CUDA PyTorch build and Docker GPU configuration; it is out of scope for the default image.

## FFmpeg unavailable

- **Symptoms:** jobs fail with an encoder error, and the logs mention `ffmpeg` not found.
- **Diagnose:** `docker compose exec ai-detection-consumer ffmpeg -version`. Outside Docker, check `AI_FFMPEG_PATH`/`AI_FFPROBE_PATH`.
- **Causes:** a custom image without FFmpeg, or wrong executable paths on a host run.
- **Recover:** rebuild the image (FFmpeg is installed in the Dockerfile), or set the absolute paths for host runs.

## Video download failure

- **Symptoms:** the job fails with a download error code (unavailable, private, too long, too large).
- **Diagnose:** the consumer logs for the job ID. The error code and the sanitized message also appear on the job page.
- **Causes:** the video is private, age- or region-restricted, removed, longer than `AI_MAX_VIDEO_DURATION_SECONDS`, or larger than `AI_MAX_VIDEO_SIZE_MB`; or a network problem.
- **Recover:** use an authorized, publicly accessible single video within the limits. Raise limits only deliberately.

## MinIO object missing

- **Symptoms:** the job page shows "The detected video is missing". The API returns `404 ARTIFACT_NOT_FOUND`.
- **Diagnose:** `docker compose logs backend | Select-String "is unavailable"`; the log line states the reason (no key recorded, key does not belong to the job, object missing, or empty).
- **Causes:** objects deleted or a MinIO volume replaced, or a restore of PostgreSQL without MinIO.
- **Recover:** restore MinIO from the backup taken together with PostgreSQL, or reprocess the video as a new job. Statistics and `result.json` (if present) remain available.

## HTTP 503 during video playback

- **Symptoms:** "Video storage is temporarily unavailable"; the API returns `503 STORAGE_UNAVAILABLE` with `Retry-After: 10`.
- **Diagnose:** `docker compose ps minio`, then `docker compose logs backend | Select-String "Object storage request failed"`. On startup the backend logs `Artifact storage: endpoint=..., bucket=..., credentials configured|MISSING`.
- **Causes:** MinIO down, or a wrong `MINIO_ENDPOINT` or missing `MINIO_SECRET_KEY` for the backend.
- **Recover:** start MinIO or fix the configuration, then use **Retry playback**. Jobs are not affected.

## HTTP Range problems

- **Symptoms:** seeking restarts the video, or downloads cannot resume.
- **Diagnose:** `curl.exe -s -D - -o NUL -H "Range: bytes=0-99" http://localhost:5173/api/v1/detections/<id>/video` should return `206` with `Content-Range: bytes 0-99/<size>`.
- **Causes:** a custom proxy that strips `Range` or buffers or rewrites responses.
- **Recover:** use the bundled Vite or nginx proxies, or configure the proxy to pass `Range`/`If-Range` and disable buffering. Multi-range requests intentionally return the full body (200).

## SSE disconnects

- **Symptoms:** "Reconnecting to live updates…" or "checking every few seconds" on the job page.
- **Diagnose:** `docker compose logs backend | Select-String -Pattern "SSE|emitter"`; check whether the proxy buffers `text/event-stream`.
- **Causes:** backend restart, proxy timeouts, or the connection cap (`DETECTION_SSE_MAX_CONNECTIONS`, 503 `STREAM_CAPACITY_EXCEEDED`).
- **Recover:** none needed. The browser reconnects, and after repeated failures the page falls back to polling and still reaches the final state. With a custom proxy, disable buffering and raise read timeouts.

## Frontend cannot reach the backend

- **Symptoms:** "Backend unavailable" in the top bar; API calls return 502/504.
- **Diagnose:** `docker compose ps backend`, `docker compose logs frontend`, and, in the development layout, `curl.exe -s http://localhost:8080/api/v1/system/info`.
- **Causes:** backend not healthy yet, or a wrong `VITE_PROXY_TARGET` for a host-run Vite.
- **Recover:** wait for backend health. For host development, set `VITE_PROXY_TARGET=http://localhost:<BACKEND_PORT>`. Same-origin UI requests do not depend on `CORS_ALLOWED_ORIGINS`.

## Windows port conflicts

- **Symptoms:** `Bind for 127.0.0.1:5432 failed: port is already allocated`.
- **Diagnose:** `netstat -ano | findstr :5432`, then `Get-Process -Id <pid>`.
- **Causes:** a local PostgreSQL or another stack already uses the port.
- **Recover:** change only the host port in `.env` (for example `POSTGRES_PORT=15432`), then `docker compose up -d`. Internal addresses stay the same.

## Node.js version mismatch

- **Symptoms:** `npm test` fails with jsdom or engine errors (`Unsupported engine`).
- **Diagnose:** `node -v`; the required range is in `frontend/package.json` `engines` (`^22.22.2 || ^24.15.0 || >=26.0.0`).
- **Recover:** install a supported LTS, or prepend an existing compatible runtime to `PATH` for the current shell only. Do not change dependencies to work around the runtime.

## Java or Maven version mismatch

- **Symptoms:** `release version 21 not supported`, or unexpected compilation errors.
- **Diagnose:** `java -version` and `mvn -v` (the Java line shows the JDK Maven uses).
- **Recover:** point `JAVA_HOME` at JDK 21 for the shell, for example `$env:JAVA_HOME = "C:\Program Files\Java\jdk-21"`. Use `backend\mvnw.cmd`, which brings Maven 3.9.16.
