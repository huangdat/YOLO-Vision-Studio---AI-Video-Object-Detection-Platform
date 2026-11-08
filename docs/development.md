# Development guide

## Prerequisites

- Work in the already cloned repository; the Git repository root is the monorepo root.
- Java 21 with `JAVA_HOME` configured. Use the checked-in Maven Wrapper.
- Node.js 22.12 or later and npm. Dependencies are locked in `frontend/package-lock.json`.
- Python 3.11 with `venv` and pip, or `uv` for creating a managed Python environment.
- Docker Engine/Desktop with Compose v2 to run the complete stack.
- Git with the existing author identity and repository authentication.

No GPU or heavy AI packages are needed in Phase 1. First-time dependency installation and container builds need internet access.

## Inspect and synchronize Git

Read [AGENTS.md](../AGENTS.md) before implementation. Run the initial checks from the existing repository root:

```powershell
git status
git branch --show-current
git remote -v
git rev-parse --show-toplevel
git branch --list main
```

Identify unrelated changes and leave them untouched. If the working tree is clean and a different branch is checked out, use `git switch main`. Stop if switching or implementation would overwrite existing work.

```powershell
git fetch origin
git pull --ff-only origin main
```

Stop on divergence or unexpected conflicts. Do not initialize or clone another repository, change `origin`, stash unrelated changes, reset history, or force push.

## Configure local settings

```powershell
Copy-Item .env.example .env
```

Set unique local values for the three required password entries. Do not copy `.env` into any image or commit it. Set host ports to unused values if needed. Host port changes affect localhost URLs; container ports and service discovery remain fixed.

Compose automatically reads the root `.env` for interpolation. Java, Vite, and Python processes launched directly from a terminal do not automatically import that root file. Export required values into each process environment before starting it. The template uses simple, unquoted `KEY=value` entries; this PowerShell snippet imports that format without printing secret values:

```powershell
# Run in the repository root in each terminal that needs these settings.
Get-Content .env | ForEach-Object {
    if ($_ -match '^([A-Z][A-Z0-9_]*)=(.*)$') {
        [Environment]::SetEnvironmentVariable($matches[1], $matches[2], 'Process')
    }
}
```

For shell formats with quoted values or more advanced dotenv syntax, use an appropriate dotenv loader instead of this simple importer.

| Variable | Direct-process purpose |
| --- | --- |
| `SERVER_PORT` | Spring Boot listening port; defaults to 8080 |
| `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USERNAME`, `DB_PASSWORD` | PostgreSQL connection; password required |
| `RABBITMQ_HOST`, `RABBITMQ_PORT`, `RABBITMQ_USERNAME`, `RABBITMQ_PASSWORD` | AMQP connection; password required |
| `CORS_ALLOWED_ORIGINS` | Comma-separated allowed browser origins |
| `DB_CONNECTION_TIMEOUT_MS`, `RABBITMQ_CONNECTION_TIMEOUT_MS` | Backend connection timeouts |
| `APP_DISPLAY_NAME`, `APP_VERSION`, `APPLICATION_NAME` | Backend service metadata |
| `VITE_PROXY_TARGET` | Vite proxy target; defaults to `http://localhost:8080` |
| `VITE_API_BASE_URL` | Browser API base URL; defaults to `/api/v1` |
| `FRONTEND_PORT` | Direct Vite listening port; defaults to 5173 |
| `AI_WORKER_HOST`, `AI_WORKER_PORT` | Worker listen address and port; defaults to `0.0.0.0:8000` |
| `LOG_LEVEL` | Shared values: DEBUG, INFO, WARN, ERROR. The worker also accepts WARNING and CRITICAL; WARN normalizes to Python WARNING. |

Compose supplies connection values inside containers. Refer to [infrastructure configuration](../infrastructure/README.md) for host port variables and credentials.

## Start the full stack

```powershell
docker compose config --quiet
docker compose up -d --build
docker compose ps
```

Use `--quiet` for routine configuration validation to avoid printing interpolated credentials. The initial MinIO image build compiles its pinned official source release. Builds are CPU compatible and may take several minutes on first use.

Check the dashboard at http://localhost:5173 and the health contracts listed below. Use overridden ports when configured. To inspect a service:

```powershell
docker compose logs --tail 100 backend
docker compose logs --tail 100 ai-worker
docker compose logs --tail 100 frontend
docker compose down
```

Named volumes retain local state after `down`. Do not add `--volumes` when that state must be preserved. Updating a password in `.env` does not automatically change credentials already initialized inside a persistent database or broker; use the service's administration procedure for existing data.

## Run source services locally

Start only dependencies with Compose before launching the Java service:

```powershell
docker compose up -d postgres rabbitmq minio
```

