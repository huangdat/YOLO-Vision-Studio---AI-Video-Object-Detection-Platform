# INT8 Quantization: Phase 3 (Per-Job Precision, Full Stack)

Branch `feature/quantization-frontend-integration`, based on Phase 2.5 (`a34aca4`…`d801569`).
Earlier phases are documented in [quantization-poc.md](quantization-poc.md),
[quantization-phase2.md](quantization-phase2.md) and
[quantization-accuracy-validation.md](quantization-accuracy-validation.md).

Users can now choose the inference precision of each video detection job: **FP32** (the default)
or **INT8** (experimental). The choice travels React → Spring Boot → RabbitMQ → Python worker. The
result reports the precision that actually ran. **FP32 remains the default everywhere.**

## Frontend behavior

**New detection job** (`/detection`, step "Detection settings", below Object tracking)

- An **Inference precision** radio group:
  - **FP32 · Standard** is selected by default.
  - **INT8 · Optimized** carries an **Experimental** tag.
- **INT8 explanation**, shown when INT8 is selected:
  - it is usually about 2× faster on CPU;
  - detections and Track IDs can differ slightly from FP32;
  - it needs an INT8 version of the model exported on the worker, and without one the job fails with an explanation;
  - accuracy is validated for pedestrians with yolo11n, not yet for vehicles.
- The selection is kept while other fields are edited, and is sent as `inferencePrecision`.

**Job details** (`/detections/{id}`, "Job settings")

| Situation | Shown |
| --- | --- |
| INT8 requested, INT8 ran | Requested: INT8 · Executed: OpenVINO INT8 |
| FP32 requested | Requested: FP32 · Executed: PyTorch FP32 |
| Job not completed yet | Requested: … · Executed: Pending |
| Result stored before Phase 3 | Requested: FP32 (the migration default) · Executed: Not reported by the worker |
| Backend without precision support | Requested: Not recorded |

- "Executed" comes **only** from the worker's result (`effectivePrecision`, `inferenceRuntime`), never from the request.
- For failures with `INT8_MODEL_UNAVAILABLE` or `PRECISION_MISMATCH`, an explanation is shown under the error code.

**History:** INT8 jobs carry an `INT8` tag next to the model.

Video playback, tracking statistics, charts, downloads, SSE progress and refresh are unchanged.

## API changes (additive)

**Create a job:** `POST /api/v1/detections`

```json
{
  "videoUrl": "https://www.youtube.com/watch?v=eO19UTm93GQ",
  "modelKey": "yolo11n",
  "confidence": 0.25,
  "imageSize": 640,
  "classes": [1, 2, 3, 5, 7],
  "processingMode": "DETECTION_TRACKING",
  "inferencePrecision": "INT8"
}
```

- `inferencePrecision` is optional and case-insensitive (`FP32`, `fp32`, `INT8`, `int8`). If omitted, it is **FP32**.
- Any other value returns `400 INVALID_DETECTION_REQUEST` with `errors.inferencePrecision = "must be FP32 or INT8"`.

**Responses**

| Response | New field |
| --- | --- |
| 202 Accepted, `GET /detections/{id}`, `GET /detections` rows | `inferencePrecision`: the requested precision (`FP32` or `INT8`) |
| `GET /detections/{id}/result` | `effectivePrecision` (`FP32`, `INT8` or `null`) and `inferenceRuntime` (`PYTORCH`, `OPENVINO` or `null`): what the worker actually ran. `null` for results stored before Phase 3. |

```json
{"jobId":"30ad496e-…","status":"PENDING","progress":0,"modelKey":"yolo11n",
 "message":"Detection job accepted","processingMode":"DETECTION_TRACKING","inferencePrecision":"INT8"}
```

```json
{"jobId":"30ad496e-…","totalDetections":11562,"effectivePrecision":"INT8","inferenceRuntime":"OPENVINO", "…": "…"}
```

**New job failure codes**

| Code | Meaning | Retried? |
| --- | --- | --- |
| `INT8_MODEL_UNAVAILABLE` | INT8 was requested, but the worker has no usable INT8 model for it. Causes: no artifact, invalid or stale artifact, no OpenVINO runtime, or a CUDA device. The message names the cause and both remedies. | No |
| `PRECISION_MISMATCH` | A completion reported a different precision than requested. The result is not stored. | No |

