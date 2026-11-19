# INT8 Quantization: Phase 2 (Validation and Docker Integration)

Status: **experimental, not enabled by default.** Branch `feature/quantization-phase2`, based on
Phase 1 (`feature/model-quantization-poc`; see [quantization-poc.md](quantization-poc.md), whose
results are kept unchanged). FP32 PyTorch remains the default everywhere. Spring Boot and React are
unchanged, and so is every public API response.

> **Update (Phase 2.5):** INT8 accuracy has since been measured against MOT17 pedestrian ground truth; see
> [quantization-accuracy-validation.md](quantization-accuracy-validation.md). Vehicle accuracy is still unvalidated.

Phase 2 covers three things:

1. Tooling to measure **real** tracking accuracy against MOTChallenge ground truth.
2. A wider benchmark: 2 models × 2 scenes × 3 runtimes, with variance.
3. Optional OpenVINO in the worker Docker image, tested end to end.

> **Headline:** INT8 is consistently **2.4–3.0× faster** for inference and **2.1–2.8× faster** end to
> end on this CPU. Its **tracking accuracy is unknown**: no ground-truth tracking annotations were
> available, so HOTA, MOTA, IDF1 and true ID switches were **not measured**. All quality figures below
> are *agreement with FP32*, not accuracy.

## 1. Architecture changes (ai-worker only)

| Area | Change |
| --- | --- |
| `benchmarks/mot.py` (new) | MOTChallenge I/O and validation (`seqinfo.ini`, `img1/`, `gt/gt.txt`), MOT17 distractor/ignore preprocessing, TrackEval metrics |
| `benchmarks/tracking_evaluation.py` (new) | Runs PyTorch FP32, OpenVINO FP32 and OpenVINO INT8 on MOT sequences; writes MOT-format predictions; reports HOTA/MOTA/IDF1/IDSW/precision/recall plus latency and FPS |
| `benchmarks/quantization_benchmark.py` | Runner reusable by the evaluator; per-repeat variance; separate runtime vs quantization gains; package versions in the report |
| `app/services/model_loader.py` | INT8 now falls back to FP32 (or fails if strict) when **OpenVINO is not installed** or the **INT8 runtime fails to initialise**. Phase 1 failed the job in that case. `LoadedModel.runtime` added. |
| Logging | Startup: `Model precision: …`. Per job: `Inference for <model> uses <FP32 PyTorch \| INT8 OpenVINO> on <device>`. Live: `Live model … ready on cpu (INT8, OpenVINO)`. A fallback is logged as a warning with its reason and is never reported as INT8. |
| `ai-worker/Dockerfile` | `ARG INSTALL_OPENVINO=false`; when `true`, installs `requirements-quantization.txt` in a **separate layer after** the PyTorch layer |
| `compose.yaml`, `.env.example` | `AI_WORKER_INSTALL_OPENVINO` (default `false`) build arg for the three Python services; `AI_MODEL_PRECISION` (default `fp32`), `AI_INT8_FALLBACK_TO_FP32` (default `true`), `AI_QUANTIZED_MODEL_DIR=/data/models/quantized` for the consumer and the live worker |
| `requirements-evaluation.txt` (new) | `trackeval==1.3.0`, `scipy`, `tabulate`; install with `--no-deps`, see §3 |
| Tests | `test_tracking_evaluation.py` (19), `test_docker_configuration.py` (6), +3 loader tests; fixed a stale integration-test fake (§7) |

## 2. Accuracy evaluation methodology

**Format.** MOTChallenge (MOT17 conventions):

- **Frames:** 1-based in files and 0-based in the pipeline.
- **Boxes:** top-left `x, y, w, h` in pixels.
- **GT columns:** `frame,id,x,y,w,h,conf,class,visibility`.
- **Predictions:** `frame,id,x,y,w,h,score,class,-1,-1`, in the TrackEval tracker layout `<dir>/<configuration>/data/<sequence>.txt`.

**Validation, enforced before anything runs:**

- `seqLength` must equal the number of images.
- Images must be named `000001…` with no gaps.
- The image size must match `seqinfo.ini`.
- GT frames must be integers within `1..seqLength`.
- Boxes must have a positive size.
- No ID may appear twice in one frame, in GT or in predictions.
- The pipeline must yield exactly `seqLength` frames.
- The class map must be consistent with the detected and evaluated classes.

**Preprocessing.** Same as TrackEval's `MotChallenge2DBox`:

