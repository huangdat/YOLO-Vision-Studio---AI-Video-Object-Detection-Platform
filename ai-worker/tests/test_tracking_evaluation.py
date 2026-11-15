"""MOTChallenge evaluation infrastructure (quantization Phase 2).

All sequences here are SYNTHETIC fixtures that test file handling and metric plumbing. They say
nothing about real-world tracking accuracy. Metric tests need TrackEval and SciPy
(requirements-evaluation.txt) and are skipped without them.
"""

from __future__ import annotations

import io
from contextlib import redirect_stdout
from importlib.util import find_spec
from pathlib import Path

import numpy as np
import pytest

from benchmarks import mot
from benchmarks.tracking_evaluation import _class_map, discover, main

needs_trackeval = pytest.mark.skipif(find_spec("trackeval") is None or find_spec("scipy") is None,
                                     reason="TrackEval/SciPy not installed (requirements-evaluation.txt)")


def make_sequence(root: Path, name: str = "SYN-01", length: int = 5, width: int = 64, height: int = 48,
                  gt_rows: list[list[float]] | None = None, image_names: list[str] | None = None) -> Path:
    sequence = root / name
    (sequence / "img1").mkdir(parents=True)
    (sequence / "gt").mkdir()
    for image in image_names or [f"{index:06d}.jpg" for index in range(1, length + 1)]:
        (sequence / "img1" / image).write_bytes(b"")
    (sequence / "seqinfo.ini").write_text(
        f"[Sequence]\nname={name}\nimDir=img1\nframeRate=30\nseqLength={length}\n"
        f"imWidth={width}\nimHeight={height}\nimExt=.jpg\n", encoding="utf-8")
    rows = gt_rows if gt_rows is not None else [[1, 1, 10, 10, 20, 30, 1, 1, 1.0]]
    (sequence / "gt" / "gt.txt").write_text("\n".join(",".join(f"{v:g}" for v in row) for row in rows) + "\n",
                                            encoding="utf-8")
    return sequence


# --- Format handling ----------------------------------------------------------------------------

def test_sequence_and_ground_truth_are_loaded(tmp_path: Path) -> None:
    sequence = mot.load_sequence(make_sequence(tmp_path))
    gt = mot.read_ground_truth(sequence)

    assert (sequence.name, sequence.length, sequence.width, sequence.height) == ("SYN-01", 5, 64, 48)
    assert gt.shape == (1, 9) and gt[0, 0] == 1


@pytest.mark.parametrize(("images", "message"), [
    (["000001.jpg", "000002.jpg"], "seqLength=5 but 2 images"),
    (["000001.jpg", "000002.jpg", "000003.jpg", "000004.jpg", "000006.jpg"], "without gaps"),
    (["1.jpg", "2.jpg", "3.jpg", "4.jpg", "5.jpg"], "without gaps"),
])
def test_image_folders_must_hold_exactly_the_numbered_frames(tmp_path: Path, images, message) -> None:
    with pytest.raises(mot.MotFormatError, match=message):
        mot.load_sequence(make_sequence(tmp_path, image_names=images))


@pytest.mark.parametrize(("row", "message"), [
    ([0, 1, 1, 1, 5, 5, 1, 1, 1], "frames must be integers in 1..5"),
    ([6, 1, 1, 1, 5, 5, 1, 1, 1], "frames must be integers in 1..5"),
    ([1.5, 1, 1, 1, 5, 5, 1, 1, 1], "frames must be integers"),
    ([1, 1, 1, 1, 0, 5, 1, 1, 1], "positive width"),
])
def test_ground_truth_rows_are_validated(tmp_path: Path, row, message) -> None:
    sequence = mot.load_sequence(make_sequence(tmp_path, gt_rows=[row]))
    with pytest.raises(mot.MotFormatError, match=message):
        mot.read_ground_truth(sequence)


def test_duplicate_ground_truth_ids_in_one_frame_are_rejected(tmp_path: Path) -> None:
    sequence = mot.load_sequence(make_sequence(tmp_path, gt_rows=[[1, 1, 1, 1, 5, 5, 1, 1, 1]] * 2))
    with pytest.raises(mot.MotFormatError, match="twice"):
        mot.read_ground_truth(sequence)


def test_tracker_rows_use_one_based_frames_xywh_boxes_and_mapped_classes() -> None:
    frames = [
        [[0, 0.9, 10, 20, 50, 80, 3], [2, 0.8, 0, 0, 5, 5, 4]],   # frame 0: person #3, car #4
        [[0, 0.7, 12, 22, 52, 82, 3], [0, 0.6, 1, 1, 2, 2, -1]],  # frame 1: person #3, unconfirmed person
    ]

    rows = mot.tracker_rows(frames, {0: 1})

    assert rows.tolist() == [[1, 3, 10, 20, 40, 60, 0.9, 1, -1, -1], [2, 3, 12, 22, 40, 60, 0.7, 1, -1, -1]]