## Database and RabbitMQ

**Flyway `V9__detection_inference_precision.sql`** (additive):

- `detection_jobs.inference_precision VARCHAR(8) NOT NULL DEFAULT 'FP32'`, with CHECK `('FP32','INT8')`. Existing jobs become `FP32`.
- `detection_results.effective_precision VARCHAR(8)` and `inference_runtime VARCHAR(16)`, both nullable with CHECK constraints. Existing results stay `NULL`.

**Job command** `detection.execute.v1`:

- Adds `inferencePrecision` (`FP32` or `INT8`). It is sent for **every** job created by this version, so the worker runs exactly the requested precision even if an operator set `AI_MODEL_PRECISION=int8` globally.
- **Deploy the worker before the backend.** The worker rejects unknown command fields, the same constraint `processingMode` introduced.

**Completion event:** `result` adds `effectivePrecision` and `inferenceRuntime`. The backend stores them, or rejects the completion with `PRECISION_MISMATCH` if the precision differs from the request.

Job lifecycle, outbox, retries, dead-lettering and idempotency are unchanged.

## Worker precision selection

| Command `inferencePrecision` | Behaviour |
| --- | --- |
| `FP32` | PyTorch FP32, strict |
| `INT8` | OpenVINO INT8 artifact on `intel:cpu`, strict. Unavailable → `INT8_MODEL_UNAVAILABLE` (not retried). |
| absent (command queued before Phase 3) | Unchanged: `AI_MODEL_PRECISION` with its `AI_INT8_FALLBACK_TO_FP32` fallback |

**How the worker enforces it**

- **Fail before any work.** The job preflight loads the requested precision before the video is downloaded, so an unavailable INT8 model fails within seconds.
- **No silent substitution.** Explicit precision is strict in `ModelLoader`. The video processor also refuses a loaded model of another precision. A stored `result.json` from a different precision is never reported, and the backend rejects any mismatch. INT8 can therefore never silently run as FP32 while being reported as INT8.
- **Concurrent jobs stay separate.** FP32 and INT8 are separate cached model instances with separate inference locks (tested with 16 concurrent loads).
- **Nothing is exported during jobs.** Thresholds and ByteTrack are unchanged.
- **Results record what ran.** `result.json` and the completion event carry `effectivePrecision` and `inferenceRuntime`. Logs show `Inference for <model> uses INT8 OpenVINO on intel:cpu`.
- **CLI:** `python -m app.cli detect … --precision int8|fp32`.

## Model availability

INT8 availability is **not** checked when the job is submitted.

- **Why:** the backend has no channel to the detection consumer's model cache. Adding one would mean a new endpoint and new infrastructure, which this phase avoids.
- **What happens instead:** availability is checked explicitly by the worker before any work. An unavailable model gives an actionable `INT8_MODEL_UNAVAILABLE` failure, and the UI says so up front.
- **What is not done:** nothing is downloaded, exported or quantized from the frontend or during jobs.

Operators prepare INT8 models explicitly, per model:

```powershell
docker compose exec ai-detection-consumer python -m app.cli models quantize --model yolo11n --imgsz 960 `
    --calibration-video /data/temp/calibration.mp4 --calibration-frames 300
