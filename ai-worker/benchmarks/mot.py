"""MOTChallenge-format ground truth, tracker output, and tracking metrics (quantization Phase 2).

Sequence layout (MOT17 conventions)::

    <sequence>/seqinfo.ini      [Sequence] name, seqLength, imWidth, imHeight, imDir (default img1)
    <sequence>/img1/000001.jpg  one zero-padded image per frame, frame 1 first
    <sequence>/gt/gt.txt        frame,id,bb_left,bb_top,bb_width,bb_height,conf,class,visibility

* Frames are 1-based in files and 0-based in the pipeline (``DetectionService`` yields frame 0 first).
* Boxes are top-left x, y, width, height in pixels, written exactly as the pipeline produced them
  (the same convention as ByteTrack's own MOT output).
* GT ``conf`` 0 marks boxes to ignore. Ground truth of ``eval_classes`` is scored; tracker boxes that
  match ``distractor_classes`` GT (IoU >= 0.5, Hungarian) are removed before scoring, as TrackEval's
  MOTChallenge2DBox preprocessing does (MOT17 distractors: 2 person on vehicle, 7 static person,
  8 distractor, 12 reflection).
* Tracker output keeps only boxes with a confirmed Track ID whose COCO class maps to an evaluated
  class. Unconfirmed boxes (``trackId`` null) are not tracks and are not written.

Metrics come from TrackEval (HOTA, CLEAR: MOTA/IDSW/precision/recall, Identity: IDF1); nothing here
re-implements them. Importing this module needs only NumPy; TrackEval and SciPy load on evaluation.
"""

from __future__ import annotations

import configparser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

MOT17_PEDESTRIAN = 1
MOT17_DISTRACTORS = (2, 7, 8, 12)
COCO_PERSON = 0
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp"}


class MotFormatError(ValueError):
    """A sequence, annotation, or tracker file does not follow the expected MOTChallenge format."""


@dataclass(frozen=True)
class Sequence:
    name: str
    root: Path
    image_dir: Path
    length: int
    width: int
    height: int

    @property
    def gt_file(self) -> Path:
        return self.root / "gt" / "gt.txt"


@dataclass
class FrameBoxes:
    """Per-frame ids and xywh boxes (and classes for GT)."""

    ids: list[np.ndarray] = field(default_factory=list)
    boxes: list[np.ndarray] = field(default_factory=list)
    classes: list[np.ndarray] = field(default_factory=list)


def load_sequence(root: Path) -> Sequence:
    """Read seqinfo.ini and check that the image directory holds exactly frames 1..seqLength."""
    root = Path(root)
    info = configparser.ConfigParser()
    if not info.read(root / "seqinfo.ini", encoding="utf-8") or "Sequence" not in info:
        raise MotFormatError(f"{root.name}: seqinfo.ini is missing")
    try:
        section = info["Sequence"]
        length, width, height = int(section["seqLength"]), int(section["imWidth"]), int(section["imHeight"])
    except (KeyError, ValueError) as error:
        raise MotFormatError(f"{root.name}: seqinfo.ini needs seqLength, imWidth and imHeight") from error
    image_dir = root / section.get("imDir", "img1")
    images = sorted(path for path in image_dir.iterdir() if path.suffix.lower() in IMAGE_SUFFIXES) \
        if image_dir.is_dir() else []
    if length < 1 or len(images) != length:
        raise MotFormatError(f"{root.name}: seqLength={length} but {len(images)} images in {image_dir.name}")
    expected = [f"{index:06d}" for index in range(1, length + 1)]
    if [path.stem for path in images] != expected:
        raise MotFormatError(f"{root.name}: images must be named 000001..{length:06d} without gaps")
    return Sequence(section.get("name", root.name), root, image_dir, length, width, height)


def _read_rows(path: Path, min_columns: int) -> np.ndarray:
    if not path.is_file():
        raise MotFormatError(f"{path.name} does not exist")
    rows = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        return np.zeros((0, min_columns))
    try:
        data = np.array([[float(value) for value in row.split(",")] for row in rows])
    except ValueError as error:
        raise MotFormatError(f"{path.name}: every row must be comma-separated numbers") from error
    if data.ndim != 2 or data.shape[1] < min_columns:
        raise MotFormatError(f"{path.name}: expected at least {min_columns} columns per row")
    return data


