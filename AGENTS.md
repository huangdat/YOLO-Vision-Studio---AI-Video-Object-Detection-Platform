# Project instructions

## Architecture Rules
- Work in this existing monorepo; keep `frontend/`, `backend/`, `ai-worker/`, `infrastructure/`, and `docs/` at its root.
- Maintain separation between frontend, backend, and AI worker. The frontend communicates only with Spring Boot.
- Spring Boot owns APIs, business logic, job management, and PostgreSQL metadata. Python owns inference and video processing. RabbitMQ carries asynchronous jobs; MinIO stores videos.
- Never execute Python inference inside Spring Boot. Use environment variables for service configuration.
- Avoid unnecessary dependencies. Prefer readable, testable code and independent, modular services.
- Phase 1 contains foundation and health endpoints only. Do not add downloading, inference, jobs, encoding, tracking, statistics, authentication, or video transfer until requested.

## Backend Rules
- Use Java 21 and Spring Boot with a layered architecture under `com.yolovision`.
- Use constructor injection, DTO-based APIs, validation, and consistent exception handling.
- Keep controllers, services, repositories, entities, DTOs, configuration, and exceptions in their established packages.
- Use Flyway migrations for schema changes; never use Hibernate to mutate production schemas.

## Frontend Rules
- Use React functional components and TypeScript strict mode.
- Keep components reusable, API services separate from UI, and layouts responsive.
- Show actual backend connection state and handle failures. Do not present placeholder metrics as real data.

## Python Rules
- Use Python 3.11, type hints, Pydantic schemas, modular services, structured logging, and unit tests.
- Keep the default service CPU compatible. Do not download model weights at startup.

## Git Rules
These rules are mandatory for every future development phase.
1. Always work in the existing repository.
2. Use the `main` branch for the requested implementation workflow.
3. Inspect Git status, branch, remote, and repository root before changes.
4. Synchronize `main` with `origin` using `git fetch origin` and `git pull --ff-only origin main` only. Stop on divergence or unexpected conflicts.
5. Never run `git init`, clone again, replace `.git`, change the remote, or create another repository.
6. Never overwrite, remove, stash, or commit unrelated user changes. Stop if existing changes conflict with the task.
7. Never force push, including `--force-with-lease`.
8. Never use destructive Git operations or bypass repository protections.
9. Never commit secrets or generated build artifacts, videos, model weights, credentials, or private keys.
10. Keep commits logically organized; normally create one meaningful commit per phase.
11. Use Conventional Commit messages.
12. Run relevant tests before committing. Fix failures and accurately report unavailable checks; never claim skipped checks passed.
13. Commit each successfully completed phase. Inspect changes and stage only relevant files. Use the existing Git author configuration; report missing identity.
14. Push completed commits to `origin/main` without creating a pull request or feature branch unless instructed.
15. Verify the push succeeded and local `main` matches remote `main`.
16. Report commit hashes after pushing, along with branch and working tree status.
17. If Git authentication, permissions, or conflicts prevent pushing, report the issue and do not bypass protections.
18. Never claim a push succeeded without verifying it.

## Conventional Commit Format
Use `type(scope): description`. Allowed types: `feat`, `fix`, `chore`, `refactor`, `docs`, `test`, `build`, `ci`.

Examples:
- `chore(phase-01): initialize project foundation`
- `feat(phase-02): implement database schema`
- `feat(phase-03): implement YOLO detection engine`
- `fix(ai-worker): resolve video processing error`
- `refactor(backend): improve job management`
- `docs(project): update architecture documentation`

Every future Codex implementation must respect these rules.
