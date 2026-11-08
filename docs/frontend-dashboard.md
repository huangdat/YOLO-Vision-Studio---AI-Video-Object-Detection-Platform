# Frontend dashboard

Phase 07 connects the React dashboard to the Spring Boot APIs built in Phases 04–06. Every number, row, and status shown comes from the backend; nothing is invented when a request fails. Job submission (the Detection Workspace) is Phase 08, and video preview or download is Phase 09.

## 1. Architecture

The stack is React 19, TypeScript in strict mode, Vite 8, React Router 7, Axios, and Tailwind 4 with the project's custom CSS. There is no global state library: each page owns its data through small hooks.

```text
src/
  api/        client.ts (Axios + ApiError), guards.ts (runtime shape checks),
              models.ts, detections.ts, system.ts
  types/      api.ts, models.ts, detections.ts   (match the backend DTOs exactly)
  hooks/      useApiResource.ts, useDetectionProgress.ts, useBackendStatus.ts
  lib/        format.ts (dates, durations, sizes), jobStatus.ts (labels, tones, order)
  components/ JobStatusBadge, ProgressBar, StatCard, StateViews (loading/empty/error),
              PaginationControls, DetectionTable, PageHeader, Sidebar, Icon, StatusBadge
  pages/      Dashboard, Models, History, DetectionDetails, Placeholder (Detection)
  test/       fixtures.ts (data + FakeEventSource), render.tsx (router helpers)
```

`StatusBadge` shows the backend connection status, unchanged from Phase 01. `JobStatusBadge` shows detection job statuses.

## 2. Routes

| Path | Page | Data |
| --- | --- | --- |
| `/` | Dashboard | Job counts, recent jobs, model catalog, system info |
| `/history` | History | `GET /detections` (server-side pages) |
| `/detections/:jobId` | Job details | Job, SSE progress, and result metadata |
| `/models` | Models | Catalog, versions, and one model's details |
| `/detection` | Placeholder | The Detection Workspace arrives in Phase 08 |

Filters and pagination are stored in the URL, for example `/history?status=FAILED&page=1` or `/models?version=YOLO26&model=yolo26s`, so reloads, links, and the back button keep the view. Invalid URL values are ignored rather than sent to the API.

## 3. API client

- **Base path.** `API_BASE_URL` defaults to the relative `/api/v1`. The Vite proxy forwards `/api` to `VITE_PROXY_TARGET` (default `http://localhost:8080`; Compose uses `http://backend:8080`). No component contains a host or port. `VITE_API_BASE_URL` can override the base path for other deployments.
- **Errors.** Every failure becomes an `ApiError` with:
  - `kind`: `network`, `timeout`, `http`, `cancelled`, or `invalid-response`
  - the HTTP `status`
  - the backend `code` (for example `JOB_NOT_FOUND`)
  - `fieldErrors`, from the problem-detail `errors` map
  - a user-presentable `message`, which is the backend `detail` or a fixed friendly text such as "Unable to connect to the backend…"

  The `retryable` flag is true for connectivity failures, 5xx responses, and invalid responses. Only those errors show a "Try again" button.
- **Runtime guards.** Responses are checked against the expected shape. An HTML fallback page or an unknown status value becomes `invalid-response` instead of rendering `undefined`.
- **Cancellation.** Every request takes an `AbortSignal`. `useApiResource` aborts the previous request whenever its key (page, filters, or id) changes, so a slow response for old filters can never replace newer results. Cancelled requests are never shown as errors.

## 4. Models

The Models page uses three endpoints:

- `GET /api/v1/models`, with server-side `version`, `size`, and `enabled` filters
- `GET /api/v1/models/versions`, for the version filter options
- `GET /api/v1/models/{modelKey}`, for the details panel

Cards show the key, version, size name, task, checkpoint filename, and **administrative** status. The page states that "Enabled" does not mean the worker has prepared the weights (`MODEL_NOT_PREPARED`). The UI shows no readiness, GPU, benchmark, download, or enable/disable claims or controls.

## 5. History

`GET /api/v1/detections?page&size&status&modelKey`:

