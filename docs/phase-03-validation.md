# Phase 03 validation

Validation was performed on Windows 11 using the `ai-worker/.venv` environment: Python 3.11.15, PyTorch 2.13.0+cpu, Ultralytics 8.4.207, OpenCV 5.0.0, NumPy 2.3.5, and FFmpeg/FFprobe 9.0.2 (gyan.dev essentials build). The FFmpeg executables were outside `PATH` and were supplied through `AI_FFMPEG_PATH` and `AI_FFPROBE_PATH`. CUDA was unavailable, so all real inference ran on CPU. Cached `yolo26s.pt` weights in `ai-worker/model-cache/` were reused; nothing was downloaded.

| Check | Result |
| --- | --- |
| `python -m pytest -q` (clean environment) | Passed: 139 tests, zero failures or skips |
| `python -m pytest -q` with host `AI_*` overrides, including real FFmpeg paths | Passed: 139 tests after test environment isolation was added (see below) |
| `python -m app.smoke --device cpu` (real YOLO26s, full pipeline) | Passed |
| Real CLI `detect` on a short local MP4 | Passed, exit code 0 |
| CLI argument errors / missing source | Exit codes 2 and 1 with readable messages |
| Worker `/health` via `python -m app` | HTTP 200, `{"service":"ai-worker","status":"UP"}`; startup loaded no model |
| Worker `POST /detect` | HTTP 404: no public inference route |
| Docker image build / container smoke | Not run: Docker daemon unavailable during validation |
| Live YouTube download | Not run: the mocked downloader tests cover validation and limits only |
| GPU (`cuda:0`) inference | Not run: no CUDA-capable PyTorch runtime available |

## Real smoke test

`python -m app.smoke --device cpu` generated a 3-second, 12 FPS, 320×320 MJPEG clip from the Ultralytics bundled `bus.jpg` sample and ran the complete local pipeline.

| Measurement | Value |
| --- | --- |
| Model / device | `yolo26s` / `cpu` |
| Settings | confidence 0.25, image size 320, classes `[1, 2, 3, 5, 7]` |
| Frames processed / decoded from output | 36 / 36 |
| Detections | 36 (`bus`: 36) |
| Average inference time | 51.7 ms per frame |
| Pipeline processing time | 8,800 ms |
| Output | `outputs/<execution-id>/detected.mp4` (65,219 bytes), `result.json`, `smoke-report.json` |

## Real CLI detection

A 4-second, 15 FPS, 640×480 H.264 clip was produced from the same sample image with FFmpeg into `ai-worker/temp/cli-input/`, then processed with:

```powershell
.\.venv\Scripts\python.exe -m app.cli detect --source temp/cli-input/street.mp4 --source-type local --device cpu --output cli-street-detected.mp4
```

Default settings applied: confidence 0.25, image size 960, vehicle classes `[1, 2, 3, 5, 7]`. Progress increased monotonically from DETECTING 15% through ENCODING 99% and reached COMPLETED 100% only after the MP4 and JSON were published.

| Measurement | Value |
| --- | --- |
| Frames processed / decoded from output | 60 / 60 |
| Detections | 79 (`bus`: 79) |
| Average inference time | 377.4 ms per frame |
| Pipeline processing time | 29,653 ms |
| Output | `outputs/cli-street-detected.mp4` and `outputs/cli-street-detected.json` |

A frame extracted from the output showed a correctly labeled `bus 0.86` box. Pedestrians were excluded by the vehicle class filter.

## Output media verification

FFprobe and a full FFmpeg decode (`ffmpeg -xerror -i <file> -f null -`) were run on both outputs independently of the pipeline's own checks.

| Property | Smoke output | CLI output |
| --- | --- | --- |
| Codec / profile | H.264 / High | H.264 |
| Pixel format | `yuv420p` | `yuv420p` |
| Color range | `tv` (limited) | `tv` (limited) |
| Dimensions / frame rate | 320×320 / 12 FPS | 640×480 / 15 FPS |
| Counted frames | 36 | 60 |
| Audio streams | None | None |
| Full decode | No errors | No errors |
| Faststart | `moov` atom precedes media data | — |

The previously reported `yuvj420p` output is resolved in the complete pipeline. The encoder converts OpenCV's full-range MJPEG intermediate to limited-range `yuv420p` and rejects any other probed pixel format.

## JSON result verification

Both `result.json` files reported `status: COMPLETED`, `sourceType: LOCAL_FILE`, input metadata matching the source (dimensions, FPS, frame count), and statistics equal to the measured run. `totalFramesProcessed` matched the decoded output frame count, and `totalDetections` equalled the sum of `detectionsByClass`. Counts are bounding-box detections across frames, not unique objects.

## Defect fixed during validation

With `AI_FFMPEG_PATH`/`AI_FFPROBE_PATH` set to real executables, two encoder unit tests failed. Their fake subprocess identifies FFprobe by the default command name. A setting such as `AI_OUTPUT_DIR` also broke a pipeline test. Tests built `Settings()` from the host environment. `ai-worker/tests/conftest.py` now clears host `AI_*`, `YOLO_*`, `LOG_LEVEL`, and `OMP_NUM_THREADS` variables and resets the settings cache for each test; tests that need a value still set it with `monkeypatch.setenv`. No production code changed for this fix.

Generated videos, JSON outputs, temporary fixtures, and model weights remain under ignored `outputs/`, `temp/`, and `model-cache/` directories and are not committed.