def test_tracker_output_with_a_duplicate_id_in_one_frame_is_rejected() -> None:
    with pytest.raises(mot.MotFormatError, match="twice"):
        mot.tracker_rows([[[0, 0.9, 0, 0, 5, 5, 1], [0, 0.8, 9, 9, 15, 15, 1]]], {0: 1})


def test_written_rows_round_trip(tmp_path: Path) -> None:
    rows = mot.tracker_rows([[[0, 0.912345, 10.5, 20.25, 50, 80, 3]]], {0: 1})
    mot.write_rows(tmp_path / "out" / "SYN-01.txt", rows)

    assert (tmp_path / "out" / "SYN-01.txt").read_text(encoding="utf-8") == \
        "1,3,10.50,20.25,39.50,59.75,0.9123,1,-1,-1\n"


def test_iou_of_xywh_boxes() -> None:
    a = np.array([[0, 0, 10, 10]], float)
    b = np.array([[5, 0, 10, 10], [20, 20, 5, 5]], float)

    assert mot.iou_xywh(a, b) == pytest.approx(np.array([[50 / 150, 0]]))
    assert mot.iou_xywh(a, np.zeros((0, 4))).shape == (1, 0)


# --- Metrics (TrackEval) ------------------------------------------------------------------------

def _toy() -> tuple[np.ndarray, np.ndarray]:
    """2 GT objects x 5 frames; tracker switches the 2nd object's ID at frame 3 and misses it at frame 5."""
    gt, tracker = [], []
    for frame in range(1, 6):
        gt += [[frame, 1, 0, 0, 10, 10, 1, 1, 1], [frame, 2, 20, 20, 10, 10, 1, 1, 1]]
        tracker.append([frame, 7, 0, 0, 10, 10, 0.9, 1, -1, -1])
        if frame < 5:
            tracker.append([frame, 8 if frame < 3 else 9, 20, 20, 10, 10, 0.9, 1, -1, -1])
    return np.array(gt, float), np.array(tracker, float)


@needs_trackeval
def test_metrics_match_hand_computed_values() -> None:
    gt, tracker = _toy()

    result = mot.evaluate(mot.build_trackeval_data(gt, tracker, 5, eval_classes=(1,), distractor_classes=()))

    # 10 GT boxes, 9 matched, 1 miss, 1 ID switch, 0 false positives.
    assert (result["TP"], result["FN"], result["FP"], result["IDSW"]) == (9, 1, 0, 1)
    assert result["MOTA"] == pytest.approx(1 - (1 + 0 + 1) / 10)
    assert result["IDF1"] == pytest.approx(2 * 7 / (10 + 9))            # best one-to-one ID assignment
    assert result["DetA"] == pytest.approx(9 / 10)                      # every match has IoU 1
    assert result["AssA"] == pytest.approx((5 * 1 + 2 * 0.4 + 2 * 0.4) / 9)
    assert result["HOTA"] == pytest.approx(np.sqrt(0.9 * result["AssA"]))
    assert (result["precision"], result["recall"]) == (pytest.approx(1.0), pytest.approx(0.9))


@needs_trackeval
def test_tracker_boxes_on_distractors_are_removed_and_ignored_gt_is_not_scored() -> None:
    gt = np.array([[1, 1, 0, 0, 10, 10, 1, 1, 1],      # pedestrian
                   [1, 2, 50, 50, 10, 10, 1, 7, 1],    # static person: distractor
                   [1, 3, 80, 80, 10, 10, 0, 1, 1]], float)  # conf 0: ignored
    tracker = np.array([[1, 5, 0, 0, 10, 10, 0.9, 1, -1, -1], [1, 6, 50, 50, 10, 10, 0.9, 1, -1, -1]], float)

    data = mot.build_trackeval_data(gt, tracker, 1, eval_classes=(1,), distractor_classes=mot.MOT17_DISTRACTORS)
    result = mot.evaluate(data)

    assert data["removed_as_distractor"] == 1
    assert (result["TP"], result["FP"], result["FN"]) == (1, 0, 0)


