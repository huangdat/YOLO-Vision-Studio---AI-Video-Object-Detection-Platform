# INT8 Quantization PoC (OpenVINO, CPU)

> Phase 2 (ground-truth evaluation tooling, wider benchmarks, optional Docker runtime, FP32 fallback
> when OpenVINO is missing) is documented in [quantization-phase2.md](quantization-phase2.md). Some
> limitations listed below, such as "Not in Docker yet", are resolved there. Phase 1 results stay as
> recorded.

Status: **proof of concept** on branch `feature/model-quantization-poc`. Off by default; the
production path (PyTorch FP32) is unchanged. Frontend, Spring Boot, Compose, and the Docker
images are not modified.

This PoC adds optional post-training quantization (PTQ) of the approved YOLO detection
checkpoints to **OpenVINO INT8**, loads those artifacts through the existing model loader, and runs
them through the unchanged detection and ByteTrack pipeline. A benchmark harness compares FP32 and
INT8 on identical inputs.

## Findings that shaped the design

| Finding | Consequence |
| --- | --- |
| The installed Ultralytics build (`ultralytics-opencv-headless` 8.4.207) replaced `int8=True` with `quantize=8`. OpenVINO export accepts `batch, data, dynamic, quantize, nms, fraction`. | Export uses `format="openvino", quantize=8, data=..., fraction=..., dynamic=True, batch=1`. |
| `ModelLoader` calls `model.to(device)`, which Ultralytics allows only for PyTorch models. | INT8 has its own load path that never calls `.to()`. |
| For static-shape exports, the Ultralytics predictor silently replaces the requested `imgsz` with the export size. | INT8 is exported with **dynamic shapes**, so a job's `imgsz` (default 960) is honoured, and letterboxing matches PyTorch exactly. |
| With `device="cpu"`, the Ultralytics OpenVINO backend picks OpenVINO's `AUTO` device whenever a GPU is visible. | INT8 inference uses `device="intel:cpu"` (the CPU plugin). The public `device` stays `"cpu"` in results and APIs. |
| OpenVINO used all 6 physical cores, ignoring `AI_CPU_THREADS` and (on Windows) process affinity. Ultralytics has no option for this. | The loader recompiles the backend with `INFERENCE_NUM_THREADS = AI_CPU_THREADS` (verified: 4 → 4, 2 → 2). |
| Ultralytics treats images without label files as background. | An unlabeled set of frames sampled from a video is a valid calibration set; no annotation is needed. |
| Test host: AMD Ryzen 5 5600H (Zen 3, 6 cores, AVX2, **no AVX-512/VNNI**), Windows 11, OpenVINO 2026.4.1. `ov.Core()` reports `INT8` among CPU capabilities. | INT8 runs here, but this CPU lacks the VNNI instructions that give Intel CPUs their largest INT8 speed-ups. Results are specific to this host. |

ByteTrack (the only tracker in the project) is unaffected: it consumes the same `DetectionBox`
list whichever runtime produced it.

## Architecture changes (ai-worker only)

```text
app/config/settings.py            + AI_MODEL_PRECISION (fp32 | int8, default fp32)
                                  + AI_INT8_FALLBACK_TO_FP32 (default true)
                                  + AI_QUANTIZED_MODEL_DIR (default <AI_MODEL_CACHE_DIR>/quantized)
app/services/model_quantization.py  new: export, calibration set, validation, artifact inspection,
                                    OpenVINO thread cap. Imports no AI package at module import.
app/services/model_loader.py      + precision handling, INT8 load path, FP32 fallback
                                  LoadedModel + precision, runtime_device, predict_device
app/services/detection_service.py predict(device=loaded_model.predict_device)
app/cli.py                        + models quantize, models int8-status
app/core/exceptions.py            + QuantizationError
requirements-quantization.txt     optional: openvino==2026.4.1, nncf==3.4.0
benchmarks/quantization_benchmark.py  FP32 vs INT8 harness
tests/test_model_quantization.py  27 tests
```

**Loading rules**

- `AI_MODEL_PRECISION=fp32` (default): exactly the previous behaviour.
- `AI_MODEL_PRECISION=int8`:
  - On CPU with a `VALID` artifact, the loader opens the OpenVINO INT8 model on `intel:cpu`, warms it up once, and caps its threads.
  - If the artifact is missing or invalid, or CUDA is selected, it logs a warning and falls back to FP32. With `AI_INT8_FALLBACK_TO_FP32=false`, it fails with `ModelLoadingError` instead.
  - A caller that passes `precision="int8"` explicitly (the benchmark) never falls back.