def read_ground_truth(sequence: Sequence) -> np.ndarray:
    """GT rows (frame, id, x, y, w, h, conf, class, visibility), validated against the sequence."""
    data = _read_rows(sequence.gt_file, 9)
    if len(data):
        frames = data[:, 0]
        if np.any(frames != np.round(frames)) or frames.min() < 1 or frames.max() > sequence.length:
            raise MotFormatError(f"{sequence.name}: GT frames must be integers in 1..{sequence.length}")
        if np.any(data[:, 4] <= 0) or np.any(data[:, 5] <= 0):
            raise MotFormatError(f"{sequence.name}: GT boxes need a positive width and height")
        keys = data[:, :2].astype(np.int64)
        if len(np.unique(keys, axis=0)) != len(keys):
            raise MotFormatError(f"{sequence.name}: a GT id appears twice in one frame")
    return data


def tracker_rows(frames: list[list[list[float]]], class_map: dict[int, int]) -> np.ndarray:
    """Convert pipeline output to MOT rows (frame, id, x, y, w, h, conf, class, -1, -1).

    ``frames`` is the benchmark's per-frame list of [coco_class, conf, x1, y1, x2, y2, track_id or -1].
    ``class_map`` maps COCO class ids to the GT class ids they are evaluated as.
    """
    rows = []
    for index, boxes in enumerate(frames):
        for coco_class, confidence, x1, y1, x2, y2, track_id in boxes:
            if track_id < 0 or int(coco_class) not in class_map:
                continue
            rows.append([index + 1, int(track_id), x1, y1, x2 - x1, y2 - y1, confidence,
                         class_map[int(coco_class)], -1, -1])
    data = np.array(rows, dtype=float) if rows else np.zeros((0, 10))
    if len(data):
        keys = data[:, :2].astype(np.int64)
        if len(np.unique(keys, axis=0)) != len(keys):
            raise MotFormatError("The tracker produced the same Track ID twice in one frame")
    return data


