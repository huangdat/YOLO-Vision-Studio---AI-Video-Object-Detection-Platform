# Phase 1 validation

Validation performed on Windows with Java 21, Node.js 24.19.0, and managed Python 3.11.15.

| Check | Result |
| --- | --- |
| `backend/`: `.\mvnw.cmd -B test` | Passed: 11 tests, zero failures or skips |
| `backend/`: `.\mvnw.cmd -B -DskipTests package` | Passed: executable application JAR produced |
| `frontend/`: `npm.cmd test` | Passed: 5 tests covering API contracts, connection, recovery, and routing |
| `frontend/`: `npm.cmd run build` | Passed: strict TypeScript check and Vite production build |
| `ai-worker/`: `.\.venv\Scripts\python.exe -m pytest` | Passed: 9 tests covering health, settings, and JSON logging |
| `ai-worker/`: `uv pip check` | Passed: installed dependencies compatible |
| `docker compose config --quiet` | Passed using portable Docker CLI 29.9.3 and Compose 5.7.0 |
| `docker compose up -d --build` | Could not run: no Docker daemon/named pipe available |
| `docker compose ps` | Could not run: same missing Docker daemon |

The Docker CLI was provisioned in the operating system temporary directory for validation. No Docker Engine installation or existing service changes were made. Generated local credentials remain only in the ignored root `.env`.

## Local runtime evidence

The backend started on port 18080 using the test-only H2 profile, because port 8080 was occupied by an unrelated Apache process and PostgreSQL was already listening on 5432. The worker started on 8000, and Vite started on 5173 with its proxy targeting the backend on 18080.

Verified HTTP responses:

- Backend `/api/v1/system/info`: exact application, service, version, and status contract.
- Backend `/actuator/health/liveness` and `/actuator/health/readiness`: HTTP 200, status `UP` under the H2 test profile.
- Worker `/health`: HTTP 200 with `{"service":"ai-worker","status":"UP"}`.
- Frontend `/api/v1/system/info`: the actual backend contract through the Vite proxy.

Chromium checks passed against these running services: actual connected state, a simulated network outage, retry recovery, all three placeholder routes and deep-link reloads, and mobile sidebar navigation. Desktop and mobile screenshots were visually inspected. There was no horizontal overflow at the checked viewport sizes and no browser runtime errors.

## Remaining infrastructure check

PostgreSQL, RabbitMQ, and MinIO container startup has not been verified. Backend H2 tests do not validate live PostgreSQL or RabbitMQ integration. The pinned MinIO source archive checksum was verified, but its Docker build and runtime remain unverified.

On a machine with a running Docker daemon, configure `.env`, select unused published ports, then run `docker compose up -d --build` and `docker compose ps`. Check all six services and the documented HTTP endpoints before treating the full container stack as validated.
