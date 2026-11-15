"""FP32 vs INT8 benchmark of the real detection + ByteTrack pipeline (quantization PoC).

Usage (from ai-worker/, after `models prepare` and `models quantize`):

    python -m benchmarks.quantization_benchmark --video temp/quantization-poc/holdout.mp4 \
        --model yolo11n --imgsz 960 --cpus 4 --repeats 3 --include-openvino-fp32

Every configuration runs in its own subprocess (clean peak-RAM measurement) through
``DetectionService.iter_frames`` with an ``ObjectTracker``: the same decode, letterbox, inference,
NMS, ByteTrack and annotation code as a tracking job; only MP4 encoding and upload are excluded.

Configurations:
  fp32     PyTorch checkpoint (the production default)
  int8     OpenVINO INT8 artifact from `models quantize`
  ov-fp32  OpenVINO FP32 export (optional; isolates the runtime effect from the quantization effect)

There is no ground truth for the input video, so detection quality is reported as *agreement with
the FP32 run* (same-class boxes with IoU >= 0.5) and Track ID continuity as *ID splits relative to
FP32 tracks*. These are proxies, not mAP, IDF1, HOTA, or true ID switches.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import os
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from typing import Any

CONFIGURATIONS = ("fp32", "int8", "ov-fp32")
WARMUP_FRAMES = 5


# --- Child process: one configuration, one pass over the video -----------------------------------

def _pin_cpus(cpus: int | None) -> list[int] | None:
    """Restrict the process to ``cpus`` physical cores (one logical CPU per core when SMT is on)."""
    if not cpus:
        return None
    import psutil

    logical = psutil.cpu_count(logical=True) or cpus
    physical = psutil.cpu_count(logical=False) or logical
    step = max(1, logical // physical)
    chosen = list(range(0, logical, step))[:cpus]
    psutil.Process().cpu_affinity(chosen)
    return chosen


def _openvino_threads(model: Any) -> int | None:
    backend = getattr(getattr(getattr(model, "predictor", None), "model", None), "backend", None)
    compiled = getattr(backend, "ov_compiled_model", None)
    try:
        return int(compiled.get_property("INFERENCE_NUM_THREADS")) if compiled is not None else None
    except Exception:
        return None


def _peak_rss_bytes() -> int | None:
    import psutil

    info = psutil.Process().memory_info()
    peak = getattr(info, "peak_wset", None)  # Windows
    if peak is None:
        try:
            import resource

            peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024  # Linux reports KiB
        except Exception:
            peak = None
    return int(peak) if peak else None


def _run_one(args: argparse.Namespace) -> dict[str, Any]:
    affinity = _pin_cpus(args.cpus)
    os.environ.setdefault("YOLO_AUTOINSTALL", "false")
    from app.config.settings import Settings
    from app.services.detection_service import DetectionService
    from app.services.model_loader import LoadedModel, ModelLoader
    from app.services.model_quantization import OPENVINO_CPU_DEVICE
    from app.services.object_tracking import ByteTrackParameters, ObjectTracker

    settings = Settings(cpu_threads=args.cpus or Settings().cpu_threads)
    started = time.perf_counter()
    if args.run_one == "ov-fp32":
        import torch
        import ultralytics

        import numpy

        from app.services.model_quantization import limit_openvino_threads

        torch.set_num_threads(settings.cpu_threads)
        model = ultralytics.YOLO(str(args.ov_fp32_dir), task="detect")
        model.predict(source=numpy.zeros((64, 64, 3), dtype=numpy.uint8), imgsz=64, device=OPENVINO_CPU_DEVICE,
                      save=False, verbose=False)
        limit_openvino_threads(model, settings.cpu_threads, args.ov_fp32_dir)  # same budget as the INT8 run
        loaded = LoadedModel(model, args.model, "cpu", {int(k): str(v) for k, v in model.names.items()},
                             precision="fp32-openvino", runtime_device=OPENVINO_CPU_DEVICE)
    else:
        loaded = ModelLoader(settings).load(args.model, "cpu", allow_download=False, record_verification=False,
                                            precision=args.run_one)
    load_seconds = time.perf_counter() - started

    tracker = ObjectTracker(ByteTrackParameters.for_confidence(args.conf, settings.tracking_track_buffer),
                            trajectory_length=settings.tracking_trajectory_length)
    inference_ms: list[float] = []
    frame_ms: list[float] = []
    frames: list[list[list[float]]] = []  # per frame: [class_id, conf, x1, y1, x2, y2, track_id or -1]
    detections: Counter[str] = Counter()
    try:
        stream = DetectionService().iter_frames(Path(args.video), loaded, args.conf, args.imgsz, args.classes,
                                                tracker=tracker)
        last = time.perf_counter()
        for detected in stream:
            now = time.perf_counter()
            frame_ms.append((now - last) * 1000)
            if detected.inference_time_ms is not None:
                inference_ms.append(detected.inference_time_ms)
            detections.update(box.label for box in detected.tracked.threshold_detections)
            frames.append([[box.class_id, box.confidence, *box.xyxy,
                            box.track_id if box.track_id is not None else -1] for box in detected.boxes])
            last = time.perf_counter()
    finally:
        tracker.close()
    return {
        "configuration": args.run_one, "precision": loaded.precision, "frames": len(frames),
        "loadSeconds": load_seconds, "inferenceMs": inference_ms[WARMUP_FRAMES:],
        "frameMs": frame_ms[WARMUP_FRAMES:], "detections": dict(detections),
        "peakRssBytes": _peak_rss_bytes(), "cpuAffinity": affinity, "torchThreads": settings.cpu_threads,
        "openvinoThreads": _openvino_threads(loaded.model), "boxes": frames,
    }


# --- Parent process: orchestration and comparison ------------------------------------------------

def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(fraction * (len(ordered) - 1))))
    return ordered[index]


def _iou(a: list[float], b: list[float]) -> float:
    x1, y1, x2, y2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def _match(reference: list[list[float]], candidate: list[list[float]], conf: float) -> list[tuple[int, int]]:
    """Greedy same-class IoU >= 0.5 matching of threshold detections; returns index pairs."""
    pairs = sorted(((_iou(r[2:6], c[2:6]), i, j) for i, r in enumerate(reference) if r[1] >= conf
                    for j, c in enumerate(candidate) if c[1] >= conf and c[0] == r[0]), reverse=True)
    used_r: set[int] = set()
    used_c: set[int] = set()
    matched = []
    for iou, i, j in pairs:
        if iou < 0.5:
            break
        if i not in used_r and j not in used_c:
            used_r.add(i)
            used_c.add(j)
            matched.append((i, j))
    return matched


def _tracking(frames: list[list[list[float]]]) -> dict[str, Any]:
    lengths: Counter[int] = Counter(int(box[6]) for frame in frames for box in frame if box[6] >= 0)
    values = list(lengths.values())
    return {"uniqueTrackIds": len(lengths),
            "meanTrackLengthFrames": round(statistics.mean(values), 1) if values else 0,
            "tracksAtLeast25Frames": sum(1 for value in values if value >= 25)}


def _agreement(reference: list[list[list[float]]], candidate: list[list[list[float]]], conf: float) -> dict[str, Any]:
    ref_total = cand_total = matched_total = 0
    split_ids: dict[int, set[int]] = defaultdict(set)
    for ref_frame, cand_frame in zip(reference, candidate):
        matched = _match(ref_frame, cand_frame, conf)
        ref_total += sum(1 for box in ref_frame if box[1] >= conf)
        cand_total += sum(1 for box in cand_frame if box[1] >= conf)
        matched_total += len(matched)
        for i, j in matched:
            if ref_frame[i][6] >= 0 and cand_frame[j][6] >= 0:
                split_ids[int(ref_frame[i][6])].add(int(cand_frame[j][6]))
    splits = sum(len(ids) - 1 for ids in split_ids.values())
    return {
        "boxRecallVsFp32": round(matched_total / ref_total, 4) if ref_total else None,
        "boxPrecisionVsFp32": round(matched_total / cand_total, 4) if cand_total else None,
        "fp32TracksCompared": len(split_ids),
        "idSplitsVsFp32": splits,
        "fp32TracksWithOneId": sum(1 for ids in split_ids.values() if len(ids) == 1),
    }


def _artifact_size(path: Path) -> int:
    return path.stat().st_size if path.is_file() else sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def _export_openvino_fp32(model: str, imgsz: int, target: Path) -> Path:
    import ultralytics

    from app.config.settings import Settings

    weights = Settings().model_cache_dir.resolve() / f"{model}.pt"
    staged = target / weights.name
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy2(weights, staged)
    return Path(ultralytics.YOLO(str(staged)).export(format="openvino", imgsz=imgsz, dynamic=True, batch=1,
                                                     device="cpu", verbose=False))


def host_info() -> dict[str, Any]:
    from importlib import metadata

    def version(name: str) -> str | None:
        try:
            return metadata.version(name)
        except metadata.PackageNotFoundError:
            return None

    return {"processor": platform.processor(), "system": platform.platform(),
            "ultralytics": version("ultralytics-opencv-headless") or version("ultralytics"),
            "torch": version("torch"), "openvino": version("openvino")}


def run_configurations(
    video: Path, *, model: str, imgsz: int, conf: float, classes: list[int], cpus: int, repeats: int,
    include_openvino_fp32: bool,
) -> tuple[list[str], dict[str, list[dict[str, Any]]], dict[str, int]]:
    """Run every configuration ``repeats`` times, each run in a fresh subprocess. ``video`` may be a
    video file or a directory of frames (read in sorted file-name order)."""
    from app.config.settings import Settings
    from app.services.model_quantization import inspect_int8_artifact, int8_artifact_dir
    from app.services.model_registry import get_model_spec

    settings = Settings()
    spec = get_model_spec(model)
    if spec is None:
        raise RuntimeError(f"Unsupported model {model}")
    status = inspect_int8_artifact(settings, spec)
    if not status.available:
        raise RuntimeError(f"INT8 artifact for {model} unavailable: {status.reason}")
    workspace = Path(tempfile.mkdtemp(prefix="quant-bench-", dir=settings.temp_dir.resolve()))
    configurations = ["fp32", "int8"]
    sizes = {"fp32": _artifact_size(settings.model_cache_dir.resolve() / spec.weights_filename),
             "int8": _artifact_size(int8_artifact_dir(settings.quantized_models_path.resolve(), spec))}
    ov_fp32_dir = None
    runs: dict[str, list[dict[str, Any]]] = defaultdict(list)
    try:
        if include_openvino_fp32:
            ov_fp32_dir = _export_openvino_fp32(model, imgsz, workspace / "ov-fp32")
            sizes["ov-fp32"] = _artifact_size(ov_fp32_dir)
            configurations.append("ov-fp32")
        for repeat in range(repeats):
            order = configurations if repeat % 2 == 0 else list(reversed(configurations))  # spread drift
            for name in order:
                result = workspace / f"{name}-{repeat}.json"
                command = [sys.executable, "-m", "benchmarks.quantization_benchmark", "--run-one", name,
                           "--video", str(video), "--model", model, "--imgsz", str(imgsz),
                           "--conf", str(conf), "--classes", ",".join(map(str, classes)),
                           "--cpus", str(cpus), "--result", str(result)]
                if ov_fp32_dir is not None:
                    command += ["--ov-fp32-dir", str(ov_fp32_dir)]
                subprocess.run(command, check=True, stdout=subprocess.DEVNULL)
                runs[name].append(json.loads(result.read_text(encoding="utf-8")))
                print(f"{Path(video).name} {model}: repeat {repeat + 1}/{repeats} {name} done", file=sys.stderr)
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
    return configurations, runs, sizes


def _spread(values: list[float]) -> dict[str, float]:
    return {"median": round(statistics.median(values), 2), "min": round(min(values), 2),
            "max": round(max(values), 2),
            "stdev": round(statistics.stdev(values), 2) if len(values) > 1 else 0.0}


def summarize(configurations: list[str], runs: dict[str, list[dict[str, Any]]], sizes: dict[str, int],
              conf: float) -> dict[str, Any]:
    reference = runs["fp32"][0]["boxes"]
    results: dict[str, Any] = {}
    for name in configurations:
        repeats = runs[name]
        first = repeats[0]
        per_run_mean = [statistics.mean(run["inferenceMs"]) for run in repeats]
        per_run_p95 = [_percentile(run["inferenceMs"], 0.95) for run in repeats]
        per_run_fps = [1000 / statistics.mean(run["frameMs"]) for run in repeats]
        results[name] = {
            "inferenceMsMean": round(statistics.median(per_run_mean), 2),
            "inferenceMsP95": round(statistics.median(per_run_p95), 2),
            "endToEndFps": round(statistics.median(per_run_fps), 2),
            "endToEndFpsRange": [round(min(per_run_fps), 2), round(max(per_run_fps), 2)],
            "variance": {"inferenceMsMean": _spread(per_run_mean), "inferenceMsP95": _spread(per_run_p95),
                         "endToEndFps": _spread(per_run_fps)},
            "artifactBytes": sizes[name],
            "peakRssBytes": max(run["peakRssBytes"] or 0 for run in repeats) or None,
            "loadSeconds": round(statistics.median(run["loadSeconds"] for run in repeats), 2),
            "torchThreads": first["torchThreads"], "openvinoThreads": first["openvinoThreads"],
            "cpuAffinity": first["cpuAffinity"],
            "detections": first["detections"], "detectionsTotal": sum(first["detections"].values()),
            "tracking": _tracking(first["boxes"]),
            "deterministicAcrossRepeats": all(run["boxes"] == first["boxes"] for run in repeats),
            **({} if name == "fp32" else {"agreement": _agreement(reference, first["boxes"], conf)}),
        }
    return results


def gains(results: dict[str, Any]) -> dict[str, Any]:
    """Speed-ups split into the runtime effect (PyTorch -> OpenVINO, both FP32) and the quantization
    effect (OpenVINO FP32 -> INT8). Ratios of medians; >1 means faster."""
    def ratio(slow: str, fast: str) -> dict[str, float] | None:
        if slow not in results or fast not in results:
            return None
        return {"inference": round(results[slow]["inferenceMsMean"] / results[fast]["inferenceMsMean"], 2),
                "endToEnd": round(results[fast]["endToEndFps"] / results[slow]["endToEndFps"], 2)}

    return {"runtime(fp32->ov-fp32)": ratio("fp32", "ov-fp32"),
            "quantization(ov-fp32->int8)": ratio("ov-fp32", "int8"), "total(fp32->int8)": ratio("fp32", "int8")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--model", default="yolo11n")
    parser.add_argument("--imgsz", type=int, default=960)
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--classes", default="1,2,3,5,7", help="COCO ids (default: the Vehicles preset)")
    parser.add_argument("--cpus", type=int, default=4, help="Physical cores pinned for every run (0: no pinning)")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--include-openvino-fp32", action="store_true")
    parser.add_argument("--output", type=Path, help="Write the full JSON report here")
    parser.add_argument("--run-one", choices=CONFIGURATIONS, help=argparse.SUPPRESS)
    parser.add_argument("--ov-fp32-dir", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--result", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    args.classes = [int(value) for value in str(args.classes).split(",")]

    if args.run_one:
        args.result.write_text(json.dumps(_run_one(args)), encoding="utf-8")
        return 0

    try:
        configurations, runs, sizes = run_configurations(
            args.video, model=args.model, imgsz=args.imgsz, conf=args.conf, classes=args.classes, cpus=args.cpus,
            repeats=args.repeats, include_openvino_fp32=args.include_openvino_fp32)
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        return 2
    report: dict[str, Any] = {
        "input": {"video": args.video.name, "frames": runs["fp32"][0]["frames"], "imgsz": args.imgsz,
                  "conf": args.conf, "classes": args.classes, "model": args.model,
                  "warmupFramesExcluded": WARMUP_FRAMES, "repeats": args.repeats, "cpusPinned": args.cpus},
        "host": host_info(),
        "results": summarize(configurations, runs, sizes, args.conf),
    }
    report["gains"] = gains(report["results"])
    text = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