def write_rows(path: Path, rows: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{int(r[0])},{int(r[1])},{r[2]:.2f},{r[3]:.2f},{r[4]:.2f},{r[5]:.2f},{r[6]:.4f},"
             f"{int(r[7])},{int(r[8])},{int(r[9]) if len(r) > 9 else -1}" for r in rows]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def iou_xywh(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    if len(a) == 0 or len(b) == 0:
        return np.zeros((len(a), len(b)))
    ax2, ay2 = a[:, 0] + a[:, 2], a[:, 1] + a[:, 3]
    bx2, by2 = b[:, 0] + b[:, 2], b[:, 1] + b[:, 3]
    width = np.clip(np.minimum(ax2[:, None], bx2) - np.maximum(a[:, 0][:, None], b[:, 0]), 0, None)
    height = np.clip(np.minimum(ay2[:, None], by2) - np.maximum(a[:, 1][:, None], b[:, 1]), 0, None)
    intersection = width * height
    union = (a[:, 2] * a[:, 3])[:, None] + b[:, 2] * b[:, 3] - intersection
    return np.where(union > 0, intersection / np.where(union > 0, union, 1), 0.0)


def preprocess_frame(frame_gt: np.ndarray, frame_tr: np.ndarray, *, eval_classes: tuple[int, ...],
                     distractor_classes: tuple[int, ...]) -> tuple[np.ndarray, np.ndarray, int]:
    """MOTChallenge preprocessing of one frame: (scored GT, kept tracker rows, removed distractor matches).

    Like TrackEval's MotChallenge2DBox: tracker rows of other classes are dropped; tracker rows matched
    (Hungarian, IoU >= 0.5) to a distractor GT box are removed, matching against every GT box of the
    frame including conf=0 ones; only GT with conf != 0 and an evaluated class is scored.
    """
    from scipy.optimize import linear_sum_assignment

    frame_tr = frame_tr[np.isin(frame_tr[:, 7], eval_classes)] if len(frame_tr) else frame_tr
    keep = np.ones(len(frame_tr), dtype=bool)
    if len(frame_gt) and len(frame_tr) and np.isin(frame_gt[:, 7], distractor_classes).any():
        similarity = iou_xywh(frame_gt[:, 2:6], frame_tr[:, 2:6])
        matching = np.where(similarity >= 0.5 - np.finfo(float).eps, similarity, 0)
        rows, cols = linear_sum_assignment(-matching)
        for row, col in zip(rows, cols):
            if matching[row, col] > 0 and frame_gt[row, 7] in distractor_classes:
                keep[col] = False
    scored_gt = frame_gt[(frame_gt[:, 6] != 0) & np.isin(frame_gt[:, 7], eval_classes)]         if len(frame_gt) else frame_gt
    return scored_gt, frame_tr[keep], int((~keep).sum())


def frame_rows(rows: np.ndarray, frame: int, columns: int) -> np.ndarray:
    return rows[rows[:, 0] == frame] if len(rows) else np.zeros((0, columns))


def build_trackeval_data(gt: np.ndarray, tracker: np.ndarray, length: int, *, eval_classes: tuple[int, ...],
                         distractor_classes: tuple[int, ...]) -> dict[str, Any]:
    """Preprocess one sequence into the dict TrackEval metrics' ``eval_sequence`` expects."""
    gt_ids: list[np.ndarray] = []
    tracker_ids: list[np.ndarray] = []
    similarities: list[np.ndarray] = []
    removed_as_distractor = 0
    for frame in range(1, length + 1):
        scored_gt, frame_tr, removed = preprocess_frame(
            frame_rows(gt, frame, 9), frame_rows(tracker, frame, 10),
            eval_classes=eval_classes, distractor_classes=distractor_classes)
        removed_as_distractor += removed
        gt_ids.append(scored_gt[:, 1].astype(int))
        tracker_ids.append(frame_tr[:, 1].astype(int))
        similarities.append(iou_xywh(scored_gt[:, 2:6], frame_tr[:, 2:6]))

    def relabel(ids: list[np.ndarray]) -> tuple[list[np.ndarray], int]:
        unique = np.unique(np.concatenate(ids)) if any(len(i) for i in ids) else np.zeros(0, dtype=int)
        lookup = {int(value): index for index, value in enumerate(unique)}
        return [np.array([lookup[int(v)] for v in i], dtype=int) for i in ids], len(unique)

    gt_ids, num_gt_ids = relabel(gt_ids)
    tracker_ids, num_tracker_ids = relabel(tracker_ids)
    return {
        "num_timesteps": length, "num_gt_ids": num_gt_ids, "num_tracker_ids": num_tracker_ids,
        "num_gt_dets": int(sum(len(i) for i in gt_ids)), "num_tracker_dets": int(sum(len(i) for i in tracker_ids)),
        "gt_ids": gt_ids, "tracker_ids": tracker_ids, "similarity_scores": similarities,
        "removed_as_distractor": removed_as_distractor,
    }


def _metrics() -> tuple[Any, Any, Any]:
    import io
    from contextlib import redirect_stdout

    with redirect_stdout(io.StringIO()):  # TrackEval prints its config and optional-import notices
        from trackeval.metrics import CLEAR, HOTA, Identity

        return HOTA(), CLEAR({"PRINT_CONFIG": False}), Identity({"PRINT_CONFIG": False})


def _summary(h: dict[str, Any], c: dict[str, Any], i: dict[str, Any]) -> dict[str, Any]:
    tp, fn, fp = int(c["CLR_TP"]), int(c["CLR_FN"]), int(c["CLR_FP"])
    return {
        "HOTA": float(np.mean(h["HOTA"])), "DetA": float(np.mean(h["DetA"])), "AssA": float(np.mean(h["AssA"])),
        "MOTA": float(c["MOTA"]), "MOTP": float(c["MOTP"]), "IDF1": float(i["IDF1"]), "IDSW": int(c["IDSW"]),
        "precision": tp / (tp + fp) if tp + fp else 0.0, "recall": tp / (tp + fn) if tp + fn else 0.0,
        "TP": tp, "FN": fn, "FP": fp, "fragmentations": int(c["Frag"]),
        "mostlyTracked": int(c["MT"]), "mostlyLost": int(c["ML"]),
    }


def evaluate(data: dict[str, Any]) -> dict[str, Any]:
    """HOTA (alpha-averaged), MOTA, IDF1, IDSW, detection precision/recall for one sequence."""
    return evaluate_many({"sequence": data})["sequence"]


def evaluate_many(sequences: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per-sequence metrics plus ``COMBINED`` (TrackEval's own combine_sequences) when there are several."""
    hota, clear, identity = _metrics()
    raw: dict[str, tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = {}
    output: dict[str, dict[str, Any]] = {}
    for name, data in sequences.items():
        data = {key: value for key, value in data.items() if key != "removed_as_distractor"}
        if data["num_gt_dets"] == 0:
            raise MotFormatError(f"{name}: the sequence has no scored ground-truth boxes")
        raw[name] = (hota.eval_sequence(data), clear.eval_sequence(data), identity.eval_sequence(data))
        output[name] = {**_summary(*raw[name]), "gtIds": data["num_gt_ids"], "trackerIds": data["num_tracker_ids"]}
    if len(raw) > 1:
        combined = tuple(metric.combine_sequences({name: values[index] for name, values in raw.items()})
                         for index, metric in enumerate((hota, clear, identity)))
        output["COMBINED"] = _summary(*combined)
    return output
