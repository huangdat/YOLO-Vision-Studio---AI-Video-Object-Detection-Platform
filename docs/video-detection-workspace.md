# Video Detection Workspace (Phase 08)

The `/detection` route is the job submission workspace. It replaces the Phase 07 placeholder and submits jobs through the existing Phase 06 endpoint. **No backend, API, worker, or schema change was needed.**

```
YouTube URL + catalog model + classes + confidence + image size
  → POST /api/v1/detections  (Spring Boot; 202 Accepted)
  → navigate to /detections/{jobId}   (existing job page, existing useDetectionProgress SSE hook)
```

The frontend talks only to Spring Boot. It never contacts YouTube, RabbitMQ, MinIO, or the worker.

## 1. Layout

| Area | Contents |
| --- | --- |
| Main column | **Video source**, **Model configuration**, **Object classes** |
| Side column (sticky on wide screens) | **Detection settings** (confidence, image size) and the **Detection configuration** summary |
| Bottom | Submission banner (only after a failed submission) and the submit bar |

Below 1100 px the columns stack; below 580 px the class grid, size options, and confidence field reflow and the submit button spans the full width. Verified at 360, 390, 768, and 1440 px with no page-level horizontal overflow.

## 2. Video URL

`lib/youtube.ts` gives immediate feedback and mirrors the backend's `YouTubeVideoUrl` rules exactly, so it is **never stricter than the API**. The same 30 cases as `YouTubeVideoUrlTest` run in `youtube.test.ts`. The backend stays authoritative and canonicalises the URL itself; the frontend sends the trimmed URL as typed.

| Accepted | Rejected (message shown) |
| --- | --- |
| `youtube.com`, `www.`, `m.`, `music.` `/watch?v=<id>` (exactly one `v`) | Empty → "Enter a YouTube video URL." |
| `youtu.be/<id>` | Whitespace → "The URL must not contain spaces." |
| `/shorts/<id>`, `/embed/<id>` | Not an absolute URL, local paths → "Enter a full URL…" |
| `http` or `https`, default ports only | Other schemes (`ftp:`, `file:`) → "Only http(s) YouTube URLs are supported." |
| Extra parameters such as `t=` | Credentials → "The URL must not contain credentials." |
| | Non-default port → "The URL must use the default port." |
| | Other hosts (including look-alikes) → "Only YouTube video URLs are supported." |
| | `list=` or `/playlist` → "Playlists are not supported. Use a single video URL." |
| | Channels, missing or malformed 11-character id → "The URL must identify a single YouTube video." |

Errors appear after the field loses focus or after a submit attempt, never while the user is still typing a fresh value. The hint reminds users to submit only videos they are permitted to download and process.

## 3. Model selection

The catalog (`GET /api/v1/models` and `GET /api/v1/models/versions`) is the only source. `lib/modelSelection.ts`:

- **Versions:** only versions with registered models, in the backend's release order. Each option shows how many sizes are enabled, for example `YOLO11 (1 enabled)`.
- **Sizes:** the registered sizes of the chosen version, smallest first. Each shows its real `modelKey` and a "Disabled" tag where applicable.
- **Resolution:** a version and size select a model only when a matching catalog record exists. **Model keys are never constructed** from the version and size.
- **Default:** the first enabled model in release and size order. If none is enabled, the first registered model is shown and submission stays blocked.
- **Version change:** the size is kept when the new version has it, otherwise an enabled size is preferred, otherwise the smallest.
- **Reload:** a still-registered choice is kept; a removed one falls back to the default. The choice is derived during render, so a reloaded catalog never shows a stale or empty selection.

**Disabled models** can be selected for inspection but never submitted. The status box, the summary, and the submit bar all say so, and pressing *Start detection* only reveals the validation messages; no request is sent. Enablement remains an administrative setting (SQL, see [yolo-model-management.md](yolo-model-management.md)); the workspace has no enable or download controls. "Enabled" does not prove the worker has prepared the weights: the worker reports `MODEL_NOT_PREPARED` on the job page in that case, and the UI says so.

Catalog states: loading skeleton, error with *Try again* (for retryable errors), "No models are registered", and a warning when no model is enabled.

## 4. Object classes

`lib/cocoClasses.ts` holds the 80 COCO classes (IDs 0–79). They were copied from the `names` of the real `yolo11n.pt` and `yolo26s.pt` checkpoints (identical maps). The backend has no class-catalog endpoint, so this module is the single frontend source.

- **Presets:** *Vehicles (default)* = bicycle 1, car 2, motorcycle 3, bus 5, truck 7; *All 80 classes* sends all 80 IDs explicitly; *Clear*.
- **Search** by name or exact ID; a "No class matches" message for no results.
- **Removable chips** for selections of up to 12 classes, plus a live "N of 80 selected" count.
- The request always carries sorted, duplicate-free IDs. At least one class is required (the backend allows 1–100).

