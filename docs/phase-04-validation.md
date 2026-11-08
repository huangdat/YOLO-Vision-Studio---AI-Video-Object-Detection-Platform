# Phase 04 validation

Validation ran on Windows 11 with JDK 21 and Maven 3.9.16 for the backend. The checked-in `mvnw.cmd` wrapper could not download its distribution in the validation environment, so the identical locally installed Maven version was used offline. Docker Desktop 29.9.2 ran the Testcontainers ITs. The worker used `ai-worker/.venv` (Python 3.11.15, PyTorch 2.13.0+cpu, Ultralytics 8.4.207) and FFmpeg/FFprobe 9.0.2, passed through `AI_FFMPEG_PATH`/`AI_FFPROBE_PATH`. CUDA was unavailable, so all inference ran on CPU.

| Check | Result |
| --- | --- |
| `mvn -B -Ppostgres-it clean verify`: unit and H2 tests | **PASS**: 54 tests (17 catalog API, 5 catalog service, 32 existing) |
| PostgreSQL 17 Testcontainers ITs (same run) | **PASS**: 40 tests (37 persistence including the V6 catalog and upgrade-preservation tests, 3 catalog API) |
| Backend packaging | **PASS**: `backend-1.0.0.jar` built |
| `python -m pytest -q`, clean environment | **PASS**: 216 tests (139 existing, 77 new) |
| `python -m pytest -q` with host `AI_*`, `LOG_LEVEL`, and FFmpeg overrides | **PASS**: 216 tests |
| `models status` before preparation | **PASS**: `yolo26s` reported `CACHED_UNVERIFIED`, all others `NOT_CACHED`. No files were created or downloaded. |
| `models prepare --model yolov8n` | **FAILED (environment)**: GitHub returned HTTP 504 for the `yolov8n.pt` release asset on every retry, and a separate `curl` request confirmed the 504. The command exited 1 with no partial file and no verification record. |
| `models prepare --model yolo11n --device cpu` | **PASS**: downloaded the official 5,613,764-byte `yolo11n.pt` into the cache, loaded it, and recorded `VERIFIED` |
| Real smoke, `python -m app.smoke --model yolo11n` | **PASS**: 36/36 frames, 36 `bus` detections, 7,058 ms |
| Real YOLO26s regression smoke, `--model yolo26s` | **PASS**: 36/36 frames, 36 `bus` detections, 7,938 ms. Cached weights were reused, and the file is now `VERIFIED`. |
| Real CLI `detect --model yolo11n --imgsz 640` on a 4 s, 640×480 clip | **PASS**: 60/60 frames, 60 `bus` detections, 8,872 ms, 46.6 ms average inference |
| Worker `GET /health` | **PASS**: HTTP 200 `{"service":"ai-worker","status":"UP"}` |
| `docker compose config --quiet` | **PASS** |
| Docker worker image rebuild and in-container preparation | **NOT RUN**: no worker code path requires a rebuild for validation. Container caches must be prepared separately (see the model management guide). |
| GPU inference | **NOT RUN**: no CUDA-capable PyTorch runtime |
| `yolov8n` real inference | **NOT RUN**: the checkpoint could not be downloaded (above). Mocked tests cover YOLOv8 key mapping and loading. |

## Output verification

FFprobe and a full `ffmpeg -xerror … -f null -` decode were run independently of the pipeline's own checks.

| Output | Codec | Pixel format | Range | Size | Frames decoded |
| --- | --- | --- | --- | --- | --- |
| `yolo11n` smoke `detected.mp4` | H.264 | `yuv420p` | `tv` | 320×320 | 36 |
| `yolo11n` CLI `cli-yolo11n-street.mp4` | H.264 | `yuv420p` | `tv` | 640×480 | 60 |
| `yolo26s` regression smoke | H.264 | `yuv420p` | — | 320×320 | 36 (smoke assertion) |

Both `yolo11n` result JSON files report `status: COMPLETED`, `modelKey: yolo11n`, `modelVersion: YOLO11`, `modelSize: n`, `weightsFilename: yolo11n.pt`, and `statistics.modelKey: yolo11n`. Processed frames equal decoded frames, and `totalDetections` equals the sum of `detectionsByClass`. The smoke test now asserts that the metadata identifies the selected model.

## Defects found and fixed during validation

- An existing test expected `yolo11s` to be rejected. That expectation is intentionally reversed in Phase 04, so the test case now uses unapproved keys instead (`yolov5s`, `yolo26s-seg`, `yolo11s-pose`, uppercase keys, and paths).
- The first version of the PostgreSQL upgrade-preservation test hung. Its setup rows were uncommitted inside the `@DataJpaTest` transaction and locked rows that the separate Flyway connection waited on. The test now runs with `Propagation.NOT_SUPPORTED` and always drops its temporary schema.
- Verification-record writing depended on the module-level `ModelLoader` name. It now uses a module-level helper.
- `models prepare` failures were labeled "Detection failed". They now say "Model preparation failed".

Generated videos, JSON outputs, the temporary CLI clip, model weights, and verification records remain in ignored `outputs/`, `temp/`, and `model-cache/` directories.
