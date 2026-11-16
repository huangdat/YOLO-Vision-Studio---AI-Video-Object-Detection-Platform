"""Python vs TypeScript ByteTrack parity fixtures (hybrid tracking).

Runs real YOLO detections on frames of a video or an image folder, the way a CLIENT tracking live
session gets them (every box from ByteTrack's low-score floor, no tracking), then runs the Python
ObjectTracker (Ultralytics BYTETracker, as the workers use it) over exactly those detections. The
fixture holds both, so the browser tracker (frontend/src/lib/tracking) can be checked frame by frame:

    python -m benchmarks.tracker_parity --source temp/quantization-poc/holdout.mp4 --every 5 \
        --classes 1,2,3,5,7 --track-buffer 10 --name traffic-5fps \
        --output ../frontend/src/lib/tracking/__fixtures__/parity-traffic-5fps.json

Box coordinates and scores are stored as float32 values (what YOLO produced), so both trackers see
bit-identical input. Detections never leave this machine; fixtures contain numbers only.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import sys
import time

import numpy as np

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp"}


def frames(source: Path, every: int, limit: int):
    import cv2

    if source.is_dir():
        files = sorted(p for p in source.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
        for index, path in enumerate(files):
            if index % every == 0:
                yield cv2.imread(str(path))
                limit -= 1
                if limit == 0:
                    return
        return
    capture = cv2.VideoCapture(str(source))
    index = 0
    try:
        while limit:
            ok, image = capture.read()
            if not ok:
                return
            if index % every == 0:
                yield image
                limit -= 1
            index += 1
    finally:
        capture.release()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--model", default="yolo11n")
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--classes", default="1,2,3,5,7")
    parser.add_argument("--every", type=int, default=5, help="Keep every Nth frame (5 = live rate from 25 fps)")
    parser.add_argument("--max-frames", type=int, default=200)
    parser.add_argument("--track-buffer", type=int, default=10)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    from app.config.settings import Settings
    from app.schemas.detection import DetectionBox
    from app.services.detection_service import DetectionService
    from app.services.model_loader import ModelLoader
    from app.services.object_tracking import ByteTrackParameters, ObjectTracker

    classes = [int(value) for value in args.classes.split(",")]
    loaded = ModelLoader(Settings()).load(args.model, args.device, allow_download=False, record_verification=False,
                                          precision="fp32")
    parameters = ByteTrackParameters.for_confidence(args.conf, args.track_buffer)
    service = DetectionService()
    recorded = []
    height = width = 0
    for image in frames(args.source, args.every, args.max_frames):
        height, width = image.shape[:2]
        detected = service.detect_image(image, loaded, parameters.inference_confidence, args.imgsz, classes)
        recorded.append([[box.class_id, float(np.float32(box.confidence)), *[float(np.float32(v)) for v in box.xyxy]]
                         for box in detected.boxes])

    tracker = ObjectTracker(parameters)
    expected, timings = [], []
    try:
        for boxes in recorded:
            inputs = [DetectionBox(class_id=b[0], label=str(b[0]), confidence=b[1], xyxy=tuple(b[2:6])) for b in boxes]
            started = time.perf_counter()
            tracked = tracker.update(inputs)
            timings.append((time.perf_counter() - started) * 1000)
            # Map reported objects back to input indices (objects keep input order and the input's values).
            out, cursor = [], 0
            for obj in tracked.objects:
                while (inputs[cursor].xyxy, inputs[cursor].confidence) != (obj.xyxy, obj.confidence):
                    cursor += 1
                out.append([cursor, obj.track_id])
                cursor += 1
            expected.append({"objects": out, "activeTracks": tracked.active_tracks})
    finally:
        tracker.close()

    fixture = {
        "name": args.name, "source": args.source.name, "model": args.model, "imgsz": args.imgsz,
        "classes": classes, "every": args.every, "width": width, "height": height,
        "config": {"confidence": args.conf, "lowScoreFloor": parameters.inference_confidence,
                   "trackBuffer": args.track_buffer, "matchThresh": parameters.match_thresh,
                   "fuseScore": parameters.fuse_score},
        "frames": [{"detections": d, "expected": e} for d, e in zip(recorded, expected)],
        "python": {"frames": len(recorded), "boxes": sum(len(d) for d in recorded),
                   "trackingMsMean": round(statistics.mean(timings), 4), "trackingMsP95":
                   round(sorted(timings)[int(0.95 * (len(timings) - 1))], 4)},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(fixture, separators=(",", ":")), encoding="utf-8")
    ids = {o[1] for e in expected for o in e["objects"] if o[1] is not None}
    print(f"{args.name}: {len(recorded)} frames, {fixture['python']['boxes']} boxes, {len(ids)} track IDs, "
          f"Python ByteTrack {fixture['python']['trackingMsMean']} ms/frame -> {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