- FP32 and INT8 models are cached separately per process.

**Artifact layout and validity**

```text
<AI_MODEL_CACHE_DIR>/quantized/yolo11n_int8_openvino_model/
    yolo11n.xml  yolo11n.bin  metadata.yaml  quantization.json
```

Export runs in a staging directory. After export, the model is validated:

- it must contain `FakeQuantize` operations;
- its class names must match the FP32 checkpoint;
- one inference on `intel:cpu` must succeed.

`quantization.json` is written last and the folder is then swapped into place atomically. An
artifact is `VALID` only if all of the following hold:

- the manifest is present, with the right version, model key and format;
- validation passed;
- every listed file exists with its recorded size;
- the SHA-256 of the current FP32 checkpoint equals the one recorded at export. Otherwise the status is `SOURCE_CHANGED`.

Statuses are `VALID`, `NOT_EXPORTED`, `INVALID` and `SOURCE_CHANGED`. Model weights are git-ignored
(`model-cache/`) and are never committed.

## Export instructions

```powershell
cd ai-worker
# 1. Optional dependencies (after requirements-ai-cpu.txt and requirements-ai.txt).
#    With a uv-created venv: uv pip install --python .venv\Scripts\python.exe -r requirements-quantization.txt
.\.venv\Scripts\python.exe -m pip install -r requirements-quantization.txt

# 2. The FP32 checkpoint must be prepared first (export never downloads weights).
.\.venv\Scripts\python.exe -m app.cli models prepare --model yolo11n --device cpu

# 3a. Calibrate on frames sampled from a representative local video...
.\.venv\Scripts\python.exe -m app.cli models quantize --model yolo11n --imgsz 960 `
    --calibration-video temp\quantization-poc\source.mp4 --calibration-frames 300 --calibration-end 600
# 3b. ...or on an Ultralytics dataset YAML (its 'val' images; --fraction selects a subset).
.\.venv\Scripts\python.exe -m app.cli models quantize --model yolo11n --imgsz 960 --data path\to\data.yaml

# 4. Inspect (never loads anything).
.\.venv\Scripts\python.exe -m app.cli models int8-status --model yolo11n

# 5. Use it.
$env:AI_MODEL_PRECISION = "int8"
.\.venv\Scripts\python.exe -m app.cli detect --source temp\cli-input\street.mp4 --source-type local `
    --model yolo11n --tracking
```

Measured export time for `yolo11n` with 300 calibration images at 960 px: about 106 s (statistics
collection about 88 s) on the test host.

## Calibration requirements

- **Representative and unlabeled.** Use frames from the scenes the worker will process: same camera type, lighting, resolution and object sizes. Labels are not used, so no annotation work is needed.
- **About 300 images.** This is the Ultralytics recommendation; fewer triggers a warning. `--calibration-frames` samples them evenly from `[--calibration-start, --calibration-end)`.
- **Same image size as inference.** Calibrate at the `imgsz` that jobs will use (the default is 960), because activation ranges depend on scale.
- **Keep evaluation data separate.** The benchmark below calibrates on frames 0–599 of the source video and evaluates on frames 600–1191, which calibration never saw.
- **Re-export when the checkpoint changes.** The SHA-256 check marks a stale artifact as `SOURCE_CHANGED`, and with fallback enabled the loader then uses FP32.

## Benchmark commands

```powershell
cd ai-worker
# Same input, thresholds, classes, tracker settings and CPU budget for every configuration.
.\.venv\Scripts\python.exe -m benchmarks.quantization_benchmark `
    --video temp\quantization-poc\holdout.mp4 --model yolo11n --imgsz 960 --conf 0.25 `
    --classes 1,2,3,5,7 --cpus 4 --repeats 3 --include-openvino-fp32 `
    --output temp\quantization-poc\results-960-4cpu.json