- Tracker boxes matched (Hungarian, IoU ≥ 0.5) to MOT17 distractor classes (2, 7, 8, 12) are removed.
- GT with `conf = 0` is not scored.
- Only the evaluated class is scored. The default is MOT class 1 (pedestrian) ← COCO class 0 (person).
- Only boxes with a **confirmed** Track ID are written; unconfirmed boxes (`trackId` null) are not tracks.

**Metrics.** From **TrackEval 1.3.0**, the reference implementation of HOTA:

- HOTA (with DetA and AssA)
- CLEAR: MOTA, MOTP, IDSW, Frag, MT/ML, and detection precision and recall
- Identity: IDF1
- Multi-sequence totals use TrackEval's own `combine_sequences`.

No metric is re-implemented here. `motmetrics` 1.4.0 was evaluated and rejected: it calls `np.asfarray`, which NumPy 2 removed, and it has no HOTA.

**Evidence that the evaluator is correct**

| Check | Result |
| --- | --- |
| Hand-computed toy sequence (10 GT boxes, 1 miss, 1 ID switch) | MOTA 0.800, IDF1 0.7368 (=14/19), DetA 0.900, AssA 0.7333, HOTA 0.8124: all match by hand |
| Same sequence with `motmetrics` | Identical MOTA, IDF1 and IDSW |
| Synthetic MOT17-style sequence (30 frames, distractor, ignored GT, false positives, misses, ID switch) vs TrackEval's **official** `Evaluator` + `MotChallenge2DBox` | Identical HOTA 0.7922, MOTA 0.9083, IDF1 0.8595, IDSW 1, TP/FN/FP 116/4/6 (kept as a test) |
| **Plumbing check:** the real pipeline on `street.mp4` converted to a MOT sequence, with PyTorch FP32's own predictions as the reference | FP32 scores exactly HOTA = MOTA = IDF1 = 1.0 (242 TP, 0 FN, 0 FP). This proves frame indexing, image order, coordinates and the class map are consistent end to end. OpenVINO FP32 also scores 1.0. |

The plumbing check uses **FP32 output as a pseudo-label**. The INT8 number from that run (HOTA
0.957) is agreement with FP32 and is **not an accuracy result**. All the synthetic sequences test
software, not real-world tracking.

**Status: not run on real data.** No MOTChallenge or other annotated tracking dataset was available
locally, and the task rules prohibit downloading large datasets automatically (MOT17 is about 5.5 GB).
No ground truth was created by hand or derived from model output.

## 3. Dataset requirements and evaluation command

**What is needed**

- One or more MOTChallenge sequences, for example MOT17 `train` (which has public GT), or project footage annotated in the same format with a tool such as CVAT exporting "MOT 1.1".
- They must be **disjoint from the INT8 calibration frames**. Today's artifacts were calibrated on frames 0–599 of `eO19UTm93GQ`.
- For vehicle footage, annotate classes and pass `--detect-classes`, `--class-map` (COCO→GT) and `--eval-classes`.

```powershell
cd ai-worker
# TrackEval's metadata pulls opencv-python, which clashes with opencv-python-headless: install without deps.
.\.venv\Scripts\python.exe -m pip install --no-deps -r requirements-evaluation.txt
.\.venv\Scripts\python.exe -m benchmarks.tracking_evaluation `
    --sequences D:\data\MOT17\train\MOT17-02-FRCNN D:\data\MOT17\train\MOT17-09-FRCNN `
    --model yolo11n --imgsz 960 --cpus 4 --repeats 3 `
    --predictions-dir temp\eval\predictions --output temp\eval\report.json
