# INT8 Quantization: Ground-Truth Accuracy Validation (Phase 2.5)

Branch `feature/quantization-accuracy-validation`, based on Phase 2 (`dd2d99e`). Earlier phases are
documented in [quantization-poc.md](quantization-poc.md) and
[quantization-phase2.md](quantization-phase2.md).

FP32 PyTorch remains the default. Spring Boot, React, Docker and Compose are unchanged in this phase.

**Scales.** All accuracy metrics are percentages (0–100). **Δ** is an **absolute difference in
percentage points** against PyTorch FP32 unless marked "relative". IDSW, FP and FN are counts. FP32 is
the comparison baseline, **not ground truth**: every accuracy number below is scored against human
MOT17 annotations.

> **Result.** On 5 held-out MOT17 sequences (pedestrians), OpenVINO INT8 (original traffic
> calibration) stays within 0.8 points of FP32 on HOTA, MOTA and IDF1, has 1 more ID switch (485 → 486),
> and is 2.34× faster end to end. The multi-source calibration raises HOTA/IDF1 but lowers MOTA and
> precision, adds ID switches, and fails the per-sequence floor; it is **not** adopted.
> **Vehicle tracking remains unvalidated.**

## 1. Dataset

| Item | Value |
| --- | --- |
| Dataset | **MOT17** training set, [motchallenge.net/data/MOT17](https://motchallenge.net/data/MOT17/) (Milan et al., *MOT16: A Benchmark for Multi-Object Tracking*, 2016) |
| License | **CC BY-NC-SA 3.0**: non-commercial use with attribution. The data is kept in git-ignored `ai-worker/temp/datasets/` and is **not committed or redistributed**. |
| Acquisition | `python -m benchmarks.fetch_mot17` reads the official 5.86 GB `MOT17.zip` through HTTP range requests (zip index plus the selected members only). Every file is verified by the zip's CRC-32. Total transferred: about 830 MB (474 MB evaluation and 352 MB calibration samples). |
| Evaluation sequences | `-FRCNN` copies; images and GT are identical across the DPM/FRCNN/SDP copies, and public detections are not used |
| GT used | Class 1 (pedestrian) with `conf=1` is scored. Distractors 2/7/8/12 (person on vehicle, static person, distractor, reflection) are handled as in the official devkit. |

| Sequence | Frames | Resolution | Camera | Scored boxes | GT tracks | People per frame | Small (< 10 % of height) | Visibility < 0.5 |
| --- | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: |
| MOT17-02 | 600 | 1920×1080 | static, street | 18,581 | 62 | 31.0 | 57 % | 61 % |
| MOT17-05 | 837 | 640×480 | moving, street | 6,917 | 133 | 8.3 | 4 % | 47 % |
| MOT17-09 | 525 | 1920×1080 | static, square | 5,325 | 26 | 10.1 | 0 % | 41 % |
| MOT17-10 | 654 | 1920×1080 | moving, night | 12,839 | 57 | 19.6 | 43 % | 29 % |
| MOT17-11 | 900 | 1920×1080 | moving, indoor mall | 9,436 | 75 | 10.5 | 10 % | 35 % |
| **Total** | **3,516** | | | **53,098** | **353** | | | |

**Limitations**

- **Pedestrians only.** MOT17 marks every car box `conf=0`, so it cannot score vehicles. Annotated vehicle tracking datasets (KITTI Tracking, UA-DETRAC, BDD100K MOT) require registration or license acceptance and were not downloaded. **Vehicle tracking, this product's default preset, is not validated.**
- **Generalisation.** The MOT17 training set is public and widely used.
- **Model coverage.** YOLO26 was not evaluated against ground truth in this phase.

## 2. Methodology

- **Pipeline:** `benchmarks.tracking_evaluation` runs the production `DetectionService` and ByteTrack. Each configuration runs in its own subprocess with identical:
  - frames (the sequence's `img1/`);
  - weights (`yolo11n.pt`, SHA-256 `0ebbc80d…44ee1`);
  - `imgsz=960`, confidence 0.25, COCO class 0 → MOT class 1;
  - ByteTrack settings (track buffer 30, match 0.8);
  - 4 pinned physical cores (PyTorch 4 threads, OpenVINO 4 threads).
- **Configurations:** PyTorch FP32, OpenVINO FP32, OpenVINO INT8 (original), and OpenVINO INT8 (multi-source, selected with `AI_QUANTIZED_MODEL_DIR`).
- **Metrics:** TrackEval 1.3.0 HOTA, CLEAR (MOTA, IDSW, FP, FN, Frag) and Identity (IDF1). Combined scores use TrackEval's `combine_sequences`. Detection precision = TP/(TP+FP) and recall = TP/(TP+FN), both at IoU ≥ 0.5 (CLEAR matching).
- **Checks on the real data before reporting:**
  - each sequence's GT scored as tracker output gives exactly 1.0 HOTA/MOTA/IDF1 (53,098 TP, 0 FP/FN);
  - frame counts equal `seqLength`;
  - the evaluator matches TrackEval's official `MotChallenge2DBox` on a synthetic sequence (test);
  - OpenVINO FP32 reproduces PyTorch FP32 exactly on every sequence.
- **Determinism:** every configuration produced identical tracks across its 2 timing repeats, so accuracy has no run-to-run variance. Per-sequence differences of 1–2 points in **both** directions between FP32 and INT8 are therefore not measurement noise. They are real, but small, divergences: tiny score changes propagate through threshold decisions and ByteTrack association. The combined score over 53,098 boxes is the reliable signal.
- **Calibration and evaluation are disjoint:**
  - Original INT8: 300 frames of the traffic video `eO19UTm93GQ` (frames 0–599).
  - Multi-source INT8: 100 traffic frames (0–594), 100 frames of **MOT17-04** and 100 of **MOT17-13**.
  - Neither MOT17 calibration sequence is in the evaluation set, but both share MOT17's domain, which favours the multi-source artifact.

```powershell
cd ai-worker
.\.venv\Scripts\python.exe -m pip install --no-deps -r requirements-evaluation.txt
.\.venv\Scripts\python.exe -m benchmarks.fetch_mot17 --sequences MOT17-02 MOT17-05 MOT17-09 MOT17-10 MOT17-11 `
    --dest temp\datasets\MOT17 --max-mb 500
.\.venv\Scripts\python.exe -m benchmarks.tracking_evaluation --sequences temp\datasets\MOT17 --model yolo11n `
    --imgsz 960 --conf 0.25 --cpus 4 --repeats 2 --predictions-dir temp\accuracy\yolo11n\predictions `
    --output temp\accuracy\yolo11n\report.json
# Multi-source artifact: separate directory, original preserved.
.\.venv\Scripts\python.exe -m benchmarks.fetch_mot17 --sequences MOT17-04 --every 10 --dest temp\datasets\MOT17-calibration
.\.venv\Scripts\python.exe -m benchmarks.fetch_mot17 --sequences MOT17-13 --every 7 --dest temp\datasets\MOT17-calibration
$env:AI_QUANTIZED_MODEL_DIR = "model-cache\quantized-diverse"
.\.venv\Scripts\python.exe -m app.cli models quantize --model yolo11n --imgsz 960 --calibration-frames 300 `
    --calibration-images temp\datasets\traffic-calibration temp\datasets\MOT17-calibration\MOT17-04-FRCNN\img1 `
    temp\datasets\MOT17-calibration\MOT17-13-FRCNN\img1
.\.venv\Scripts\python.exe -m benchmarks.tracking_evaluation --sequences temp\datasets\MOT17 --model yolo11n `
    --imgsz 960 --cpus 4 --repeats 2 --configurations int8 --int8-label int8-diverse `
    --predictions-dir temp\accuracy\yolo11n\predictions --output temp\accuracy\yolo11n\report-int8-diverse.json
Remove-Item Env:AI_QUANTIZED_MODEL_DIR
.\.venv\Scripts\python.exe -m benchmarks.quantization_error_analysis --sequences temp\datasets\MOT17 `
    --predictions-dir temp\accuracy\yolo11n\predictions --candidates int8 int8-diverse ov-fp32 `
    --output temp\accuracy\yolo11n\analysis.json
```

Raw reports: [`docs/benchmarks/accuracy/`](benchmarks/accuracy/). This folder contains:

- the evaluation reports;
- the error analysis;
- both artifact manifests, with calibration provenance and the source checkpoint hash.

## 3. Accuracy against MOT17 ground truth (yolo11n, pedestrians)

### Combined (5 sequences, 3,516 frames, 53,098 GT boxes)

| Metric | PyTorch FP32 | OpenVINO FP32 | INT8 original | Δ | INT8 multi-source | Δ |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| HOTA | 38.50 | 38.50 | 37.91 | −0.59 | 39.04 | +0.54 |
| DetA | 38.59 | 38.59 | 38.53 | −0.06 | 38.64 | +0.05 |
| AssA | 38.99 | 38.99 | 37.90 | −1.09 | 40.13 | +1.14 |
| MOTA | 40.54 | 40.54 | 40.51 | −0.03 | 39.92 | −0.62 |
| IDF1 | 44.97 | 44.97 | 44.21 | −0.76 | 45.70 | +0.73 |
| IDSW (count) | 485 | 485 | 486 | +1 (+0.2 % rel.) | 516 | +31 (+6.4 % rel.) |
| Precision | 84.54 | 84.54 | 84.48 | −0.06 | 83.22 | −1.32 |
| Recall | 50.73 | 50.73 | 50.75 | +0.02 | 51.22 | +0.49 |
| FP (count) | 4,924 | 4,924 | 4,950 | +26 | 5,485 | +561 (+11.4 % rel.) |
| FN (count) | 26,164 | 26,164 | 26,150 | −14 | 25,899 | −265 |
| Fragmentations | 719 | 719 | 740 | +21 | 797 | +78 |

### Per sequence (Δ against PyTorch FP32, in points)

| Sequence | Config | HOTA | MOTA | IDF1 | IDSW | Precision | Recall |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| MOT17-02 | FP32 | 31.73 | 27.77 | 36.69 | 77 | 84.80 | 34.34 |
| | INT8 original | 30.49 (−1.24) | 27.83 (+0.06) | 36.03 (−0.66) | 81 | 84.56 | 34.58 |
| | INT8 multi-source | 31.37 (−0.36) | 27.80 (+0.03) | 36.49 (−0.20) | 80 | 82.82 | 35.62 |
| MOT17-05 | FP32 | 41.32 | 44.14 | 55.17 | 129 | 80.09 | 61.23 |
| | INT8 original | 41.13 (−0.19) | 42.75 (−1.39) | 54.48 (−0.69) | 123 | 79.13 | 60.47 |
| | INT8 multi-source | 40.23 (−1.09) | **38.83 (−5.31)** | 53.10 (−2.07) | 131 | **75.87** | 59.72 |
| MOT17-09 | FP32 | 43.22 | 57.88 | 49.12 | 77 | 85.00 | 72.04 |
| | INT8 original | 42.59 (−0.63) | 59.12 (+1.24) | 47.71 (−1.41) | 74 | 86.55 | 71.64 |
| | INT8 multi-source | 44.48 (+1.26) | 58.27 (+0.39) | 51.91 (+2.79) | 71 | 85.39 | 71.91 |
| MOT17-10 | FP32 | 33.03 | 41.79 | 40.16 | 162 | 87.70 | 50.07 |
| | INT8 original | 32.87 (−0.16) | 41.47 (−0.32) | 39.48 (−0.68) | 169 | 87.00 | 50.30 |
| | INT8 multi-source | 34.31 (+1.28) | 41.53 (−0.26) | 41.30 (+1.14) | **195** | 86.52 | 50.99 |
| MOT17-11 | FP32 | 49.52 | 51.56 | 53.87 | 40 | 84.06 | 64.15 |
| | INT8 original | 49.14 (−0.38) | 52.06 (+0.50) | 53.25 (−0.62) | 39 | 84.46 | 64.30 |
| | INT8 multi-source | 51.28 (+1.76) | 52.06 (+0.50) | 56.66 (+2.79) | 39 | 84.40 | 64.37 |

FP32 itself scores low on absolute terms (HOTA 38.5). Most misses are small or occluded people: recall
is 18 % for people under 10 % of the image height and 12 % at visibility < 0.25. That is a property of
the Nano model at 960 px, not of quantization.

## 4. Error analysis (where INT8 differs, judged against GT)

From `benchmarks.quantization_error_analysis` (IoU ≥ 0.5 per-frame matching with the same MOT17
preprocessing; its overall recall is 50.76 %, within 0.03 points of TrackEval's).

**Recall by condition** (%, all 53,098 GT boxes)

| Condition | GT boxes | FP32 | INT8 original | INT8 multi-source |
| --- | ---: | ---: | ---: | ---: |
| Height < 10 % of the image (small) | 17,285 | 18.25 | 19.10 | 19.86 |
| Height 10–20 % | 14,400 | 50.61 | 50.17 | 51.43 |
| Height 20–40 % | 10,787 | 71.66 | 71.32 | 71.51 |
| Height ≥ 40 % | 10,626 | 82.65 | 82.39 | 81.72 |
| Visibility < 0.25 (heavily occluded) | 17,115 | 12.35 | 12.32 | 12.99 |
| Visibility 0.25–0.5 | 6,565 | 39.66 | 39.16 | 39.76 |
| Visibility 0.5–0.75 | 6,909 | 59.70 | 59.33 | 59.26 |
| Visibility ≥ 0.75 | 22,509 | 80.47 | 80.83 | 81.35 |
| < 10 people in the frame | 9,025 | 68.98 | 68.54 | 67.88 |
| 30 or more people (crowded) | 14,517 | 33.56 | 33.98 | 35.12 |

**Disagreements with FP32, classified by ground truth**

| | INT8 original | INT8 multi-source |
| --- | ---: | ---: |
| Boxes both agree on | 30,728 | 30,981 |
| INT8-only, correct (miss recovered) | 500 | 684 |
| FP32-only, correct (detection lost) | 465 | 311 |
| INT8-only, false positive (new FP) | 670 | 1,019 |
| FP32-only, false positive (FP removed) | 665 | 566 |
| **Net effect** | **+35 TP, +5 FP** | **+373 TP, +453 FP** |
| Score change on agreed boxes (INT8 − FP32): mean / median / mean absolute | −0.002 / −0.002 / 0.017 | **+0.006 / +0.004** / 0.016 |
| Mean IoU of INT8 box with FP32 box | 0.971 | 0.969 |
| Mean IoU of matches with GT (FP32 0.796) | 0.794 | 0.793 |
| Disagreeing boxes with score in [0.25, 0.35) (all true positives: 3.7 %) | 22–28 % | 19–28 % |
| GT tracks with more / fewer / the same ID changes as FP32 | 45 / 52 / 189 | 55 / 47 / 185 |

**Findings**

- **Quantization noise, not bias (original artifact).**
  - On agreed boxes, INT8 scores differ from FP32 by ±0.017 on average, with no systematic shift (−0.002).
  - Localisation is preserved: IoU with the FP32 box is 0.971, and the match quality to GT is unchanged.
  - Errors cancel: INT8 recovers 500 misses and loses 465; it adds 670 false positives and removes 665.
- **Threshold sensitivity amplifies the noise.** Boxes where INT8 and FP32 disagree are 6–8× more likely to sit just above the 0.25 threshold than true positives in general (22–28 % vs 3.7 %). The remaining disagreements come from **tracker behaviour**: a slightly different score or box changes ByteTrack's association or track confirmation, and that difference persists along the track. This explains why AssA moves (−1.09 points) more than DetA (−0.06).
- **Small objects and occlusion are not degraded by INT8.** Small-person recall is +0.85 points (original) and +1.61 (multi-source). Heavily occluded recall is unchanged (−0.03 / +0.64). The small losses fall on medium and large people (−0.3 to −0.9 points).
- **ID switches.** No systematic change for the original artifact: 485 → 486 IDSW; more ID changes on 45 GT tracks, fewer on 52. The multi-source artifact adds 31 IDSW (+6.4 % relative), concentrated in MOT17-10 (night; 162 → 195) and MOT17-05.
- **Calibration data shifts the operating point.** The multi-source calibration raises scores systematically (+0.006 mean), so more boxes pass the 0.25 threshold. Recall goes up (+0.49; +1.6 for small people and crowds), but so do false positives (+11 % relative), and precision drops (−1.32). Association metrics (HOTA, IDF1, AssA) rise while MOTA and IDSW worsen. It is a different trade-off, not a uniformly better model.
- **The multi-source gains may be inflated by domain overlap.** That calibration includes two other MOT17 sequences. Even so, it still failed on MOT17-05 (MOTA −5.31, precision −4.22), a low-resolution moving-camera scene unlike any of its calibration sources.

ByteTrack thresholds were **not** changed. Re-tuning the confidence threshold would trade precision against recall for every runtime equally, and would hide the quantization effect.

## 5. Performance (same runs, 4 pinned cores, imgsz 960)

Frame-weighted over all 3,516 frames. Per-sequence medians and ranges are in the JSON reports.

| | PyTorch FP32 | OpenVINO FP32 | INT8 original | INT8 multi-source |
| --- | ---: | ---: | ---: | ---: |
| End-to-end tracking FPS | 7.83 | 11.37 | **18.34** | **18.41** |
| Mean inference latency | 105.3 ms | 75.7 ms | 42.9 ms | 43.2 ms |
| P95 inference latency (per-sequence range) | 125.8–230.3 ms | 92.3–144.3 ms | 51.6–69.8 ms | 48.4–77.5 ms |
| Speed-up vs PyTorch FP32 (end to end) | 1.00× | 1.45× | **2.34×** | **2.35×** |
| Artifact | 5.61 MB | 10.84 MB | 3.41 MB | 3.41 MB |
| Peak process RAM | 464 MiB | 564 MiB | 536 MiB | 539 MiB |

- **Both INT8 artifacts have the same speed.** They share the same graph (101 quantized ops); per-sequence FPS ranges overlap.
- **Same trend as Phase 2:** runtime gain about 1.45×, quantization gain about 1.6×, on top of each other.
- **RAM is higher than PyTorch FP32** (+72 MiB), as already measured in Phase 2.

**Artifact provenance**

| Artifact | Calibration | `yolo11n.xml` SHA-256 | `yolo11n.bin` SHA-256 |
| --- | --- | --- | --- |
| `model-cache/quantized/` (original, unchanged) | 300 traffic frames (`eO19UTm93GQ` 0–599) | `c9cf26af…a06df7` | `58f1c775…c31a50` |
| `model-cache/quantized-diverse/` (experimental) | 100 traffic + 100 `MOT17-04-FRCNN/img1` + 100 `MOT17-13-FRCNN/img1` (file-list hashes in the manifest) | `e3d25b7a…2614ae` | `7173bdd9…c3f0` |

## 6. Regression tests

| Suite | Result |
| --- | --- |
| AI worker unit tests (`python -m pytest`, from `ai-worker/`) | **475 passed**, 0 failed, 10 skipped (5 need FFmpeg, absent on the Windows host; 5 need `IT_*` broker settings) |
| Broker/storage integration tests | Not rerun in this phase. The job-processing code is unchanged since Phase 2, where they passed 5/5 against real RabbitMQ and MinIO. |
| FP32 backward compatibility | Default precision still `fp32`; OpenVINO FP32 and PyTorch FP32 give identical tracks on all 5 sequences |
| Docker, Compose, API | No changes in this phase (`git diff feature/quantization-phase2` touches only `ai-worker/app/cli.py`, `model_quantization.py`, `benchmarks/` and tests) |
| Artifacts in git | No datasets, videos, images, weights or credentials committed; only JSON reports and manifests (about 60 KB) |

New in this phase:

- `--calibration-images` (multi-folder calibration with provenance);
- `fetch_mot17`;
- `quantization_error_analysis`;
- evaluation options `--configurations` and `--int8-label`;
- 5 new tests (470 → 475);
- two bug fixes found during the work: ambiguous `img1` provenance names, and a `KeyError` in single-configuration evaluation.

## 7. Acceptance policy (pedestrian tracking, per model and artifact)

Proposed for review. Thresholds reflect this use case (counting and following people with a Nano
model). They are engineering margins, not standards.

| Gate | Threshold (Δ vs PyTorch FP32 on held-out annotated sequences) | INT8 original | INT8 multi-source |
| --- | --- | --- | --- |
| Combined HOTA, IDF1, MOTA | each ≥ −1.0 point | ✅ −0.59 / −0.76 / −0.03 | ✅ +0.54 / +0.73 / −0.62 |
| Combined detection precision and recall | each ≥ −1.0 point | ✅ −0.06 / +0.02 | ❌ precision −1.32 |
| Combined IDSW | ≤ +5 % relative | ✅ +0.2 % | ❌ +6.4 % |
| Every sequence: HOTA, MOTA, IDF1 | each ≥ −2.0 points | ✅ worst −1.41 (IDF1, MOT17-09) | ❌ MOTA −5.31, IDF1 −2.07 (MOT17-05) |
| Speed | end-to-end FPS ≥ 1.5× PyTorch FP32 | ✅ 2.34× | ✅ 2.35× |
| Calibration and evaluation disjoint | required | ✅ | ✅ (same domain, different sequences) |
| **Decision** | | **Pass (pedestrians)** | **Fail: keep as an experiment only** |

The same gates should be applied to vehicles, using vehicle-annotated sequences and the Vehicles
preset classes, before INT8 is offered for vehicle tracking.

## 8. Remaining risks

- **Vehicles (the default preset) are not validated.** No vehicle ground truth was available.
- **One model, one CPU.** Only yolo11n was validated against ground truth. yolo26s, which fragmented more in Phase 2's agreement test, was not. Only an AMD Zen 3 CPU without VNNI was used; Intel CPUs with VNNI or AMX may behave differently.
- **Public data.** MOT17 training sequences are public and well known. Five sequences cover static and moving cameras, crowds, small people, occlusion, night and indoor scenes, but not rain, fisheye, thermal or top-down views.
- **Calibration sensitivity.** Changing the calibration data shifted the confidence operating point measurably. Every new INT8 artifact needs the full gate, not just a smoke test.
- **Low absolute accuracy.** Nano at 960 px misses most small and occluded people for every runtime. INT8 does not make that worse, but it matters more than INT8 for product quality.

## 9. Recommendation

| Scope | Decision |
| --- | --- |
| Pedestrian tracking, yolo11n, original INT8 artifact | **GO** as an opt-in, operator-configured runtime (`AI_MODEL_PRECISION=int8`). Meets every proposed gate; 2.34× faster. |
| Multi-source INT8 artifact | **NO-GO.** Fails precision, IDSW and the per-sequence floor. Kept only as an experiment in `model-cache/quantized-diverse/`. |
| Vehicle tracking (Vehicles preset, default use case) | **NO-GO**: unvalidated |
| Other models (yolo26s, …) | **NO-GO** until each passes the gates |
| INT8 as the default | **NO-GO**: FP32 stays the default |

**Phase 3 (Spring Boot and React precision selection): NO-GO for a general user-facing selector.**
The product's main use case, vehicle tracking with the Vehicles preset, has no accuracy validation
yet, and a selector would offer INT8 for it.

A narrower Phase 3 is reasonable now:

- report the **effective** precision read-only (worker result field, nullable Flyway column, job details API, UI badge);
- keep INT8 as an operator setting restricted to validated model and class combinations.

Next steps:

1. Obtain vehicle tracking ground truth: KITTI Tracking or UA-DETRAC after accepting their terms, or annotate 3–5 project traffic clips in CVAT (MOT 1.1 export), disjoint from calibration. Run `tracking_evaluation` with `--detect-classes 2,3,5,7 --class-map 2:…`.
2. Evaluate yolo26s (and any other offered model) on MOT17 with the same gates.
3. Repeat on the deployment CPU.