docker compose exec ai-detection-consumer python -m app.cli models int8-status
```

## Docker requirements

INT8 jobs need the AI images built with OpenVINO (`AI_WORKER_INSTALL_OPENVINO=true`, adds about 0.55 GB)
and an exported artifact in the `ai-model-cache` volume (see [quantization-phase2.md](quantization-phase2.md)).
With the default image, INT8 jobs fail with `INT8_MODEL_UNAVAILABLE` ("OpenVINO is not installed in this image").
FP32 jobs work with either image. No Compose change was needed in Phase 3.

## Backward compatibility

- **API clients:** existing clients and request bodies keep working; a missing precision is FP32. Response fields are only added. Existing Java record constructors are kept.
- **Existing data:** jobs read as requested `FP32`; their results show executed precision `null`.
- **Commands and workers:**
  - Commands queued before the upgrade (no field) keep the worker's global behaviour.
  - New commands need the new worker, so deploy the worker first.
- **Live Detection:** unchanged; see the limitations below.

## Error handling

| Case | Result |
| --- | --- |
| Invalid precision in the request | HTTP 400 field error; no job, no outbox message |
| INT8 requested, no or invalid artifact, no OpenVINO, or CUDA worker | Job `FAILED`, `INT8_MODEL_UNAVAILABLE`, actionable message, one attempt, no download |
| Worker reports another precision | Job `FAILED`, `PRECISION_MISMATCH`, no result stored |
| Stored result of another precision on redelivery | Not reported; handled as a storage failure |

## Test results (measured on this branch)

| Suite | Result |
| --- | --- |
| AI worker (`python -m pytest`, from `ai-worker/`) | **487 passed**, 0 failed, 10 skipped (5 need FFmpeg, absent on the Windows host; 5 need `IT_*` broker settings). 12 new tests: command parsing, strict INT8 and FP32, legacy default, unavailable INT8 failure, mismatch protection, effective precision reporting, 16 concurrent mixed-precision loads. |
| Backend unit (`mvnw test`) | **424 passed**, 0 failed. 12 new tests: validation and case-insensitivity, FP32 default, persistence, command propagation, responses, result mapping, lifecycle storage, `PRECISION_MISMATCH`, legacy completions, event JSON deserialisation. |
| Backend integration (`mvnw -Ppostgres-it verify`, Testcontainers PostgreSQL, RabbitMQ, MinIO) | **70 passed**, 0 failed, including V9 on PostgreSQL 17 (default, CHECK constraints, round trip) |
| Frontend (`tsc -b`, `vitest run`, `vite build`) | Typecheck clean; **259 passed** (8 new: default FP32, INT8 selection kept while editing, request serialisation, API parsing including legacy and invalid values, requested vs executed display, pending, error guidance); production build OK. Run in the project's `frontend` image (Node 24), because the host's Node 22.14 is below the required version. |
| Lint | No lint script is configured in the frontend or backend. |

**End-to-end in Docker** (isolated project `yvs-int8-test`, own ports and volumes; images built from
this branch with OpenVINO; the `yolo-vision-studio` stack was not touched):

- **Database upgrade:** Flyway applied V9 on top of an existing V8 test database. The 3 existing jobs read `FP32`, and their results `null`.
- **INT8 job** (REST → RabbitMQ → worker → MinIO): `COMPLETED` in about 95 s; result `effectivePrecision INT8`, `inferenceRuntime OPENVINO`, 11,562 detections; worker log `Inference for yolo11n uses INT8 OpenVINO on intel:cpu`.
- **FP32 job** (sent as lowercase `fp32`): `COMPLETED` in about 145 s; result `FP32` / `PYTORCH`, 11,354 detections.
- **INT8 job for yolo26s without an artifact:** `FAILED` in about 10 s with `INT8_MODEL_UNAVAILABLE` and an actionable message, one attempt, no download.
- **History through the frontend dev server's API proxy:** shows `inferencePrecision` per job.
- **Not done:** the UI was not exercised in a real browser in this phase. Its behaviour is covered by the component tests above.

## Known limitations

- **Live Detection keeps its existing behaviour:** the live worker's global `AI_MODEL_PRECISION` (FP32 by default) and its fallback. Per-session precision selection is **not** supported yet. It would need the live worker to cache models per precision and the WebSocket protocol to carry the choice, and the live pipeline was deliberately left unchanged.
- **No availability check at submission:** an unavailable INT8 model is reported as a fast, actionable job failure instead.
- **Vehicle accuracy is unvalidated:** INT8 accuracy is validated only for pedestrians with yolo11n (Phase 2.5). The UI states this; INT8 stays opt-in and experimental.
- **Legacy jobs show requested `FP32`.** This is the migration default for jobs created before precision existed. Some Phase 2 test jobs ran INT8 through the old global setting, which is why "Executed" shows "Not reported by the worker" for them instead of a guess.
- **Deployment order:** the worker must be upgraded before the backend.