```

The report holds per-sequence and `COMBINED` accuracy for each configuration,
`accuracyDeltaVsPytorchFp32`, and the same performance block as the benchmark.

## 4. Benchmark method and environment

| Item | Value |
| --- | --- |
| CPU | AMD Ryzen 5 5600H (Zen 3, 6 cores / 12 threads, AVX2, no AVX-512/VNNI), 13.9 GB RAM, Windows 11 (build 26200) |
| Software | Python 3.11, ultralytics-opencv-headless 8.4.207, torch 2.13.0+cpu, OpenVINO 2026.4.1, NNCF 3.4.0, numpy 2.3.5 |
| CPU budget | 4 physical cores pinned (one logical CPU per core); PyTorch threads 4; OpenVINO `INFERENCE_NUM_THREADS` 4 (read back from the compiled model) |
| Pipeline | `DetectionService.iter_frames` + ByteTrack (track buffer 30) + annotation; no MP4 encoding or upload |
| Settings | `imgsz=960`, conf 0.25; traffic: Vehicles (1, 2, 3, 5, 7); street: person + vehicles (0, 1, 2, 3, 5, 7) |
| INT8 artifacts | OpenVINO INT8, dynamic shapes, calibrated on 300 frames (0–599, stride 2) of public video `eO19UTm93GQ` at 960 px; yolo11n 101 and yolo26s 125 quantized ops |
| Runs | Each configuration in a fresh subprocess; 3 repeats (traffic) or 5 (street) in alternating order; first 5 frames excluded; median reported with [min–max] |

**Scenes.** Only local, already-available footage was used:

| Scene | Source | Frames | Character |
| --- | --- | --- | --- |
| Traffic | Frames 600–1191 of `eO19UTm93GQ`, 1280×720, 25 fps | 592 | Dense urban traffic (about 17 vehicles per frame), partial occlusions; same camera as calibration, but unseen frames |
| Street | `ai-worker/temp/cli-input/street.mp4`, 640×480, 15 fps | 60 | Sparse: a few pedestrians and a bus; **outside the calibration domain** |

No separate fast-motion or heavy-crowd clips were available, and none were downloaded.

**Models.** `yolo11n`, and `yolo26s` for YOLO26. YOLO26 **Nano** weights were not available
locally and were not downloaded.

**Rerun note.** The first yolo11n runs overlapped other work on the machine (test suites), which
caused large variance (for example FP32 91–106 ms). They were discarded and rerun on an idle machine;
only the reruns are reported. The yolo26s runs were made on an idle machine.

Raw reports: [`docs/benchmarks/phase2/`](benchmarks/phase2/).

```powershell
cd ai-worker
.\.venv\Scripts\python.exe -m app.cli models quantize --model yolo26s --imgsz 960 `
    --calibration-video temp\quantization-poc\source.mp4 --calibration-frames 300 --calibration-end 600
.\.venv\Scripts\python.exe -m benchmarks.quantization_benchmark --video temp\quantization-poc\holdout.mp4 `
    --model yolo26s --imgsz 960 --cpus 4 --repeats 3 --include-openvino-fp32 --classes 1,2,3,5,7 `
    --output temp\phase2\yolo26s-traffic-960.json
```

## 5. Results (measured)

### Performance

Inference is the median of per-run mean model latency (ms), with the range in brackets. FPS is the
end-to-end tracking pipeline.

| Model / scene | Runtime | Inference ms | P95 ms | FPS | Artifact | Peak RAM |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| yolo11n / traffic | PyTorch FP32 | 89.3 [88.0–92.1] | 110.0 | 9.75 [9.46–9.84] | 5.61 MB | 481 MiB |
| | OpenVINO FP32 | 62.0 [59.9–63.4] | 84.3 | 13.44 [13.11–13.83] | 10.84 MB | 588 MiB |
| | **OpenVINO INT8** | **36.9** [35.2–37.3] | **52.9** | **20.25** [20.08–21.40] | **3.41 MB** | 565 MiB |
| yolo26s / traffic | PyTorch FP32 | 233.7 [223.0–235.7] | 310.1 | 4.05 [4.01–4.23] | 20.42 MB | 589 MiB |
| | OpenVINO FP32 | 180.8 [163.2–182.9] | 248.1 | 5.14 [5.08–5.67] | 38.41 MB | 691 MiB |
| | **OpenVINO INT8** | **78.2** [75.5–81.3] | **109.3** | **11.10** [10.69–11.50] | **10.47 MB** | 608 MiB |
| yolo11n / street ⚠ | PyTorch FP32 | 145.0 [112.0–191.5] | 188.3 | 6.42 [4.94–8.28] | 5.61 MB | 497 MiB |
| | OpenVINO FP32 | 87.4 [76.9–102.8] | 108.2 | 10.23 [8.74–11.57] | 10.84 MB | 595 MiB |
| | **OpenVINO INT8** | **55.6** [51.1–65.9] | **89.2** | **15.08** [12.83–16.35] | **3.41 MB** | 559 MiB |
| yolo26s / street | PyTorch FP32 | 312.9 [304.1–325.7] | 389.1 | 3.10 [2.98–3.19] | 20.42 MB | 613 MiB |
| | OpenVINO FP32 | 223.3 [210.7–231.2] | 316.7 | 4.29 [4.16–4.55] | 38.41 MB | 711 MiB |
| | **OpenVINO INT8** | **107.8** [104.9–113.1] | **142.3** | **8.59** [8.12–8.74] | **10.47 MB** | 614 MiB |

