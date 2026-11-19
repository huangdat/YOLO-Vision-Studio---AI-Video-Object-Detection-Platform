"""Time the Python ObjectTracker (Ultralytics BYTETracker) on saved parity fixtures.

    python -m benchmarks.tracker_replay ../frontend/src/lib/tracking/__fixtures__/parity-traffic-5fps.json --repeats 5

Replays exactly the detections the TypeScript parity test uses, so both trackers are timed on the
same input. Reports the per-frame update time (mean, P95) and checks the Track IDs match the fixture.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import time


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("fixtures", nargs="+", type=Path)
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args(argv)

    from app.schemas.detection import DetectionBox
    from app.services.object_tracking import ByteTrackParameters, ObjectTracker

    report = []
    for path in args.fixtures:
        fixture = json.loads(path.read_text(encoding="utf-8"))
        config = fixture["config"]
        frames = [[DetectionBox(class_id=b[0], label=str(b[0]), confidence=b[1], xyxy=tuple(b[2:6]))
                   for b in frame["detections"]] for frame in fixture["frames"]]
        timings: list[float] = []
        mismatches = 0
        for _ in range(args.repeats):
            tracker = ObjectTracker(ByteTrackParameters.for_confidence(config["confidence"], config["trackBuffer"]))
            for boxes, frame in zip(frames, fixture["frames"]):
                started = time.perf_counter()
                tracked = tracker.update(boxes)
                timings.append((time.perf_counter() - started) * 1000)
                ids = [obj.track_id for obj in tracked.objects]
                if ids != [expected[1] for expected in frame["expected"]["objects"]]:
                    mismatches += 1
            tracker.close()
        ordered = sorted(timings)
        report.append({"fixture": fixture["name"], "frames": len(frames), "repeats": args.repeats,
                       "pythonMsMean": round(statistics.mean(timings), 4),
                       "pythonMsP95": round(ordered[int(0.95 * (len(ordered) - 1))], 4),
                       "mismatchedFrames": mismatches})
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