In a terminal that has loaded the root `.env`, point Spring Boot at the published localhost dependency ports:

```powershell
$env:DB_HOST = 'localhost'
$env:DB_PORT = $env:POSTGRES_PORT
$env:RABBITMQ_HOST = 'localhost'
$env:SERVER_PORT = $env:BACKEND_PORT
Set-Location backend
.\mvnw.cmd spring-boot:run
```

The `.env` template contains the default published ports. If `RABBITMQ_PORT` is overridden there, that host value is used by the local Java process. On macOS/Linux, export the equivalent variables and run `./mvnw spring-boot:run`.

Start the frontend in another terminal after loading `.env`:

```powershell
$env:VITE_PROXY_TARGET = "http://localhost:$($env:BACKEND_PORT)"
Set-Location frontend
npm ci
npm run dev
```

The frontend proxies requests to this Java process. If using a custom browser origin, add it to `CORS_ALLOWED_ORIGINS`. A built frontend requires a hosting layer that forwards `/api` to Spring Boot and falls back to `index.html` for client-side routes; Vite development proxy settings are not a production reverse proxy.

Start the worker in another terminal:

```powershell
Set-Location ai-worker
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m app
```

If Python is unavailable but `uv` is installed:

```powershell
uv python install 3.11
uv venv --python 3.11 .venv
uv pip install --python .venv/Scripts/python.exe -r requirements-dev.txt
.\.venv\Scripts\python.exe -m app
```

On macOS/Linux, use `python3.11 -m venv .venv` and `.venv/bin/python`. Run from `ai-worker/` so that `app` is importable. The worker defaults to port 8000; change `AI_WORKER_PORT` for local conflicts.

## Tests and runtime verification

Run commands from the indicated service directory:

| Location | Command | What it verifies |
| --- | --- | --- |
| `backend/`, Windows | `.\mvnw.cmd test` | API contract, CORS, error handling, application context and Flyway with test-only H2 |
| `backend/`, macOS/Linux | `./mvnw test` | Same backend tests |
| `frontend/` | `npm test` | Backend connection response and error behavior |
| `frontend/` | `npm run build` | Strict TypeScript compilation and Vite production bundle |
| `ai-worker/` | `.\.venv\Scripts\python.exe -m pytest` | Health response, configuration validation, JSON logging |
| Repository root | `docker compose config --quiet` | Compose syntax, interpolation, required settings |
| Repository root | `docker compose up -d --build` | Container builds and startup; requires an available Docker daemon |
| Repository root | `docker compose ps` | Service health and running state |

The backend test profile is defined only under test resources. It uses H2 and disables RabbitMQ dependency health checks; it does not change the normal PostgreSQL configuration. A Docker configuration check does not prove that containers build or start. Report missing tooling or daemon access separately from passing tests.

Verify the running services with the actual configured ports:

```powershell
Invoke-RestMethod http://localhost:8080/api/v1/system/info
Invoke-RestMethod http://localhost:8080/actuator/health/liveness
Invoke-RestMethod http://localhost:8080/actuator/health/readiness
Invoke-RestMethod http://localhost:8000/health
```

The system information response must contain `application=YOLO Vision Studio`, `service=backend`, `version=1.0.0`, and `status=UP`. The worker response must contain `service=ai-worker` and `status=UP`.

Open the dashboard and check that its connection indicator reflects the backend response. Stop only the backend process started for this project, confirm an unavailable/error state, restart it, and use retry to confirm recovery. Check narrow and wide layouts and navigate to each placeholder route. The frontend should never send requests directly to the worker.

## Commit and push a completed phase

Run the appropriate checks and resolve failures before committing. Review all tracked and untracked files, including ignore behavior:

```powershell
git status --short
git diff --check
git diff
git check-ignore .env frontend/node_modules backend/target ai-worker/.venv .idea
```

Stage explicit task-related paths after inspection; never stage unrelated user files. Inspect staged content for credentials and build artifacts:

```powershell
git diff --cached --stat
git diff --cached
git commit -m "chore(phase-01): initialize project foundation"
git push origin main
git fetch origin
git status
git log -1 --oneline
git branch --show-current
git rev-parse main
git rev-parse origin/main
git ls-remote origin refs/heads/main
```

The Phase 1 commit uses the message above. Future phases use `type(scope): description` and one meaningful commit per completed phase where practical. Use the existing Git author identity. Do not create a feature branch or pull request for this workflow.

Verify that local `main`, `origin/main`, and the remote branch identify the expected commit and that no implementation changes remain uncommitted. Report the hash and actual push result. If authentication, identity, conflicts, or repository protections block completion, report the issue without bypassing safeguards or claiming success.