⚠ The yolo11n street run has only 55 measured frames, and its variance stays high even on an idle
machine (PyTorch FP32 stdev 29 ms). Treat its ratios as indicative only. The street frames are 4:3,
so they letterbox to 960×736 rather than 960×544, which explains why they are slower per frame than
traffic.

**Speed-up split** (ratios of medians; inference / end to end):

| Model / scene | Runtime gain (PyTorch → OpenVINO FP32) | Quantization gain (OpenVINO FP32 → INT8) | Total |
| --- | ---: | ---: | ---: |
| yolo11n / traffic | 1.44× / 1.38× | 1.68× / 1.51× | **2.42× / 2.08×** |
| yolo26s / traffic | 1.29× / 1.27× | 2.31× / 2.16× | **2.99× / 2.74×** |
| yolo11n / street ⚠ | 1.66× / 1.59× | 1.57× / 1.47× | 2.61× / 2.35× |
| yolo26s / street | 1.40× / 1.38× | 2.07× / 2.00× | **2.90× / 2.77×** |

**What the performance numbers show**

- **Gains are consistent.** INT8 is the fastest configuration in every scene and every repeat.
- **Quantization matters more for larger models.** The quantization gain is larger for yolo26s (2.1–2.3×) than for yolo11n (about 1.6×), because the Small model is more compute-bound.
- **The yolo11n traffic result reproduces Phase 1:** inference 36.9 vs 36.3 ms, 20.25 vs 20.7 FPS.
- **Artifact size.** INT8 is about 31 % of the OpenVINO FP32 IR for yolo11n and 27 % for yolo26s.
- **Peak RAM does not drop.** INT8 uses more than PyTorch FP32: +84 MiB for yolo11n and +19 MiB for yolo26s on traffic. The process loads both OpenVINO and PyTorch.
- **INT8 load is slower:** about 7–8 s, against about 2 s for PyTorch. It includes a warm-up and a recompile to cap threads.

### Detections and tracking: agreement with FP32 (not accuracy)

| Model / scene | Detections FP32 → INT8 | Unique IDs FP32 → INT8 | Mean track length FP32 → INT8 | Box recall / precision vs FP32 | FP32 tracks followed by one INT8 ID | ID splits vs FP32 |
| --- | --- | --- | --- | --- | --- | --- |
| yolo11n / traffic | 10,251 → 10,537 (+2.8 %) | 106 → 104 | 101.2 → 106.0 | 98.4 % / 95.7 % | 70 / 101 | 43 |
| yolo26s / traffic | 10,500 → 10,213 (−2.7 %) | 74 → 76 | 147.4 → 141.4 | 95.6 % / 98.3 % | 55 / 70 | 20 |
| yolo11n / street | 331 → 336 | 6 → 6 | 55.3 → 58.5 | 95.5 % / 94.1 % | 4 / 6 | 2 |
| yolo26s / street | 319 → 352 (+10.3 %) | **6 → 11** | **53.3 → 31.7** | 98.4 % / **89.2 %** | 4 / 6 | 6 |

**What the agreement numbers show**

- **OpenVINO FP32 is identical to PyTorch FP32 in all four cases** (100 %/100 %, 0 splits). Every difference above comes from quantization.
- **Results are deterministic.** All 12 configurations produced identical outputs on every repeat.
- **INT8 shifts detections near the threshold by a few percent.** Track IDs diverge from FP32 on 21–33 % of the comparable FP32 tracks, consistently across models and scenes.
- **The out-of-domain scene is the clearest warning.** With yolo26s on the street clip, INT8 starts nearly twice as many tracks (11 vs 6), each about 40 % shorter, and 10.8 % of its boxes have no FP32 counterpart. Calibration on traffic frames may not transfer to other scenes.
- **None of this is an accuracy measurement.** FP32 is not ground truth: these numbers show *disagreement*, not which runtime is right.

## 6. Docker integration

**Build and run options**

- **Default (unchanged):** `AI_WORKER_INSTALL_OPENVINO=false`, `AI_MODEL_PRECISION=fp32`.
- **Opt-in:**
  1. Set `AI_WORKER_INSTALL_OPENVINO=true` and rebuild.
  2. Export artifacts once.
  3. Set `AI_MODEL_PRECISION=int8` and recreate the AI services.

