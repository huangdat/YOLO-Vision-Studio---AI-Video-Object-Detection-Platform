# Local infrastructure

The root `compose.yaml` defines a CPU-compatible development stack on a dedicated bridge network. Configure the ignored root `.env` from `.env.example` before use. No working credentials are shipped in the repository. PostgreSQL uses `postgres:17-bookworm`; RabbitMQ uses `rabbitmq:4.2-management`.

## Services and ports

| Compose service | Container port | Default localhost port | Host setting |
| --- | --- | --- | --- |
| `frontend` | 5173 | 5173 | `FRONTEND_PORT` |
| `backend` | 8080 | 8080 | `BACKEND_PORT` |
| `ai-worker` | 8000 | 8000 | `AI_WORKER_PORT` |
| `postgres` | 5432 | 5432 | `POSTGRES_PORT` |
| `rabbitmq` AMQP | 5672 | 5672 | `RABBITMQ_PORT` |
| `rabbitmq` management | 15672 | 15672 | `RABBITMQ_MANAGEMENT_PORT` |
| `minio` API | 9000 | 9000 | `MINIO_API_PORT` |
| `minio` console | 9001 | 9001 | `MINIO_CONSOLE_PORT` |

Published ports bind to `127.0.0.1`. The backend uses `postgres:5432` and `rabbitmq:5672`; the frontend proxy uses `http://backend:8080`. Changing a published host port does not change these internal addresses. For conflicts with existing applications, select unused host values such as `BACKEND_PORT=18080` and `POSTGRES_PORT=15432` instead of stopping unrelated processes.

## Credentials and configuration

The template provides non-secret service names and usernames. Set independent local values for `DB_PASSWORD`, `RABBITMQ_PASSWORD`, and `MINIO_ROOT_PASSWORD`; Compose requires them to be nonempty. MinIO requires at least eight characters for its root password. Keep credentials in `.env` or an appropriate local secret mechanism, never in source files or image layers.

`DB_NAME` and `DB_USERNAME` configure initial PostgreSQL setup. `RABBITMQ_USERNAME` configures the broker's initial account. `MINIO_ROOT_USER` configures the object storage administrator. Initial account variables do not rotate credentials in existing persistent data automatically.

All container-facing ports are fixed in Compose. Direct source processes use the environment settings described in [development.md](../docs/development.md), including `SERVER_PORT` for Java and `AI_WORKER_PORT` for Python.

## Health and startup

PostgreSQL uses `pg_isready`, RabbitMQ uses its diagnostics command, and MinIO uses its HTTP readiness endpoint. The backend health endpoint includes database and RabbitMQ readiness. The frontend and worker have HTTP health checks. Compose startup dependencies wait for required service health before dependent applications start.

```powershell
docker compose config --quiet
docker compose up -d --build
docker compose ps
docker compose logs --tail 100 backend ai-worker
```

`config --quiet` validates configuration without displaying interpolated secrets. An installed CLI can perform this check without proving Docker daemon availability. Container builds, health checks, and service startup require a running Docker Engine/Desktop and must be verified separately.

## MinIO build

The MinIO container builds the official [source-only security release `RELEASE.2025-10-15T17-29-55Z`](https://github.com/minio/minio/releases/tag/RELEASE.2025-10-15T17-29-55Z). Its Dockerfile is maintained in `minio/Dockerfile` and verifies the release archive SHA-256 before compilation. A Go 1.24 Alpine build stage produces the binary; the Debian Bookworm runtime runs it as a nonroot user. The first build downloads Go modules and compiles the server; later builds can reuse cached layers. The resulting service remains CPU compatible and stores object data in its named volume.

The source build and runtime must be validated with Docker in an environment that has a running daemon. Configuration validation alone does not confirm this image builds or that MinIO starts. Bucket creation and storage access from application services are future work.

## Persistent data

Named volumes persist PostgreSQL data, RabbitMQ state, and MinIO objects. They are independent of application source and image rebuilds.

```powershell
docker compose down
```

This stops containers and removes the development network while retaining named volume data. Remove volumes only when deliberately discarding that local state. No automatic volume deletion, database reset, or destructive cleanup is part of the normal workflow.