```

**How the harness works**

- Each configuration runs in its own subprocess, which keeps peak-RAM figures clean. Runs alternate their order between repeats to spread thermal drift.
- `--cpus 4` pins the process to 4 physical cores. PyTorch threads and OpenVINO `INFERENCE_NUM_THREADS` are both set to 4, and the report records the values actually used.
- Frames go through `DetectionService.iter_frames` with an `ObjectTracker`: decode, letterbox, inference, NMS, ByteTrack and annotation. MP4 encoding and upload are excluded.
- The first 5 frames of each run are excluded as warm-up. Reported values are the median over repeats.

**Metrics**

| Metric | Source |
| --- | --- |
| Inference latency, mean and P95 | Ultralytics `speed["inference"]` per frame: model forward pass only |
| End-to-end FPS | Wall-clock time per yielded frame of the full tracking pipeline above |
| Artifact size | Bytes of `.pt` (FP32) or of the OpenVINO directory |
| Peak RAM | Process peak working set (`psutil` `peak_wset` on Windows, `ru_maxrss` on Linux), including Python, PyTorch and OpenVINO |
| Detections and tracks | Threshold detections per class (the product's definition), unique Track IDs, mean track length |
| Agreement with FP32 | Same-class boxes with IoU ≥ 0.5 (recall and precision against FP32), and **ID splits**: extra INT8 IDs assigned along one FP32 track |

**No ground truth exists for this video**, so mAP, IDF1, HOTA and true ID switches are **not
computed**. The agreement figures show how closely INT8 reproduces FP32, not whether either is
correct.

## Results

All numbers below are **measured** on 2026-11-15 with the command above.

**Setup**

| Item | Value |
| --- | --- |
| Host | AMD Ryzen 5 5600H, Windows 11, 4 physical cores pinned for every run |
| Runtimes | PyTorch 2.13.0+cpu; OpenVINO 2026.4.1 (4 threads) |
| Model and settings | `yolo11n`, `imgsz=960`, conf 0.25, Vehicles preset (classes 1, 2, 3, 5, 7), ByteTrack (track buffer 30) |
| Input | 592 frames, 1280×720 at 25 fps, from public video `eO19UTm93GQ` (frames 600–1191; calibration used frames 0–599) |
| Runs | 3 repeats per configuration; median reported; first 5 frames excluded |

The raw report is in
[`benchmarks/quantization-poc-yolo11n-960-4cpu.json`](benchmarks/quantization-poc-yolo11n-960-4cpu.json).

**Performance**

| | PyTorch FP32 (production) | OpenVINO FP32 | **OpenVINO INT8** |
| --- | ---: | ---: | ---: |
| Inference latency, mean | 83.0 ms | 60.2 ms | **36.3 ms** |
| Inference latency, P95 | 107.1 ms | 81.0 ms | **49.8 ms** |
| End-to-end FPS (tracking pipeline) | 10.5 (8.8–10.6) | 13.8 (13.6–14.8) | **20.7 (20.3–21.8)** |
| Speed-up vs PyTorch FP32, inference / end-to-end | 1.00× / 1.00× | 1.38× / 1.32× | **2.29× / 1.97×** |
| Model artifact | 5.61 MB (`.pt`) | 10.84 MB (IR) | **3.41 MB** (IR) |
| Peak process RAM | 504 MB | 618 MB | 593 MB |

**What the performance numbers mean**

- **Runtime vs quantization.** The INT8 gain comes from two sources:
  - switching runtime (PyTorch to OpenVINO FP32) gives **1.38×** inference speed;
  - quantization (OpenVINO FP32 to INT8) adds **1.66×** on top.
- **Artifact size.** The INT8 IR is **31 %** of the size of the FP32 IR. Against the `.pt` file the ratio is 61 %, but a `.pt` checkpoint is stored differently from an IR, so that comparison is less meaningful.
- **Peak RAM goes up, not down.** INT8 uses about +89 MB (+18 %) more than PyTorch FP32, because the process loads both the OpenVINO runtime and PyTorch (Ultralytics still uses PyTorch for pre- and post-processing). For a Nano model the weights are a small part of process memory, so the smaller artifact does not lower RAM.
- **End-to-end gains are smaller than inference gains.** Decode, letterbox, NMS, ByteTrack and annotation are unchanged and now take a larger share of each frame.

**Detections and tracking**

| | PyTorch FP32 | OpenVINO FP32 | OpenVINO INT8 |
| --- | ---: | ---: | ---: |
| Threshold detections, total | 10,251 | 10,251 | 10,537 (+2.8 %) |
| car / bus / truck / motorcycle | 7,972 / 1,873 / 405 / 1 | identical | 8,334 / 1,825 / 378 / 0 |
| Unique Track IDs | 106 | 106 | 104 |
| Mean track length (frames) | 101.2 | 101.2 | 106.0 |
| Tracks lasting ≥ 25 frames | 55 | 55 | 51 |
| Box recall / precision vs FP32 (same class, IoU ≥ 0.5) | — | 100 % / 100 % | 98.4 % / 95.7 % |
| FP32 tracks followed by one INT8 ID | — | 106 / 106 | 70 / 101 |
| ID splits vs FP32 (extra IDs along FP32 tracks) | — | 0 | 43 |

**What the tracking numbers mean**

- **OpenVINO FP32 matches PyTorch exactly** (same detections, same tracks). Every difference in the INT8 column therefore comes from quantization, not from the runtime or the pipeline integration.
- **INT8 detects slightly more boxes than FP32.** It finds 98.4 % of FP32's boxes, and 4.3 % of its boxes have no FP32 match. That is mostly extra cars and fewer buses and trucks, so some large vehicles may be classified differently.
- **INT8 tracks are not worse by the aggregate measures:** slightly fewer unique IDs, longer mean tracks.
- **INT8 tracks are clearly different from FP32 tracks.** 31 of the 101 comparable FP32 tracks receive more than one INT8 ID (43 extra IDs in total).
  - This measures *disagreement with FP32*, not errors: it also counts places where FP32 itself was the one that switched IDs.
  - Small changes in box scores near the confidence threshold change ByteTrack's matching, and the change carries forward along the track.
  - Whether INT8 tracking is better or worse can only be measured with ground-truth annotations (IDF1, HOTA, ID switches), which do not exist for this video.

**Conclusion.** On this host, OpenVINO INT8 roughly **doubles the throughput** of the tracking pipeline for `yolo11n` at 960 px and shrinks the model. The cost is a few-percent change in detections and noticeably different Track IDs. Before INT8 becomes the default, accuracy has to be validated on labelled data.

## Known limitations

- **One model, one video, one CPU.** Results are for `yolo11n` on 592 frames of one traffic video, on an AMD Zen 3 CPU without VNNI. Other model sizes, scenes and CPUs (especially Intel with VNNI or AMX) need their own measurements.
- **No accuracy measurement.** Agreement with FP32 is a proxy. A labelled validation set (for example COCO val or annotated project footage) is needed for mAP, and MOT-style annotations for IDF1, HOTA and ID switches.
- **Not in Docker yet.** `requirements-quantization.txt` is not installed in the worker images, and Compose does not pass `AI_MODEL_PRECISION`. Setting the variable in a container today would only log a fallback warning.
- **CPU only.** CUDA devices always use FP32.
- **Coupled to Ultralytics internals.** The thread cap replaces `backend.ov_compiled_model` and `backend.compile_model` of the Ultralytics OpenVINO backend. It is verified on 8.4.207; another layout is detected and left unchanged with a warning. Pin Ultralytics, or re-verify on upgrade.
- **Dynamic shapes.** Dynamic shapes keep `imgsz` semantics but can be slower than a static export at one fixed size. A static export was not benchmarked.
- **Extra load time.** INT8 load includes a warm-up and one recompile (a few seconds; measured `loadSeconds` is in the JSON report).
- **Windows precision hint.** On Windows, Ultralytics sets `INFERENCE_PRECISION_HINT=f32` for OpenVINO. INT8 layers still run in INT8, but non-quantized layers stay FP32.
- **Silent model substitution is avoided, not surfaced.** The loader logs which precision was used, but the result JSON and APIs do not report it yet.

## Next steps for frontend and backend integration (Phase 2)

1. **Worker images.** Install `requirements-quantization.txt` in the CPU image, behind a build argument. Pass `AI_MODEL_PRECISION`, `AI_INT8_FALLBACK_TO_FP32` and `AI_QUANTIZED_MODEL_DIR` through `compose.yaml`. Keep the default at `fp32`.
2. **Artifact lifecycle.** Run `models quantize` as an explicit operator step next to `models prepare`, stored in the `ai-model-cache` volume (read-only for `ai-live-worker`). Then measure INT8 for the Live Detection Nano models at `imgsz` 640, where latency matters most.
3. **Report the precision.** Add an optional `precision` field (`fp32` or `int8`) to the worker result and live responses. Add a nullable column through a new Flyway migration, and expose it read-only in the job details API. These are additive changes, so existing clients are unaffected.
4. **Model catalog.** Extend `GET /api/v1/models` with INT8 availability. The worker reports `int8-status`; the backend stores or relays it.
5. **Frontend.** Show a small "INT8" badge on job details and the Live Detection page. A per-job precision selector should come only after accuracy is validated on labelled data.
6. **Quality gate.** Before enabling INT8 by default, evaluate mAP on a labelled set, and IDF1/HOTA on annotated tracking footage. Set a maximum allowed drop against FP32 (for example ≤ 1 mAP point).