@needs_trackeval
def test_matches_the_official_trackeval_motchallenge_evaluator(tmp_path: Path) -> None:
    """Our loader and preprocessing must give exactly the official devkit numbers (synthetic data)."""
    import trackeval

    rng = np.random.default_rng(0)
    gt, tracker = [], []
    length = 30
    for frame in range(1, length + 1):
        for person in range(1, 5):
            x, y = 20 + person * 120 + 3 * frame, 100 + person * 10
            gt.append([frame, person, x, y, 40, 90, 1, 1, 1])
            if not (person == 2 and 10 <= frame <= 13):
                track = 30 if person == 3 and frame > 18 else person
                tracker.append([frame, track, x + rng.normal(0, 2), y + rng.normal(0, 2), 40, 90, 0.9, 1, -1, -1])
        gt.append([frame, 50, 500, 300, 30, 60, 1, 7, 1])     # distractor followed by the tracker
        tracker.append([frame, 50, 501, 301, 30, 60, 0.8, 1, -1, -1])
        gt.append([frame, 60, 300, 350, 30, 60, 0, 1, 1])     # ignored ground truth
        if frame % 5 == 0:
            tracker.append([frame, 70, 100, 400, 30, 60, 0.6, 1, -1, -1])  # false positive
    sequence_dir = make_sequence(tmp_path / "gt", length=length, width=640, height=480, gt_rows=gt)
    mot.write_rows(tmp_path / "trackers" / "ours" / "data" / "SYN-01.txt", np.array(tracker))

    sequence = mot.load_sequence(sequence_dir)
    written = np.loadtxt(tmp_path / "trackers" / "ours" / "data" / "SYN-01.txt", delimiter=",")
    ours = mot.evaluate(mot.build_trackeval_data(mot.read_ground_truth(sequence), written, length,
                                                 eval_classes=(1,), distractor_classes=mot.MOT17_DISTRACTORS))

    config = trackeval.Evaluator.get_default_eval_config()
    config.update(PRINT_RESULTS=False, PRINT_CONFIG=False, OUTPUT_SUMMARY=False, OUTPUT_DETAILED=False,
                  PLOT_CURVES=False, TIME_PROGRESS=False)
    dataset_config = trackeval.datasets.MotChallenge2DBox.get_default_dataset_config()
    dataset_config.update(GT_FOLDER=str(tmp_path / "gt"), TRACKERS_FOLDER=str(tmp_path / "trackers"),
                          SKIP_SPLIT_FOL=True, SEQ_INFO={"SYN-01": None}, TRACKERS_TO_EVAL=["ours"],
                          BENCHMARK="MOT17", PRINT_CONFIG=False)
    with redirect_stdout(io.StringIO()):
        results, _ = trackeval.Evaluator(config).evaluate(
            [trackeval.datasets.MotChallenge2DBox(dataset_config)],
            [trackeval.metrics.HOTA(), trackeval.metrics.CLEAR({"PRINT_CONFIG": False}),
             trackeval.metrics.Identity({"PRINT_CONFIG": False})])
    official = next(iter(results.values()))["ours"]["SYN-01"]["pedestrian"]

    assert ours["HOTA"] == pytest.approx(float(np.mean(official["HOTA"]["HOTA"])))
    assert ours["MOTA"] == pytest.approx(float(official["CLEAR"]["MOTA"]))
    assert ours["IDF1"] == pytest.approx(float(official["Identity"]["IDF1"]))
    assert ours["IDSW"] == official["CLEAR"]["IDSW"]
    assert (ours["TP"], ours["FN"], ours["FP"]) == (official["CLEAR"]["CLR_TP"], official["CLEAR"]["CLR_FN"],
                                                    official["CLEAR"]["CLR_FP"])
    assert ours["IDSW"] == 1 and ours["FP"] == 6  # the distractor track is not a false positive


@needs_trackeval
def test_several_sequences_are_combined_by_trackeval() -> None:
    gt, tracker = _toy()
    data = mot.build_trackeval_data(gt, tracker, 5, eval_classes=(1,), distractor_classes=())

    results = mot.evaluate_many({"A": data, "B": data})

    assert set(results) == {"A", "B", "COMBINED"}
    assert results["COMBINED"]["TP"] == 18 and results["COMBINED"]["IDSW"] == 2
    assert results["COMBINED"]["MOTA"] == pytest.approx(results["A"]["MOTA"])


# --- Command line ------------------------------------------------------------------------------

def test_discover_accepts_sequence_folders_and_their_parent(tmp_path: Path) -> None:
    first, second = make_sequence(tmp_path, "A"), make_sequence(tmp_path, "B")

    assert discover([first]) == [first]
    assert discover([tmp_path]) == [first, second]
    with pytest.raises(mot.MotFormatError):
        discover([tmp_path / "missing"])


def test_class_map_parsing_and_consistency_checks(tmp_path: Path) -> None:
    assert _class_map("0:1,2:3") == {0: 1, 2: 3}
    sequence = make_sequence(tmp_path)
    with pytest.raises(SystemExit):
        main(["--sequences", str(sequence), "--detect-classes", "2", "--class-map", "0:1"])
    with pytest.raises(SystemExit):
        main(["--sequences", str(sequence), "--class-map", "0:3"])
