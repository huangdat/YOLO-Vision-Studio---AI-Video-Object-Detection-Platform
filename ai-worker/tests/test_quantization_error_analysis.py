"""Quantization error analysis on SYNTHETIC fixtures (tests the bookkeeping, not real accuracy)."""

from __future__ import annotations

from importlib.util import find_spec
from pathlib import Path

import numpy as np
import pytest

from benchmarks import mot
from benchmarks.quantization_error_analysis import analyse, match

pytestmark = pytest.mark.skipif(find_spec("scipy") is None, reason="SciPy not installed")


def test_match_pairs_boxes_by_iou_and_reports_unmatched() -> None:
    gt = np.array([[1, 1, 0, 0, 10, 10, 1, 1, 1], [1, 2, 50, 50, 10, 10, 1, 1, 1]], float)
    tracker = np.array([[1, 7, 1, 1, 10, 10, 0.9, 1, -1, -1], [1, 8, 200, 200, 5, 5, 0.3, 1, -1, -1]], float)

    pairs, unmatched_gt, unmatched_tracker = match(gt, tracker)

    assert [(r, c) for r, c, _ in pairs] == [(0, 0)] and pairs[0][2] == pytest.approx(81 / 119)
    assert (unmatched_gt, unmatched_tracker) == ({1}, {1})


def test_disagreements_are_classified_by_ground_truth_outcome(tmp_path: Path) -> None:
    # Two pedestrians over 3 frames (a large one, height 0.5 of the image; a small one, 0.05).
    gt_rows = []
    for frame in (1, 2, 3):
        gt_rows += [[frame, 1, 10, 10, 20, 50, 1, 1, 1.0], [frame, 2, 60, 10, 4, 5, 1, 1, 0.2]]
    sequence_dir = tmp_path / "SYN-01"
    (sequence_dir / "img1").mkdir(parents=True)
    (sequence_dir / "gt").mkdir()
    for frame in (1, 2, 3):
        (sequence_dir / "img1" / f"{frame:06d}.jpg").write_bytes(b"")
    (sequence_dir / "seqinfo.ini").write_text(
        "[Sequence]\nname=SYN-01\nimDir=img1\nseqLength=3\nimWidth=100\nimHeight=100\n", encoding="utf-8")
    (sequence_dir / "gt" / "gt.txt").write_text(
        "\n".join(",".join(f"{v:g}" for v in row) for row in gt_rows) + "\n", encoding="utf-8")

    reference = [[f, 1, 10, 10, 20, 50, 0.9, 1, -1, -1] for f in (1, 2, 3)] + \
                [[f, 2, 60, 10, 4, 5, 0.4, 1, -1, -1] for f in (1, 2, 3)]
    candidate = [[f, 1 if f < 3 else 5, 10, 10, 20, 50, 0.85, 1, -1, -1] for f in (1, 2, 3)]  # ID change at f3
    candidate += [[1, 2, 60, 10, 4, 5, 0.3, 1, -1, -1]]                                       # small: only frame 1
    candidate += [[2, 9, 80, 80, 10, 10, 0.27, 1, -1, -1]]                                    # new false positive
    for name, rows in (("fp32", reference), ("int8", candidate)):
        mot.write_rows(tmp_path / "pred" / name / "data" / "SYN-01.txt", np.array(rows, float))

    report = analyse([mot.load_sequence(sequence_dir)], tmp_path / "pred", "fp32", ["int8"],
                     eval_classes=(1,), distractors=mot.MOT17_DISTRACTORS, conf=0.25)

    fp32, int8 = report["perConfiguration"]["fp32"], report["perConfiguration"]["int8"]
    versus = report["versusReference"]["int8"]
    assert fp32["recall"]["all"] == 1.0 and int8["recall"]["all"] == pytest.approx(4 / 6, abs=1e-4)
    assert int8["recall"]["size <10%"] == pytest.approx(1 / 3, abs=1e-4) and int8["recall"]["size >=40%"] == 1.0
    assert int8["recall"]["visibility <0.25"] == pytest.approx(1 / 3, abs=1e-4)
    assert versus["referenceOnlyTruePositive"] == 2       # INT8 lost the small person in frames 2 and 3
    assert versus["candidateOnlyFalsePositive"] == 1      # and added one false positive
    assert versus.get("candidateOnlyTruePositive", 0) == 0
    assert versus["matchedBoxes"] == 4
    assert versus["scoreDeltaOnMatchedBoxes"]["mean"] == pytest.approx((3 * -0.05 - 0.1) / 4, abs=1e-4)
    assert versus["disagreementNearThresholdShare"]["candidateOnlyFalsePositive"] == 1.0
    assert int8["gtTracksWithIdChange"] == 1 and fp32["gtTracksWithIdChange"] == 0
    assert versus["gtTracks"] == {"candidateMoreIdChanges": 1, "sameIdChanges": 1}