- Pages are fetched server-side, 10 rows by default (25 or 50 selectable, never more than the backend's 100), newest first as ordered by the backend.
- Changing a filter or the page size returns to the first page. The previous page stays visible, dimmed and marked `aria-busy`, while the next one loads.
- A page number beyond the last page offers a link back to the first page.

## 6. Dashboard statistics

| Metric | Source |
| --- | --- |
| Total, Completed, Failed | `totalElements` of `GET /detections?size=1` without a filter and with `status=COMPLETED` / `status=FAILED` |
| In progress | Total − Completed − Failed − Cancelled (each from its own `size=1` count query), floored at 0 |
| YOLO models, enabled | `GET /models` (the whole catalog is small) |
| Recent activity | `GET /detections?size=5` |
| Families | `GET /models/versions` and the catalog, grouped by version |

Counts never come from the rows of a page. The four count queries are separate requests rather than one snapshot. A job that changes state between them can make "In progress" briefly inaccurate by one, which is why it is floored at 0. The dashboard loads once per visit and has no polling. The backend connection check keeps its existing 30-second refresh.

## 7. Job details and results

The details page shows:

- **Header:** the status badge, a progress bar, and the stage description.
- **Configuration:** model, confidence, image size, class IDs, and source link.
- **Timeline:** created, started, completed, and last update.
- **Failures:** the stored, sanitized `errorCode` and `errorMessage` when a job fails.

An invalid UUID is rejected before any request is made, and an unknown job shows "Detection job not found".

When the job is `COMPLETED`, `GET /detections/{id}/result` supplies:

- the model used
- frames processed
- processing time
- total **detection events**
- a bar per class, labelled "*Class* detection events" and sorted by count, supporting any class name

The page states that counts are bounding-box detections summed across frames, not unique objects. Video preview and download are described as a future phase, with no links or buttons.

## 8. Live progress (SSE)

`useDetectionProgress(jobId, { enabled, pollIntervalMs = 5000, maxStreamErrors = 3 })` opens one native `EventSource` at `/api/v1/detections/{id}/events`. The path is relative, so it goes through the same proxy as Axios. The hook is UI-independent so the Phase 08 workspace can reuse it.

- **Connecting.** The details page enables the hook only after the job has loaded and only when it is not yet terminal.
- **Events.** The hook listens for `detection.progress`, `detection.completed`, `detection.failed`, and `detection.cancelled`, and parses each payload with the same guards as REST responses.
- **Ordering.** A snapshot replaces the current one only if it is not older (by the persisted `timestamp`) and not an earlier stage. Terminal snapshots are final, and events for another job are ignored.
- **Terminal events.** The stream closes on any terminal event. The page then reloads the job once, to get `completedAt` and the full error text, and fetches results when the job completed.
- **Cleanup.** The stream closes on unmount and when the job id changes. React StrictMode's double effects still leave a single connection.
- **Connection state.** The page shows "Connecting", "Live updates", "Reconnecting", or "Live updates unavailable; checking every few seconds".

## 9. Reconnection and fallback

- `EventSource` reconnects by itself after transient errors. The backend sends the latest persisted snapshot first, so a reconnect needs no replay. The backend does **not** replay missed transitions and the client does not use `Last-Event-ID`; brief stages can be skipped.
- If the browser gives up (`readyState === CLOSED`, for example after a 404 or a 503 stream-capacity response), after three consecutive stream errors, or where `EventSource` doesn't exist, the hook stops streaming and polls `GET /detections/{id}` every 5 s.
- Polling stops at a terminal state or a 404. SSE and polling never run at the same time.

## 10. Error handling

Every API-driven section has loading skeletons (announced through a hidden status), an empty state, and an error state carrying the normalized message and "Try again" where retrying can help:

| Situation | Message |
| --- | --- |
| Empty catalog | "No models are registered." |
| Empty history | "No detection jobs yet." |
| Filters match nothing | "No models match these filters." / "No jobs match these filters." |
| Backend unreachable | "Unable to connect to the backend. Check that it is running and try again." |

Dashboard sections fail independently. If job statistics fail, the cards are hidden instead of showing zeros.

## 11. Configuration

| Variable | Used by | Default |
| --- | --- | --- |
| `VITE_PROXY_TARGET` | Vite dev and preview proxy for `/api` | `http://localhost:8080` (Compose: `http://backend:8080`) |
| `FRONTEND_PORT` | Vite dev server port | 5173 |
| `VITE_API_BASE_URL` | Build-time API base path | `/api/v1` |

**Node.js:** `^22.22.2 || ^24.15.0 || >=26` (`package.json` `engines`). jsdom 31, which runs the tests, does not start on older Node 22 releases. The Docker image uses `node:24-alpine`.

## 12. Local development

```powershell
cd frontend
npm ci
$env:VITE_PROXY_TARGET = 'http://localhost:18080'   # your BACKEND_PORT
npm run dev                                         # http://localhost:5173
```

## 13. Docker development

`docker compose up -d --build frontend backend` serves the dashboard at `http://localhost:${FRONTEND_PORT}`. The container's Vite proxy points at `http://backend:8080`. Live progress also needs `ai-detection-consumer` and a prepared and enabled model (see [asynchronous-job-processing.md](asynchronous-job-processing.md)).

## 14. Testing

```powershell
cd frontend
npm test          # Vitest + Testing Library (jsdom)
npm run build     # strict TypeScript (tsc -b) + production bundle
```

- **What the suites cover:** the API client and guards, endpoint parameters, every page (data, loading, empty, error, retry, filters, pagination, stale-response protection, invalid and unknown ids), and the SSE hook. The hook tests use a controllable `FakeEventSource` and fake timers only for the polling fallback; they cover initial snapshots, updates, terminal events, reconnects, fallback, unmount, StrictMode, and stale events.
- **Isolation:** tests mock the API modules and never call the backend.
- **Linting:** no ESLint configuration exists in this project. Strict `tsc` with `noUnusedLocals` and `noUnusedParameters` is the static check.

Executed results are recorded in [phase-07-validation.md](phase-07-validation.md).

## 15. Known limitations

- **Snapshots, not history.** Live progress shows current state; there is no event history.
- **Count timing.** Dashboard counts are separate queries, so a transition between them can momentarily skew "In progress".
- **Class names.** Class IDs on the job page are raw numbers, because the API does not expose model class names.
- **No authentication.** Everything is development-only, like the API (see [detection-rest-api.md](detection-rest-api.md)).
- **Not yet built.** No job submission form, cancellation, video preview, or download.

## 16. Future Detection Workspace (Phase 08)

The workspace can reuse:

- `listModels({ enabled: true })` for the model selector
- `ApiError.fieldErrors` to show per-field validation from `POST /detections`
- the `Location` header to navigate to `/detections/:jobId`
- `useDetectionProgress` and `JobStatusBadge`/`ProgressBar` for live progress

`api/detections.ts` currently has no create function; Phase 08 adds it next to the existing read functions.
