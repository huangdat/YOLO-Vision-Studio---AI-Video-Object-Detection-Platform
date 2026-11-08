# YOLO Vision Studio

**AI-Powered Video Object Detection Platform**

A modular foundation for processing videos with YOLO models. Phase 1 provides a responsive dashboard, a Spring Boot API, a CPU-compatible Python service, and local infrastructure. The dashboard reports the actual backend connection state.

Phase 02 adds the PostgreSQL schema, Flyway migrations, JPA entities, repositories, and response DTO foundations for model configurations, detection jobs, and result metadata. The initial `yolo26s` metadata remains disabled; no weights are installed. See the [database design and persistence testing guide](docs/database-design.md).

Video detection, YouTube downloading, job execution, inference, statistics, authentication, and video transfer are reserved for later phases. The Detection, History, and Models pages are placeholders.

## Project structure

```text
.
├── frontend/          React dashboard and backend API client
├── backend/           Spring Boot API, configuration, migrations, tests
├── ai-worker/         FastAPI service, configuration, schemas, tests
├── infrastructure/    Supporting container configuration and notes
├── docs/              Architecture, development guide, roadmap
├── compose.yaml       Six-service local development stack
├── .env.example       Configuration template without credentials
├── .gitignore         Secrets, IDE files, build outputs, videos, weights
├── AGENTS.md          Persistent architecture and development rules
└── README.md
```

## Technologies

| Area | Selected versions |
| --- | --- |
| Backend | Java 21, Spring Boot 3.5.16, Maven 3.9.16 via Wrapper |
| Frontend | React 19.3.1, TypeScript 7.0.2, Vite 8.3.6 |
| UI and client | Tailwind CSS 4.3.5, Axios 1.21.0, React Router 7.18.5 |
| AI worker | Python 3.11, FastAPI 0.162.2, Pydantic 2.14.3, Uvicorn 0.54.0 |
| Persistence and messaging | PostgreSQL 17, RabbitMQ 4.2, MinIO `RELEASE.2025-10-15T17-29-55Z` |
| Testing | Spring Boot Test/JUnit, Vitest/Testing Library, Pytest 9.2.0 |

Backend dependencies include Spring Web MVC, Data JPA, Validation, Actuator, AMQP, and Flyway. Phase 1 installs no PyTorch, Ultralytics, OpenCV, model weights, or GPU runtime. Exact Java, Node, and Python dependencies are recorded in their service manifests and the frontend lockfile.

## Start with Docker Compose

Install Docker Engine or Docker Desktop with the Compose v2 plugin. Run commands from this existing repository root.

```powershell
Copy-Item .env.example .env
```

Fill the blank `DB_PASSWORD`, `RABBITMQ_PASSWORD`, and `MINIO_ROOT_PASSWORD` entries in `.env` with independently generated local values. MinIO requires at least eight characters for its root password. Keep `.env` private; it is ignored by Git. Compose rejects missing credentials.

```powershell
docker compose config --quiet
docker compose up -d --build
docker compose ps
```

The initial build downloads dependencies and builds the MinIO server from its pinned official source release. It can take longer than later starts. All services use CPU-compatible defaults; no GPU is required.

| Service | Local URL / port | Purpose |
| --- | --- | --- |
| Frontend | http://localhost:5173 | Dashboard |
| Backend | http://localhost:8080/api/v1/system/info | System information |
| Backend Actuator | http://localhost:8080/actuator/health | Dependency health |
| AI worker | http://localhost:8000/health | Worker HTTP liveness |
| PostgreSQL | `localhost:5432` | Metadata database |
| RabbitMQ | `localhost:5672` | AMQP transport |
| RabbitMQ management | http://localhost:15672 | Broker administration |
| MinIO API | http://localhost:9000 | S3-compatible storage |
| MinIO console | http://localhost:9001 | Object storage administration |

Published ports bind to `127.0.0.1` by default. Override host ports in `.env` if another application is already using them; for example, set `BACKEND_PORT=18080` and `POSTGRES_PORT=15432`. Container-to-container ports remain unchanged. See [infrastructure notes](infrastructure/README.md).

```powershell
Invoke-RestMethod http://localhost:8080/api/v1/system/info
Invoke-RestMethod http://localhost:8000/health
docker compose logs --tail 100 backend ai-worker
docker compose down
```

`docker compose down` preserves named volumes. Avoid volume deletion when retaining local data.

## Run tests

Install Java 21, Node.js 22.12 or later, and Python 3.11 for source development. The Maven Wrapper downloads Maven on first use.

```powershell
# backend/
.\mvnw.cmd test
.\mvnw.cmd -Ppostgres-it verify # Isolated PostgreSQL integration tests; Docker required.

# frontend/
npm ci
npm test
npm run build

# ai-worker/
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest

# repository root, after configuring .env
docker compose config --quiet
```

On macOS/Linux, use `./mvnw test` and `.venv/bin/python -m pytest`. Fast backend tests use a test-only H2 database, generate its entity mapping schema, and target Flyway at V1 only. The `postgres-it` profile separately executes the real migrations and persistence checks against isolated PostgreSQL 17 through Testcontainers. H2 success does not prove PostgreSQL compatibility. See the [database testing guide](docs/database-design.md#test-strategy-and-commands) and [development instructions](docs/development.md).

## Architecture and development workflow

The frontend calls Spring Boot through `/api/v1`; it never calls the Python worker directly. Spring Boot owns APIs, metadata, and future job coordination. Python owns future video processing. RabbitMQ will carry asynchronous jobs and MinIO will store video objects.

- [Architecture and current API contracts](docs/architecture.md)
- [Database schema, persistence mappings, and tests](docs/database-design.md)
- [Development environment, configuration, startup, and validation](docs/development.md)
- [Development phases](docs/roadmap.md)
- [Persistent project rules](AGENTS.md)

Every implementation phase starts by inspecting the existing repository and safely synchronizing `main` with `origin/main` using fast-forward updates. Run relevant tests, review only task-related changes, create a Conventional Commit, push `origin main`, and verify the remote commit and working tree. Never overwrite unrelated changes, commit secrets, or force push.
