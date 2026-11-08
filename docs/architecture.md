# Architecture

YOLO Vision Studio separates the browser application, API and metadata service, and Python processing service. Vehicle detection is the initial use case; later domain contracts should support any permitted detection classes and model families.

## Service boundaries

```mermaid
flowchart TD
    frontend[React frontend] -->|REST: system information| backend[Spring Boot backend]
    backend -->|JPA / Flyway| postgres[(PostgreSQL metadata)]
    backend -->|Health connection| rabbit[RabbitMQ]
    backend -.->|Future job publishing| rabbit
    rabbit -.->|Future asynchronous jobs| worker[Python AI worker]
    backend -.->|Future object metadata / links| minio[(MinIO videos)]
    worker -.->|Future video objects| minio
    worker -->|Explicit CLI / library call| pipeline[Video processing pipeline]
```

Solid arrows describe current integrations. Dashed arrows describe later phases. Through Phase 03, the backend has no worker HTTP client, job publisher, or storage SDK. The worker exposes health without starting a queue consumer or importing AI libraries at startup; its video pipeline runs only through explicit CLI/library calls. MinIO is provisioned infrastructure; video transfers are not integrated yet.

| Component | Responsibilities |
| --- | --- |
| Frontend | Navigation, presentation, backend status, and future job interaction |
| Backend | API contracts, validation, exceptions, CORS, persistence configuration, migrations, future business logic |
| AI worker | Independent health service and explicit local/authorized-YouTube video detection engine |
| PostgreSQL | Backend metadata and Flyway migration history |
| RabbitMQ | Future asynchronous job transport; current backend dependency health check |
| MinIO | Persistent S3-compatible object storage for future videos |

The frontend communicates only with Spring Boot. Python inference must never run inside Spring Boot. Neither media files nor downloaded model weights belong in PostgreSQL or Git. Services exchange metadata and object references when those contracts are introduced.

## Backend

`com.yolovision` contains `controller`, `service`, `repository`, `entity`, `dto`, `config`, and `exception` packages. Controllers expose DTOs; services provide behavior through constructor injection. Phase 02 adds `ModelConfig`, `DetectionJob`, and `DetectionResult` entities, Spring Data repositories, string-based job statuses, and record response DTO foundations. No detection controller or processing service is introduced.

Spring Boot configures PostgreSQL, RabbitMQ, Flyway, health probes, and CORS from environment variables. Hibernate validates production schemas instead of modifying them. The unchanged V1 foundation is followed by V2-V5 migrations for model metadata, jobs, results, and the disabled `yolo26s` seed. Jobs reference models restrictively; results reference one owning job and are removed with its metadata when the job is deleted. UUIDs, TIMESTAMPTZ, JSONB, relational constraints, and indexes support future processing without executing it. See [database-design.md](database-design.md) for the ER diagram, columns, query methods, and separate H2/PostgreSQL test strategies.

The global exception handler returns HTTP Problem Details and validation information without exposing internal exception messages or stack traces. Actuator exposes `health` and `info`; health details are hidden. Liveness indicates the application process is running. Readiness includes database and RabbitMQ availability, so dependency outages can produce a non-success health response even while the system information endpoint still responds.

## Frontend

React functional components use TypeScript strict mode, reusable navigation/status components, and a separate Axios API layer. React Router supplies Dashboard, Detection, History, and Models routes. The application shell maintains backend status across routes; the dashboard shows connection details. Feature routes identify planned work without pretending it is implemented.

The API client defaults to `/api/v1`. Vite proxies `/api` to Spring Boot, keeping browser traffic on the frontend origin during development. `VITE_PROXY_TARGET` selects the backend target used by the Vite process. The browser displays loading, successful connection, and error states based on actual responses; it offers retry after failure. No detection counts or availability claims are fabricated.

`VITE_API_BASE_URL` can override the browser API base URL for a different hosting setup. Values with a `VITE_` prefix are public browser configuration and must never contain credentials.

## AI worker

The worker uses FastAPI with API, services, workers, config, and schemas packages. Pydantic validates process settings. `python -m app` starts Uvicorn with the configured host, port, and JSON logging. Startup does not require PostgreSQL, RabbitMQ, MinIO, CUDA, model weights, or the optional AI Python dependencies.

Phase 03 adds `DetectionPipeline`, lazy cached YOLO26s loading, streamed frame inference, progress callbacks, bounded source handling, FFmpeg export, and JSON statistics. The library and CLI run independently of FastAPI and a broker. Counts describe bounding-box detection events across frames, not unique objects. Database model availability is not changed by local CLI support. See [ai-detection-engine.md](ai-detection-engine.md) for module boundaries and configuration.

`/health` verifies that the worker HTTP process can serve requests. It does not claim that model weights, queue consumers, or an inference execution are ready. There is no public synchronous inference endpoint.

## Current API contracts

`GET /api/v1/system/info`, served by Spring Boot:

```json
{
  "application": "YOLO Vision Studio",
  "service": "backend",
  "version": "1.0.0",
  "status": "UP"
}
```

`GET /health`, served by the internal Python service:

```json
{
  "service": "ai-worker",
  "status": "UP"
}
```

The backend also exposes `/actuator/health`, `/actuator/health/liveness`, and `/actuator/health/readiness`. Business APIs, SSE progress events, messaging schemas, and video object contracts belong to later phases.

## Deployment and persistence

Compose defines one dedicated bridge network and named volumes for PostgreSQL, RabbitMQ, and MinIO. Health checks gate dependent service startup. Published development ports bind to localhost; internal service discovery uses Compose names such as `postgres`, `rabbitmq`, and `backend`.

Runtime settings use environment variables. Required local credentials are supplied through the ignored root `.env`; `.env.example` contains no working passwords. The stack is a development foundation with no application authentication. A later deployment phase must define its environment-specific access and operational configuration before public hosting.