```powershell
# 1. Build the AI images with OpenVINO (adds about 0.55 GB).
$env:AI_WORKER_INSTALL_OPENVINO = "true"
docker compose build ai-worker ai-detection-consumer ai-live-worker
# 2. Explicit, one-time export into the persistent ai-model-cache volume. Never runs on startup.
#    Copy a representative calibration clip in first, then remove it.
docker compose cp .\calibration.mp4 ai-detection-consumer:/data/temp/calibration.mp4
docker compose exec ai-detection-consumer python -m app.cli models quantize --model yolo11n `
    --imgsz 960 --calibration-video /data/temp/calibration.mp4 --calibration-frames 300
docker compose exec ai-detection-consumer python -m app.cli models int8-status
# 3. Switch precision (consumer and live worker), then confirm in the logs.
$env:AI_MODEL_PRECISION = "int8"
docker compose up -d ai-detection-consumer ai-live-worker
docker compose logs ai-detection-consumer | Select-String "Model precision|Inference for"
```

From Git Bash, set `MSYS_NO_PATHCONV=1`; otherwise `/data/...` arguments are rewritten to Windows paths.

**Verified in Docker** (isolated project `yvs-int8-test`, its own ports 2xxxx and volumes; the
`yolo-vision-studio` stack and its volumes were not touched)

| Check | Result |
| --- | --- |
| Default image from this branch (`INSTALL_OPENVINO=false`) | 2.84 GB, the same as before. The PyTorch layer was reused from cache, and OpenVINO is not installed. |
| OpenVINO image (`INSTALL_OPENVINO=true`) | 3.39 GB (+0.55 GB), `pip check` clean. OpenVINO 2026.4.1 sees the CPU with `INT8` capability. |
| Consumer startup log, INT8 configured | `Model precision: INT8 requested (OpenVINO installed: True, fallback to FP32: True, artifacts: /data/models/quantized)` |
| Job A: INT8 requested, no artifact (REST → RabbitMQ → worker → MinIO) | COMPLETED; warning `INT8 is unavailable (NOT_EXPORTED…)`; `uses FP32 PyTorch on cpu`; MP4 served (HTTP 200) |
| INT8 export inside the container (explicit `models quantize`) | VALID, 101 quantized ops, 3.38 MB, in the persistent volume |
| Job B: INT8 artifact present, same running worker | COMPLETED; `Inference for yolo11n uses INT8 OpenVINO on intel:cpu`; 15,852 detections, 147 tracks |
| Job C: `AI_MODEL_PRECISION=fp32` | COMPLETED; `FP32 PyTorch`; results **identical to Job A** (15,478 detections, 151 tracks, same MP4 size). The fallback really ran FP32. |
| API contract | Job A, B and C responses have identical structure; nothing mentions precision |
| Default image + INT8 requested | Fallback with `OpenVINO is not installed in this image`; strict mode → `ModelLoadingError` |
| OpenVINO image + INT8 from a **read-only** cache mount | INT8 OpenVINO on `intel:cpu` |
| Live worker with INT8 | Startup log OK; `Live model yolo11n ready on cpu (INT8, OpenVINO)`; 10 tracking frames via `/internal/live/infer` with persistent Track IDs 1–9; session closed (204); response keys unchanged |
| Worker broker/storage integration tests (real RabbitMQ and MinIO) | 5/5 pass after the fixture fix (§7) |

**Rollback**

1. Set `AI_MODEL_PRECISION=fp32` (or remove it) and run `docker compose up -d ai-detection-consumer ai-live-worker`. The next job uses FP32; check `Model precision: FP32 (PyTorch)` in the logs.
2. Optionally return to the smaller image: set `AI_WORKER_INSTALL_OPENVINO=false` and rebuild the three AI services.
3. INT8 artifacts can stay in the volume (they are ignored under FP32), or be removed with `docker compose exec ai-detection-consumer rm -r /data/models/quantized/<model>_int8_openvino_model`.
4. No database, API or frontend change is involved, so there is nothing to migrate back.

## 7. Test evidence

| Suite | Result |
| --- | --- |
| AI worker unit tests (`python -m pytest`, from `ai-worker/`) | **470 passed**, 10 skipped: 5 need FFmpeg (absent on the Windows host; CI installs it) and 5 need `IT_*` broker settings |
| AI worker integration tests against real RabbitMQ and MinIO | **5 passed** after fixing the test fake. Before the fix: 4 failed / 1 passed, **identically on `main`**: the fake pipeline result lacked `processing_mode`, which the job processor checks since ByteTrack (`0f2af50`). This was a pre-existing test bug, not a Phase 2 regression. |
| Docker end-to-end (§6) | All checks passed |
| Backend and frontend | Not rerun: no files under `backend/` or `frontend/` differ from `main` |

New tests cover:

- FP32 default and precision parsing
- INT8 artifact valid, missing, invalid and stale
- CPU-only restriction
- Strict versus fallback loading
- OpenVINO missing, and runtime initialisation failure
- OpenVINO thread cap
- Effective precision and runtime reporting
- MOTChallenge format validation, frame/coordinate/class conversion, and the TrackEval cross-checks
- Docker and Compose defaults

## 8. Known limitations

- **No ground-truth accuracy.** HOTA, MOTA, IDF1 and IDSW are implemented and verified, but not measured on real data.
- **Narrow benchmark coverage.** One CPU (AMD without VNNI), two scenes (one of them only 60 frames), two models. YOLO26 Nano was not available. There were no dedicated fast-motion or crowd clips.
- **Calibration domain.** Artifacts are calibrated on one traffic video, and agreement drops on the out-of-domain street clip (especially yolo26s).
- **RAM.** INT8 does not reduce RAM; it adds about 20–85 MiB per process. The image is 0.55 GB larger.
- **Ultralytics coupling.** The OpenVINO thread cap depends on Ultralytics internals and is verified on 8.4.207 only. An unknown backend layout is left unchanged and logged.
- **Precision only in logs.** Results and APIs do not record precision, deliberately for now (no contract change). Logs are the only record.
- **Dynamic shapes.** Static exports were not compared.
- **Integration fixture lag.** The broker/storage integration tests skip in CI without `IT_*` settings, which is how the stale fixture stayed unnoticed. Consider a CI job with service containers.

## 9. Recommendations

**Acceptance criteria for enabling INT8 per model.** These are proposed for review, not universal thresholds:

| Criterion | Proposed gate | Status |
| --- | --- | --- |
| Performance | INT8 end-to-end FPS ≥ 1.5× PyTorch FP32 on the target hardware, every scene, non-overlapping ranges | **Met** on this host (2.1–2.8×; 2.35× on the noisy street run) |
| Tracking accuracy | On annotated sequences disjoint from calibration: ΔHOTA and ΔIDF1 ≥ −1.0 point, ΔMOTA ≥ −1.0 point vs FP32, no class-specific recall drop > 2 points | **Not measured**, blocking |
| Robustness | Same gates on at least one out-of-calibration-domain scene | **Not measured**; agreement data suggests risk |
| Operations | Docker opt-in, fallback, logging, rollback verified | **Met** |

The tolerance should be confirmed by the product owner against how track counts are used.
±1 point is a common engineering margin, not a standard.

**Answers to the Phase 2 questions**

- *Consistent performance gains?* Yes, on this CPU: 2.4–3.0× inference and 2.1–2.8× end to end, every run.
- *Tracking quality acceptable?* Unknown. It must be evaluated on ground truth before any default change.
- *Do YOLO26 results match YOLO11 trends?* Yes for speed, with a larger quantization gain. The agreement pattern is similar, but yolo26s fragments more on the out-of-domain clip.
- *Can Docker run INT8 reliably?* Yes in the tested flows (export, jobs, live, fallback, strict mode, read-only cache).
- *Is more calibration needed?* Probably. Calibrate on a mix of scenes the worker actually sees (several cameras, day and night, sparse and dense), then repeat the agreement and ground-truth evaluation.
- *QAT?* Only if post-training INT8 misses the accuracy gate after better calibration. Ultralytics supports QAT (`quantize=8` in training), but it requires training data and a training pipeline this project does not have.

**Phase 3 recommendation: not ready to expose precision selection in Spring Boot or React.**

1. Run `benchmarks.tracking_evaluation` on MOT17 `train` (pedestrians) and on a small annotated set of project traffic footage (vehicles), disjoint from calibration.
2. Recalibrate with multi-scene data, and re-measure.
3. Benchmark on the deployment CPU (ideally Intel with VNNI or AMX).

Only if the accuracy gate passes:

4. Add an optional `precision` field to worker results.
5. Add a nullable column through a new Flyway migration.
6. Expose it read-only in the job details API and as a UI badge.
7. Add per-job selection last.
