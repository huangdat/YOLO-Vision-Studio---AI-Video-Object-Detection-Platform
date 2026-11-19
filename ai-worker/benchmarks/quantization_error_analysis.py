"""Where INT8 tracking differs from FP32, judged against MOTChallenge ground truth (accuracy validation).

Reads the predictions written by ``benchmarks.tracking_evaluation --predictions-dir`` and the GT of the
same sequences. Matching uses the evaluation's own MOT17 preprocessing (``mot.preprocess_frame``) and
IoU >= 0.5 Hungarian assignment per frame, like CLEAR/MOTA.

    python -m benchmarks.quantization_error_analysis --sequences temp/datasets/MOT17 \
        --predictions-dir temp/accuracy/yolo11n/predictions --candidates int8 --output analysis.json

Per configuration it reports recall by object size (box height / image height), occlusion (GT
visibility) and crowd density (scored people in the frame), false positives by size, localization
(IoU of matches), confidence of true and false positives, and per-GT-track identity statistics.
For each candidate (e.g. int8) versus the reference (fp32) it classifies every box the two disagree
on by its ground-truth outcome: a candidate-only box is a recovered miss (TP) or a new false positive
(FP); a reference-only box is a lost detection (TP) or a removed false positive (FP).

Identity counts here are per GT track (ID changes between consecutive matched frames). They are a
diagnostic breakdown; TrackEval's IDSW from the evaluation report is the official number.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
from typing import Any

import numpy as np

from benchmarks import mot

SIZE_BINS = ((0.0, 0.1, "<10%"), (0.1, 0.2, "10-20%"), (0.2, 0.4, "20-40%"), (0.4, 9.9, ">=40%"))
VISIBILITY_BINS = ((0.0, 0.25, "<0.25"), (0.25, 0.5, "0.25-0.5"), (0.5, 0.75, "0.5-0.75"), (0.75, 1.01, ">=0.75"))
DENSITY_BINS = ((0, 10, "<10"), (10, 20, "10-19"), (20, 30, "20-29"), (30, 10_000, ">=30"))


def _bin(value: float, bins: tuple[tuple[float, float, str], ...]) -> str:
    return next((label for low, high, label in bins if low <= value < high), bins[-1][2])


def match(gt: np.ndarray, tracker: np.ndarray, threshold: float = 0.5) -> tuple[list[tuple[int, int, float]], set[int], set[int]]:
    """Hungarian IoU matching: (pairs with IoU, unmatched GT rows, unmatched tracker rows)."""
    from scipy.optimize import linear_sum_assignment

    if len(gt) == 0 or len(tracker) == 0:
        return [], set(range(len(gt))), set(range(len(tracker)))
    iou = mot.iou_xywh(gt[:, 2:6], tracker[:, 2:6])
    rows, cols = linear_sum_assignment(-np.where(iou >= threshold - np.finfo(float).eps, iou, 0))
    pairs = [(int(r), int(c), float(iou[r, c])) for r, c in zip(rows, cols) if iou[r, c] >= threshold - 1e-12]
    return pairs, set(range(len(gt))) - {p[0] for p in pairs}, set(range(len(tracker))) - {p[1] for p in pairs}


def _load_rows(path: Path) -> np.ndarray:
    if not path.is_file() or path.stat().st_size == 0:
        return np.zeros((0, 10))
    return np.atleast_2d(np.loadtxt(path, delimiter=","))


class ConfigurationStats:
    def __init__(self) -> None:
        self.gt_total: Counter[str] = Counter()
        self.gt_found: Counter[str] = Counter()
        self.fp_by_size: Counter[str] = Counter()
        self.predictions_by_size: Counter[str] = Counter()
        self.ious: list[float] = []
        self.tp_scores: list[float] = []
        self.fp_scores: list[float] = []
        self.track_ids: dict[tuple[str, int], list[int]] = defaultdict(list)  # per GT track, matched IDs in order

    def add_frame(self, sequence: str, height: int, gt: np.ndarray, tracker: np.ndarray) -> tuple[set[int], set[int]]:
        pairs, _, unmatched_tracker = match(gt, tracker)
        matched_gt = {pair[0] for pair in pairs}
        density = _bin(len(gt), DENSITY_BINS)
        for index, row in enumerate(gt):
            found = index in matched_gt
            for key in (f"size {_bin(row[5] / height, SIZE_BINS)}", f"visibility {_bin(row[8], VISIBILITY_BINS)}",
                        f"density {density}", "all"):
                self.gt_total[key] += 1
                self.gt_found[key] += found
        for index, row in enumerate(tracker):
            size = _bin(row[5] / height, SIZE_BINS)
            self.predictions_by_size[size] += 1
            if index in unmatched_tracker:
                self.fp_by_size[size] += 1
                self.fp_scores.append(float(row[6]))
        for gt_index, tracker_index, iou in pairs:
            self.ious.append(iou)
            self.tp_scores.append(float(tracker[tracker_index, 6]))
            self.track_ids[(sequence, int(gt[gt_index, 1]))].append(int(tracker[tracker_index, 1]))
        return {pair[1] for pair in pairs}, unmatched_tracker

    def summary(self, conf: float) -> dict[str, Any]:
        switches = {key: sum(1 for a, b in zip(ids, ids[1:]) if a != b) for key, ids in self.track_ids.items()}
        distinct = [len(set(ids)) for ids in self.track_ids.values()]
        near = (conf, conf + 0.1)
        return {
            "recall": {key: round(self.gt_found[key] / total, 4) for key, total in sorted(self.gt_total.items())},
            "gtBoxes": dict(sorted(self.gt_total.items())),
            "falsePositiveShareBySize": {key: round(self.fp_by_size[key] / total, 4)
                                         for key, total in sorted(self.predictions_by_size.items())},
            "meanMatchIoU": round(float(np.mean(self.ious)), 4) if self.ious else None,
            "scoreMean": {"truePositives": round(float(np.mean(self.tp_scores)), 4) if self.tp_scores else None,
                          "falsePositives": round(float(np.mean(self.fp_scores)), 4) if self.fp_scores else None},
            "nearThresholdShare": {
                "truePositives": round(float(np.mean([near[0] <= s < near[1] for s in self.tp_scores])), 4)
                if self.tp_scores else None,
                "falsePositives": round(float(np.mean([near[0] <= s < near[1] for s in self.fp_scores])), 4)
                if self.fp_scores else None},
            "gtTracksMatched": len(self.track_ids),
            "gtTracksWithIdChange": sum(1 for value in switches.values() if value),
            "idChangesAlongGtTracks": int(sum(switches.values())),
            "meanDistinctIdsPerGtTrack": round(float(np.mean(distinct)), 3) if distinct else None,
        }


def analyse(sequences: list[mot.Sequence], predictions: Path, reference: str, candidates: list[str], *,
            eval_classes: tuple[int, ...], distractors: tuple[int, ...], conf: float) -> dict[str, Any]:
    configurations = [reference, *candidates]
    stats = {name: ConfigurationStats() for name in configurations}
    pairwise = {name: Counter() for name in candidates}
    score_deltas: dict[str, list[float]] = {name: [] for name in candidates}
    counterpart_ious: dict[str, list[float]] = {name: [] for name in candidates}
    disagreement_scores: dict[str, dict[str, list[float]]] = {name: defaultdict(list) for name in candidates}
    for sequence in sequences:
        gt_all = mot.read_ground_truth(sequence)
        rows = {name: _load_rows(predictions / name / "data" / f"{sequence.name}.txt") for name in configurations}
        for frame in range(1, sequence.length + 1):
            frame_gt = mot.frame_rows(gt_all, frame, 9)
            kept: dict[str, np.ndarray] = {}
            outcome: dict[str, tuple[set[int], set[int]]] = {}
            for name in configurations:
                scored, tracker, _ = mot.preprocess_frame(frame_gt, mot.frame_rows(rows[name], frame, 10),
                                                          eval_classes=eval_classes, distractor_classes=distractors)
                kept[name] = tracker
                outcome[name] = stats[name].add_frame(sequence.name, sequence.height, scored, tracker)
            for name in candidates:
                pairs, reference_only, candidate_only = match(kept[reference], kept[name])
                for ref_index, cand_index, iou in pairs:
                    score_deltas[name].append(float(kept[name][cand_index, 6] - kept[reference][ref_index, 6]))
                    counterpart_ious[name].append(iou)
                true_ref, _ = outcome[reference]
                true_cand, _ = outcome[name]
                for index in candidate_only:
                    label = "candidateOnlyTruePositive" if index in true_cand else "candidateOnlyFalsePositive"
                    pairwise[name][label] += 1
                    disagreement_scores[name][label].append(float(kept[name][index, 6]))
                for index in reference_only:
                    label = "referenceOnlyTruePositive" if index in true_ref else "referenceOnlyFalsePositive"
                    pairwise[name][label] += 1
                    disagreement_scores[name][label].append(float(kept[reference][index, 6]))
                pairwise[name]["matchedBoxes"] += len(pairs)
    # Per GT track: does the candidate change ID more or less often than the reference?
    identity: dict[str, Counter[str]] = {}
    for name in candidates:
        counter: Counter[str] = Counter()
        for key in set(stats[reference].track_ids) | set(stats[name].track_ids):
            ref_ids, cand_ids = stats[reference].track_ids.get(key, []), stats[name].track_ids.get(key, [])
            ref_changes = sum(1 for a, b in zip(ref_ids, ref_ids[1:]) if a != b)
            cand_changes = sum(1 for a, b in zip(cand_ids, cand_ids[1:]) if a != b)
            counter["candidateMoreIdChanges" if cand_changes > ref_changes else
                    "candidateFewerIdChanges" if cand_changes < ref_changes else "sameIdChanges"] += 1
        identity[name] = counter
    near = (conf, conf + 0.1)
    return {
        "reference": reference,
        "perConfiguration": {name: stats[name].summary(conf) for name in configurations},
        "versusReference": {
            name: {
                **dict(pairwise[name]),
                "scoreDeltaOnMatchedBoxes": {
                    "mean": round(float(np.mean(score_deltas[name])), 4),
                    "median": round(float(np.median(score_deltas[name])), 4),
                    "stdev": round(float(np.std(score_deltas[name])), 4),
                    "absMean": round(float(np.mean(np.abs(score_deltas[name]))), 4)},
                "meanIoUWithReferenceBox": round(float(np.mean(counterpart_ious[name])), 4),
                "disagreementNearThresholdShare": {
                    label: round(float(np.mean([near[0] <= s < near[1] for s in values])), 4)
                    for label, values in disagreement_scores[name].items() if values},
                "gtTracks": dict(identity[name]),
            } for name in candidates},
    }


def main(argv: list[str] | None = None) -> int:
    from benchmarks.tracking_evaluation import _ints, discover

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--sequences", nargs="+", type=Path, required=True)
    parser.add_argument("--predictions-dir", type=Path, required=True)
    parser.add_argument("--reference", default="fp32")
    parser.add_argument("--candidates", nargs="+", default=["int8"])
    parser.add_argument("--eval-classes", default=str(mot.MOT17_PEDESTRIAN))
    parser.add_argument("--distractor-classes", default=",".join(map(str, mot.MOT17_DISTRACTORS)))
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    sequences = [mot.load_sequence(path) for path in discover(args.sequences)]
    report = analyse(sequences, args.predictions_dir, args.reference, args.candidates,
                     eval_classes=_ints(args.eval_classes), distractors=_ints(args.distractor_classes), conf=args.conf)
    report["sequences"] = [sequence.name for sequence in sequences]
    text = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
