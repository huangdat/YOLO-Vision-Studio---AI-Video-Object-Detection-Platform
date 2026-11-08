# Python AI worker

The worker provides an independent YOLO26s video detection library and CLI. The FastAPI service still exposes only health; it does not load a model or start inference at startup. Spring Boot, PostgreSQL, RabbitMQ, and MinIO are not required for CLI processing.

## Install on Windows

Use Python 3.11. Run from `ai-worker/`:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt

# Optional CPU inference dependencies: install in this order.
.\.venv\Scripts\python.exe -m pip install -r requirements-ai-cpu.txt
.\.venv\Scripts\python.exe -m pip install -r requirements-ai.txt
```

The first AI requirements file bootstraps CPU-only PyTorch from the official PyTorch index. The second installs the shared engine dependencies, retaining those compatible CPU wheels. Base HTTP dependencies and unit tests do not download weights. The supported headless Ultralytics distribution imports as `ultralytics` and avoids installing conflicting GUI OpenCV wheels.

Install FFmpeg and FFprobe, add their directory to `PATH`, or configure `AI_FFMPEG_PATH` and `AI_FFPROBE_PATH` with executable paths. Paths containing spaces are supported; pass the whole value as one environment variable.

```powershell
$env:AI_DEVICE = 'cpu'
$env:AI_LOCAL_INPUT_DIR = (Get-Location).Path
$env:AI_OUTPUT_DIR = 'outputs'
.\.venv\Scripts\python.exe -m app.cli --help
.\.venv\Scripts\python.exe -m app.cli detect `
  --source 'sample.mp4' --source-type local `
  --model yolo26s --confidence 0.25 --imgsz 960 `
  --classes 1,2,3,5,7 --device cpu
```

Local inputs must be inside `AI_LOCAL_INPUT_DIR`; outputs must stay inside `AI_OUTPUT_DIR`. Existing output files are not overwritten. Output defaults to a unique execution directory containing `detected.mp4` and `result.json`.

For an authorized single YouTube video, use `--source-type youtube` with a supported YouTube URL. This is not a general URL downloader. Install a supported Deno runtime on `PATH`, or set `AI_YOUTUBE_JS_RUNTIME_PATH`, when required by yt-dlp. Access-restricted, live, and playlist content is rejected or reported as unavailable; no cookies, login extraction, DRM, or access-control bypass is implemented.

## Run and test

```powershell
# HTTP health service; no inference dependencies or weights required.
.\.venv\Scripts\python.exe -m app

# Normal tests use fake models and mocked downloads; never download weights.
.\.venv\Scripts\python.exe -m pytest -q

# Explicit real inference smoke test; first run may download YOLO26s weights.
.\.venv\Scripts\python.exe -m app.smoke

# Model registry, cache status (no downloads), and explicit preparation.
.\.venv\Scripts\python.exe -m app.cli models list
.\.venv\Scripts\python.exe -m app.cli models status
.\.venv\Scripts\python.exe -m app.cli models prepare --model yolo11n --device cpu

# Smoke test with another approved model.
.\.venv\Scripts\python.exe -m app.smoke --model yolo11n
```

The smoke command generates a very short deterministic video, runs real inference, encodes H.264 MP4 without audio, verifies the output, and writes measured JSON statistics. Synthetic frames may legitimately produce zero detections; this is not replaced with fabricated counts.

## Linux and Docker

Use `python3.11`, `.venv/bin/python`, and the same requirements installation order on Linux x86_64. For CUDA, install a compatible PyTorch/Torchvision build using the official PyTorch instructions instead of the CPU bootstrap, then install `requirements-ai.txt`. An explicit `cuda:0` request fails when CUDA is unavailable.

```bash
docker build -t yolo-vision-ai-worker:local ./ai-worker
docker run --rm -p 8000:8000 yolo-vision-ai-worker:local

# Optional HTTP-only image, retaining FFmpeg but excluding AI Python packages.
docker build --target base -t yolo-vision-ai-worker:base ./ai-worker
```

Run these Docker commands from the monorepo root. The default image uses CPU-only PyTorch and runs as a nonroot user. Compose persists worker model cache, temporary storage, and output in worker-specific named volumes. No model weights are included in an image or loaded by the health service. GPU execution needs a CUDA-capable runtime/image and supported host drivers; the default image does not include a CUDA build.

See [the engine guide](../docs/ai-detection-engine.md) for configuration, pipeline design, metadata semantics, Docker CLI volume examples, and validation details. Ultralytics licensing must be reviewed before commercial deployment; consult the [official licensing information](https://www.ultralytics.com/license).
