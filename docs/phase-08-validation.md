# Phase 08 validation

## Environment

- **Platform:** Windows 11.
- **Node.js:** tests, type checks, builds, and the dev/preview servers ran on **Node v24.19.0 / npm 11.17.0**. This is the runtime already bundled with IntelliJ IDEA (`…\JetBrains\IntelliJIdea2026.2\acp-agents\.runtimes\node\24.19.0`), which Phase 07 also used. It was placed first on `PATH` for the validation shell only. The system Node (v22.14.0) was not changed, and nothing was installed.
- **Backend:** the existing Phase 06 JAR (`backend-1.0.0.jar`). The backend is unchanged in this phase. It ran on the default `java` on `PATH` (Java 22.0.2).
- **Worker:** the existing `ai-worker/.venv`, CPU only, FFmpeg 9.0.2.
- **Infrastructure:** **disposable** PostgreSQL 17, RabbitMQ 4.2, and MinIO containers on unused ports with random credentials. They were removed afterwards.
- **Untouched:** the user's `.env`, Compose stack, volumes, and ports 18080/15432.
- **Browser:** headless Chrome with a throwaway profile, driven over the DevTools protocol.

## Automated checks

| Check | Result |
| --- | --- |
| `npm test` (`vitest run`) | **PASS**: 163 tests in 14 files. Same result in three consecutive runs |
| Existing Phase 07 tests | **Preserved**: all 73 still run. One App test was rewritten on purpose: it asserted the placeholder, which this phase replaces, and now asserts the workspace route |
| New tests | **90** |
| Strict TypeScript (`tsc -b`) | **PASS** |
| Production build (`npm run build`) | **PASS**: 386 kB JS (121.5 kB gzip), 38.8 kB CSS |
| Dependencies | **No change**: `package.json` and `package-lock.json` are untouched |
| ESLint | **NOT RUN**: no ESLint configuration exists; strict `tsc` is the static check |
| Backend and Python suites | **NOT RE-RUN**: no backend or worker code changed |

Tests per file:

| File | Tests | New |
| --- | --- | --- |
| `lib/youtube.test.ts` | 39 | 39: the 30 backend `YouTubeVideoUrlTest` cases, trimming, empty input, and 7 exact messages |
| `lib/detectionForm.test.ts` | 19 | 19: defaults, confidence parsing, model blocking, field errors, exact request body |
| `pages/Detection.test.tsx` | 18 | 18 (see below) |
| `lib/modelSelection.test.ts` | 6 | 6 |
| `lib/cocoClasses.test.ts` | 3 | 3 |
| `api/endpoints.test.ts` | 14 | 3: `createDetection` |
| `pages/DetectionDetails.test.tsx` | 11 | 2: the submitted notice |
| `App.test.tsx` | 6 | 0 (1 rewritten) |
| Other Phase 07 files | 47 | 0 |

The page tests cover:

- catalog loading, error with retry, empty, and no enabled models
- default selection and version/size resolution through catalog records
- disabled-model blocking
- URL validation on blur
- class presets, search, and chips
- confidence slider/number sync and validation
- the exact payload with a single request under click, click, and submit, plus navigation
- focus on the first invalid field without an API call
- backend field errors with preserved values
- `MODEL_DISABLED` with catalog reload
- network failure, code-less 5xx, and unreadable success treated as ambiguous
- unrecognised 4xx and `SERVICE_UNAVAILABLE` reported as definite rejections

## Live integration (real backend, mocked YouTube downloader)

`yolo11n` was enabled with SQL **in the disposable database only**. No other model settings were touched.

**Mocked YouTube download.** No authorized YouTube video was available, so the worker ran through the validation-only launcher from Phase 06. It applies the worker's real URL validation, then copies a local fixture clip instead of downloading. **No request to YouTube was made, and this is not a live YouTube validation.** The worker log shows `MOCKED DOWNLOAD (no network): https://www.youtube.com/watch?v=abcdefghijk -> fixture street.mp4`. Everything else was real: Spring Boot, the outbox, RabbitMQ, YOLO11n CPU inference, FFmpeg, MinIO, and SSE.

| Scenario (browser through the Vite proxy) | Result |
| --- | --- |
| Fresh database, all 20 models disabled | Warning shown; versions read "(none enabled)"; `yolov8n` selected and marked disabled; *Start detection* sent **no** request |
| Submit `https://youtu.be/abcdefghijk?t=3`, `yolo11n`, confidence 0.3, 320 px, vehicles + person; button clicked twice plus `requestSubmit()` | **One** `POST` with exactly `{"videoUrl":"https://youtu.be/abcdefghijk?t=3","modelKey":"yolo11n","confidence":0.3,"imageSize":320,"classes":[0,1,2,3,5,7]}` |
| After 202 | Navigated to `/detections/{id}` with the "Job submitted" notice. Live SSE: `Pending 0 → Queued 0 → Detecting 15 → 46 → 82 → Completed 100` in about 10 s. Results: 153 person and 60 bus **detection events** |
| Database | Job stored with confidence 0.300, image size 320, classes `[0,1,2,3,5,7]`, status `COMPLETED`; the worker received the canonical URL |
| Same flow on the **production build** (`vite preview`, 390 px mobile) | One `POST`, `Pending → Detecting 25/56 → Encoding 85 → Completed 100`, no console problems. Two UI flows produced exactly **2** jobs |
| `yolo11n` disabled in the database after the page loaded, then submitted | 409 `MODEL_DISABLED` banner, "No job was created", URL preserved; *Reload models* showed the new state. Job count unchanged |
| Backend stopped after the page loaded, then submitted | Vite proxy 502 without a problem code → "The submission result is unknown" with a History link. One `POST`, no automatic retry, values preserved |

Console: the only entries across all runs were the deliberate 409 and 502 responses (and the 403 described below).

## Responsive layout

| Viewport | Result |
| --- | --- |
| 360×740, 390×844 (mobile emulation) | **PASS**: page width equals the viewport; columns stack; class grid in two columns; full-width submit button |
| 768×1024 | **PASS** |
| 1440×1100 | **PASS**: two columns with a sticky side column |
| Job page 360 px, Dashboard 390 px | **PASS**: no page overflow. The dashboard table still scrolls inside its own container (Phase 07 fix intact) |

## Defects found and fixed during validation

- **Unrecognised 4xx shown as "result unknown".** The first live submission returned 403. The cause was my own setup: the disposable backend allowed origin `localhost:5173` while the browser used `127.0.0.1:5173`. No job was stored, yet the UI called the result ambiguous. Any 4xx is an explicit refusal, so it is now reported as "The request was rejected … No job was created". Only network errors, timeouts, code-less 5xx, and unreadable success responses remain ambiguous. Tests were added for both cases. The backend was restarted with the correct origins.
- **Default selection flash.** The model choice was first reconciled in an effect, so the first render after loading showed the first `<option>` instead of the default. The choice is now derived during render. Found by a page test.
- **Layout polish.** A duplicate "Object classes" heading (the legend is now visually hidden), a double gap when the columns stack, and the sidebar and dashboard phase labels updated to Phase 08.

## Cleanup

All disposable resources were removed: the containers, the backend, worker, Vite, preview, and Chrome processes, and `ai-worker/temp/p08-work`. Validation scripts and logs stayed in the session scratch directory, outside the repository.

## Not run

- **Live YouTube downloading:** intentionally not performed (see above).
- **Docker Compose frontend container:** its image is unchanged; validation used the Vite dev server and `vite preview`.
- **Physical devices and screen-reader software:** not available. Accessible names are exercised through Testing Library role and label queries, and layout through Chrome device emulation.