Results are counted as bounding-box **detection events per frame, not unique objects**; the hint says so.

## 5. Confidence and image size

- **Confidence:** a slider (0.01 steps) and a numeric field (up to three decimals) share one text value, so they always agree. Default `0.25`; valid range 0–1 with at most three decimals (the backend `@Digits(fraction = 3)` rule). Invalid text is kept as typed and flagged, not silently corrected. The hint states it is a filter threshold, not an accuracy score.
- **Image size:** 320, 640 (default), 960, or 1280 px. All are backend-valid multiples of 32. The hint notes that larger sizes cost more time, especially on CPU workers.

## 6. Configuration summary

The summary lists source, model (version and size name), model key, model status, confidence, image size, and class count. **"Ready to submit" means only that the form is valid and the model is enabled.** Otherwise it shows "N items to fix before submitting". A note explains that processing can still fail later (model not prepared, download failure) and that such failures appear on the job page.

## 7. Submission

`createDetection` in `api/detections.ts` posts exactly:

```json
{ "videoUrl": "...", "modelKey": "yolo11n", "confidence": 0.25, "imageSize": 640, "classes": [1, 2, 3, 5, 7] }
```

No other fields are sent; the backend rejects unknown fields. The 202 body (`jobId`, `status`, `progress`, `modelKey`, `message`) is shape-checked.

- **Duplicate protection:** a synchronous in-flight guard plus a disabled button. Rapid double clicks and Enter-plus-click produce one request (verified live: three triggers produced one `POST` and one job).
- **While submitting:** inputs are disabled, the button shows *Submitting…*, and the status line is announced politely.
- **No automatic retry.** A submission is never repeated by the client.
- **Success:** navigate to `/detections/{jobId}` with the accepted response in router state. The job page shows a "Job submitted" notice and follows progress with the existing `useDetectionProgress` hook. No second SSE connection is opened.

## 8. Failure handling

| Response | Meaning | UI |
| --- | --- | --- |
| 400 `INVALID_DETECTION_REQUEST` | Rejected, nothing created | Field messages from `errors` ("Rejected by the server: …"); unknown keys are listed in the banner. Messages clear when the field changes |
| 400 `MALFORMED_REQUEST` | Rejected | Banner with the server detail |
| 404 `MODEL_NOT_FOUND`, 409 `MODEL_DISABLED`, 409 `MODEL_NOT_SUPPORTED` | Rejected | Banner with *Reload models* |
| 413 `PAYLOAD_TOO_LARGE` | Rejected | Banner |
| 503 `SERVICE_UNAVAILABLE` | Backend could not store the job; nothing created | Banner: try again in a moment |
| Any other 4xx (for example a proxy or CORS 403) | Explicit refusal | "The request was rejected … No job was created." |
| Network error, timeout, 5xx without a code, unreadable 2xx | **Ambiguous**: the job may exist | Warning "The submission result is unknown" with *Open detection history*; check History before submitting again |

Every rejection keeps the form values. The backend writes the job and its outbox message in one transaction, which is why explicit rejections can state that nothing was created.

## 9. Code map

```
src/lib/youtube.ts            URL pre-check mirroring the backend
src/lib/modelSelection.ts     catalog-driven version/size resolution
src/lib/cocoClasses.ts        verified COCO class map and presets
src/lib/detectionForm.ts      form state, validation, exact request body
src/api/detections.ts         createDetection (POST /detections)
src/components/workspace/     VideoSourceField, ModelSelector, ClassSelector,
                              DetectionSettings (ConfidenceControl, ImageSizeSelector),
                              ConfigurationSummary
src/pages/Detection.tsx       page orchestration, submission, error mapping
src/pages/DetectionDetails.tsx  "Job submitted" notice from router state
```

## 10. Tests

90 new tests (163 total). The suites cover:

- the URL rules (`youtube.test.ts`, the backend cases plus messages)
- model selection, the class map, and form validation with the exact payload
- `createDetection` (body, 202 parsing, a problem response without retry, a missing `jobId`)
- the workspace page: catalog states, version and size resolution, disabled-model blocking, classes, confidence, the payload and single submission, navigation, field errors, every banner category, and focus on the first invalid field
- the job page notice

See [phase-08-validation.md](phase-08-validation.md).

## 11. Limitations

- **No authentication.** Like the API, the workspace is for local development only.
- **COCO classes only.** Custom models with other class sets are not supported in this phase.
- **No live YouTube validation.** The URL check is syntactic; availability, restrictions, and permissions are discovered by the worker.
- **No drafts.** Form values are not persisted across reloads.
- **Preview and download** of completed jobs are on the job page since Phase 09 (see [video-preview-download.md](video-preview-download.md)).
