"""Ground-truth tracking evaluation of PyTorch FP32, OpenVINO FP32, and OpenVINO INT8 (Phase 2).

Usage (from ai-worker/, with requirements-evaluation.txt installed):

    python -m benchmarks.tracking_evaluation --sequences D:/data/MOT17/train/MOT17-04-FRCNN \
        D:/data/MOT17/train/MOT17-09-FRCNN --model yolo11n --imgsz 960 --cpus 4 --repeats 3 \
        --output temp/eval/report.json --predictions-dir temp/eval/predictions

Each MOTChallenge sequence (see ``benchmarks.mot``) is processed by the same subprocess runner as
``quantization_benchmark``: identical frames, ``imgsz``, confidence, classes, ByteTrack settings, and
pinned CPUs for all three configurations. Tracker output is written in MOTChallenge format
(``<predictions-dir>/<configuration>/data/<sequence>.txt``, the TrackEval tracker layout) and scored
with TrackEval: HOTA, MOTA, IDF1, IDSW, detection precision and recall.

Defaults evaluate MOT17 pedestrians: YOLO detects COCO class 0 (person), mapped to MOT class 1;
MOT17 distractor classes are handled like the official devkit. For other annotations pass
``--detect-classes``, ``--class-map``, ``--eval-classes`` and ``--distractor-classes``.

The evaluation sequences must not overlap the INT8 calibration data.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from benchmarks import mot
from benchmarks.quantization_benchmark import WARMUP_FRAMES, gains, host_info, run_configurations, summarize

ACCURACY_KEYS = ("HOTA", "DetA", "AssA", "MOTA", "IDF1", "IDSW", "precision", "recall")


def _ints(value: str) -> tuple[int, ...]:
    return tuple(int(item) for item in value.split(",") if item.strip()) if value else ()


def _class_map(value: str) -> dict[int, int]:
    try:
        return {int(coco): int(gt) for coco, gt in (pair.split(":") for pair in value.split(","))}
    except ValueError as error:
        raise argparse.ArgumentTypeError("--class-map needs coco:gt pairs, e.g. 0:1") from error


def discover(paths: list[Path]) -> list[Path]:
    """Accept sequence folders, or parent folders whose children are sequences."""
    found: list[Path] = []
    for path in paths:
        if (path / "seqinfo.ini").is_file():
            found.append(path)
        elif path.is_dir():
            found.extend(sorted(child for child in path.iterdir() if (child / "seqinfo.ini").is_file()))
    if not found:
        raise mot.MotFormatError("No MOTChallenge sequences (folders with seqinfo.ini) were found")
    return found


def _check_image_size(sequence: mot.Sequence) -> None:
    import cv2

    first = cv2.imread(str(sequence.image_dir / f"{1:06d}{next(sequence.image_dir.iterdir()).suffix}"))
    if first is None or first.shape[1] != sequence.width or first.shape[0] != sequence.height:
        raise mot.MotFormatError(f"{sequence.name}: image size does not match seqinfo.ini imWidth/imHeight")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--sequences", nargs="+", type=Path, required=True)
    parser.add_argument("--model", default="yolo11n")
    parser.add_argument("--imgsz", type=int, default=960)
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--detect-classes", default="0", help="COCO ids YOLO detects (default: person)")
    parser.add_argument("--class-map", type=_class_map, default={mot.COCO_PERSON: mot.MOT17_PEDESTRIAN},
                        help="COCO-to-GT class pairs (default 0:1, person -> MOT17 pedestrian)")
    parser.add_argument("--eval-classes", default=str(mot.MOT17_PEDESTRIAN))
    parser.add_argument("--distractor-classes", default=",".join(map(str, mot.MOT17_DISTRACTORS)))
    parser.add_argument("--cpus", type=int, default=4)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--predictions-dir", type=Path)
    parser.add_argument("--configurations", nargs="+", choices=("fp32", "ov-fp32", "int8"),
                        default=["fp32", "ov-fp32", "int8"])
    parser.add_argument("--int8-label", default="int8",
                        help="Report/predictions name of the INT8 run (e.g. int8-diverse for another artifact "
                             "selected with AI_QUANTIZED_MODEL_DIR)")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    detect_classes = list(_ints(args.detect_classes))
    eval_classes, distractors = _ints(args.eval_classes), _ints(args.distractor_classes)
    if set(args.class_map) - set(detect_classes):
        parser.error("--class-map uses COCO classes that are not in --detect-classes")
    if set(args.class_map.values()) - set(eval_classes):
        parser.error("--class-map maps to GT classes that are not in --eval-classes")

    sequences = [mot.load_sequence(path) for path in discover(args.sequences)]
    ground_truth = {}
    for sequence in sequences:
        _check_image_size(sequence)
        ground_truth[sequence.name] = mot.read_ground_truth(sequence)

    per_config_data: dict[str, dict[str, dict[str, Any]]] = {}
    performance: dict[str, Any] = {}
    for sequence in sequences:
        configurations, runs, sizes = run_configurations(
            sequence.image_dir, model=args.model, imgsz=args.imgsz, conf=args.conf, classes=detect_classes,
            cpus=args.cpus, repeats=args.repeats, include_openvino_fp32="ov-fp32" in args.configurations,
            only=tuple(args.configurations))
        labels = {name: (args.int8_label if name == "int8" else name) for name in configurations}
        runs = {labels[name]: value for name, value in runs.items()}
        sizes = {labels[name]: value for name, value in sizes.items() if name in labels}
        configurations = [labels[name] for name in configurations]
        for name in configurations:
            frames = runs[name][0]["boxes"]
            if len(frames) != sequence.length:
                raise mot.MotFormatError(f"{sequence.name}: the pipeline yielded {len(frames)} frames, "
                                         f"seqLength is {sequence.length}")
            rows = mot.tracker_rows(frames, args.class_map)
            if args.predictions_dir:
                mot.write_rows(args.predictions_dir / name / "data" / f"{sequence.name}.txt", rows)
                # Every reported box (also unconfirmed ones) for offline error analysis.
                raw = args.predictions_dir / name / "raw" / f"{sequence.name}.json"
                raw.parent.mkdir(parents=True, exist_ok=True)
                raw.write_text(json.dumps(frames), encoding="utf-8")
            per_config_data.setdefault(name, {})[sequence.name] = mot.build_trackeval_data(
                ground_truth[sequence.name], rows, sequence.length,
                eval_classes=eval_classes, distractor_classes=distractors)
        results = summarize(configurations, runs, sizes, args.conf)
        performance[sequence.name] = {"results": results, "gains": gains(results)}

    accuracy = {name: mot.evaluate_many(data) for name, data in per_config_data.items()}
    overall = "COMBINED" if len(sequences) > 1 else sequences[0].name
    deltas = {name: {key: round(accuracy[name][overall][key] - accuracy["fp32"][overall][key], 4)
                     for key in ACCURACY_KEYS} for name in accuracy if name != "fp32" and "fp32" in accuracy}
    report = {
        "input": {"sequences": [{"name": s.name, "frames": s.length, "size": [s.width, s.height]} for s in sequences],
                  "model": args.model, "imgsz": args.imgsz, "conf": args.conf, "detectClasses": detect_classes,
                  "classMap": args.class_map, "evalClasses": eval_classes, "distractorClasses": distractors,
                  "repeats": args.repeats, "cpusPinned": args.cpus, "warmupFramesExcluded": WARMUP_FRAMES},
        "host": host_info(),
        "accuracy": accuracy,
        "accuracyDeltaVsPytorchFp32": deltas,
        "performance": performance,
    }
    text = json.dumps(report, indent=2, default=str)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except mot.MotFormatError as error:
        print(f"Invalid evaluation input: {error}", file=sys.stderr)
        raise SystemExit(2) from error
