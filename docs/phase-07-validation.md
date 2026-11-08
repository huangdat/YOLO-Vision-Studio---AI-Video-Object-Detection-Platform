# Phase 07 validation

## Environment

- **Platform:** Windows 11.
- **Node.js:**
  - The system install (`C:\Program Files\nodejs`) is v22.14.0, which cannot start jsdom 31 (requires `^22.22.2 || ^24.15.0 || >=26`). This also affected the existing Phase 01 tests.
  - Tests and the final build ran on **Node v24.19.0 / npm 11.17.0**, an existing runtime already present on the machine. It was placed first on PATH for the validation shell only; no system configuration was changed.
  - The `engines` field in `package.json` (and the lockfile's root entry) was corrected from `>=22.12.0` to the toolchain's real requirement, `^22.22.2 || ^24.15.0 || >=26.0.0`.
- **Backend, containers, and browser:**
  - The backend ran from the committed Phase 06 JAR.
  - Disposable PostgreSQL 17, RabbitMQ 4.2, and MinIO containers were started and removed afterwards; the user's Compose stack, `.env`, and volumes were not touched.
  - The browser was headless Chrome with a throwaway profile.

## Automated checks

| Check | Result |
| --- | --- |
| `npm test` (`vitest run`) | **PASS**: 73 tests in 9 files. The same result in three consecutive runs |
| Strict TypeScript (`tsc -b`, `noUnusedLocals`/`noUnusedParameters`) | **PASS** |
| Production build (`npm run build`) | **PASS**: 364 kB JS (115 kB gzip), 32 kB CSS |
| Dependencies | **No change**. `package.json` differs only in `engines`. `npm ci --dry-run` confirms the lockfile is in sync |
| ESLint | **NOT RUN**: no ESLint configuration exists in this project; strict `tsc` is the static check |

Tests per file:

| File | Tests | Covers |
| --- | --- | --- |
| `App.test.tsx` | 6 | 3 existing Phase 01 tests, plus routing for History, Models, and job details with sidebar highlighting |
| `api/system.test.ts` | 2 | Existing tests, unchanged |
| `api/client.test.ts` | 9 | Problem details, field errors, 404/5xx, network, timeout, cancellation, invalid responses |
| `api/endpoints.test.ts` | 11 | Query parameters, `size=1` counts, shape guards, SSE payload parsing, relative SSE URL |
| `hooks/useDetectionProgress.test.tsx` | 14 | See below |
| `pages/Dashboard.test.tsx` | 7 | KPIs from pagination metadata, recent activity, families, loading, empty, error and retry, no negative counts |
| `pages/Models.test.tsx` | 7 | Catalog, version/size/enabled filters with URL state, empty and no-match states, error and retry, details |
| `pages/History.test.tsx` | 8 | Paging, newest-first order, filters resetting the page, stale-response protection, empty states, invalid URL parameters, error and retry |
| `pages/DetectionDetails.test.tsx` | 9 | Pending, detecting with live events, completion with reload and results, arbitrary class names, no detections, failed, invalid id, unknown id, retry |

The SSE hook tests cover:

- the initial snapshot over the relative proxy path
- progress updates, and ignoring stale or backward events
- completed, failed, and cancelled events closing the stream
- reconnecting
- polling fallback after a rejected stream and after repeated errors, stopping at a terminal state or a 404
- closing on unmount
- a single connection under StrictMode
- no connection when disabled or for an invalid id, and ignoring events for another job

They use a deterministic `FakeEventSource`, and fake timers only for polling.

## Live backend integration

The Vite dev server proxied `/api` to the backend. Data was produced through the real API and a real worker: job submission went through the controlled downloader stub described in [phase-06-validation.md](phase-06-validation.md), and the rest of the pipeline was real.

| Observation | Result |
| --- | --- |
| Data set | 12 jobs: 1 completed (real YOLO11n inference), 1 failed (`MODEL_NOT_PREPARED`, the model enabled but not prepared on the worker), 10 queued |
| `POST` and `GET` through the Vite proxy | All responses correct, including 202 submissions |
| SSE through the Vite proxy (`curl -N`) | 9 `detection.progress` events and 1 `detection.completed`, streamed unbuffered |
| Dashboard | 12 total, 1 completed, 1 failed, 10 in progress, 20 models (2 enabled), 5 recent rows; all matched the API counts |
| Models | 20 cards; `version=YOLO26&size=s` showed 1 card |
| History | 10 + 2 rows over 2 pages; `status=FAILED` showed the one job with `MODEL_NOT_PREPARED` |
| Completed job | 60 frames, 7.4 s, 60 bus detection events, the not-unique-objects note, and the future-video note with no links |
| Failed job | Code and sanitized remediation message shown |
| Invalid id / unknown id / Detection placeholder | "Invalid job ID", "Detection job not found", and the placeholder each rendered correctly |

## Browser validation

| Check | Result |
| --- | --- |
| Console, 12 pages (Chrome headless, dev server) | **PASS**: no errors or warnings. Capture confirmed working, since React's and Vite's info messages were recorded |
| Console, production build via `vite preview` (CDP) | **PASS**: no errors or exceptions. The only network log is the intentional 404 when opening an unknown job id |
| **Live SSE in the browser** (production build, CDP sampling the DOM) | **PASS**: a queued job's page updated itself from `Queued 0` through `Detecting 15…71`, `Encoding 85`, and `Uploading 96` to `Completed 100` in 26 s. The live indicator disappeared when the stream closed, and the result statistics loaded automatically |
| Mobile 390×844 and 360×740 (CDP device emulation) | **PASS after a fix**: the page width equals the device width on Dashboard, History, Models, and job details; tables scroll inside their own container |
| Tablet 768 / desktop 1440 | **PASS**: no horizontal overflow |

## Defects found and fixed during validation

- **Mobile overflow.** Dashboard and History rendered 608–623 px wide on a 390 px device. The production build behaved the same, which ruled out a dev-server styling artefact. The cause was absolutely positioned, visually hidden table text escaping its `overflow-x: auto` wrapper. Fixed by making the wrapper the containing block (`position: relative`).
- **Accessible names.** Computed names read "View detailsfor job …" and "Detailsfor yolo11n", because the leading space of hidden text was lost. Both controls now carry explicit `aria-label`s, and a test asserts the exact name.
- **Copy.** "1 model match the filters" now reads "1 model matches the filters" (and likewise for jobs).
- **Test fixes.** One test read the connection label before React flushed the state; it now awaits it. Another queried "60", which correctly appears twice; it now reads the metric by its label.

## Not run

- **ESLint:** not configured.
- **Docker Compose frontend container:** its image is unchanged (`node:24-alpine`); validation used the Vite dev server and `vite preview` against the disposable backend.
- **Live YouTube downloading:** see the Phase 06 limitations.
- **Physical mobile devices and screen-reader software:** not available. Accessible names were verified with `dom-accessibility-api`, and layout with Chrome device emulation.
