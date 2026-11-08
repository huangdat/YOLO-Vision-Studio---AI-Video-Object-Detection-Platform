"""Explicit real-model smoke test. Never imported or executed by normal pytest runs."""

import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile

from app.config.settings import get_settings
from app.schemas.detection import DetectionRequest, SourceType


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Explicit CPU/GPU real-model smoke test; may download the selected weights")
    parser.add_argument("--duration", type=float, default=3)
    parser.add_argument("--fps", type=int, default=12)
    parser.add_argument("--imgsz", type=int, default=320)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda:0"), default="cpu")
    parser.add_argument("--model", default="yolo26s", help="Approved detection model key")
    parser.add_argument("--fixture-image", type=Path, help="Optional developer-owned local image to repeat as video")
    args = parser.parse_args(argv)
    if not 2 <= args.duration <= 5 or not 1 <= args.fps <= 30 or args.imgsz <= 0:
        parser.error("Use a duration of 2-5 seconds, FPS of 1-30, and a positive image size")

    # Heavy dependencies are intentionally imported only after explicit invocation.
    import cv2
    import numpy as np

    from app.workers.detection_pipeline import DetectionPipeline

    settings = get_settings()
    settings.temp_dir.mkdir(parents=True, exist_ok=True)
    image_path = args.fixture_image
    if image_path is None:
        spec = importlib.util.find_spec("ultralytics")
        bundled = Path(spec.origin).parent / "assets" / "bus.jpg" if spec and spec.origin else None
        if bundled is not None and bundled.is_file():
            image_path = bundled
    image = cv2.imread(str(image_path)) if image_path is not None else None
    if image_path is not None and image is None:
        raise RuntimeError("The smoke fixture image could not be read")
    expected_frames = round(args.duration * args.fps)
    with tempfile.TemporaryDirectory(prefix="smoke-input-", dir=settings.temp_dir.resolve()) as fixture:
        source = Path(fixture) / "source.avi"
        writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*"MJPG"), args.fps, (320, 320))
        if not writer.isOpened():
            raise RuntimeError("The smoke fixture video writer could not be initialized")
        try:
            for index in range(expected_frames):
                if image is not None:
                    frame = cv2.resize(image, (320, 320))
                else:
                    frame = np.zeros((320, 320, 3), dtype=np.uint8)
                    cv2.rectangle(frame, (20 + index % 30, 140), (180 + index % 30, 220), (120, 180, 240), -1)
                cv2.putText(frame, f"Frame {index + 1}", (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
                writer.write(frame)
        finally:
            writer.release()
        runtime_settings = settings.model_copy(update={"local_input_dir": Path(fixture)})
        result = DetectionPipeline(runtime_settings).process_video(DetectionRequest(
            source=str(source), source_type=SourceType.LOCAL_FILE,
            model_key=args.model, device=args.device, image_size=args.imgsz,
        ))
    probe = subprocess.run([
        settings.ffprobe_path, "-v", "error", "-show_streams", "-show_format", "-of", "json",
        str(result.output.video_path),
    ], check=True, capture_output=True, text=True, timeout=settings.processing_timeout_seconds)
    streams = json.loads(probe.stdout)["streams"]
    video = next(stream for stream in streams if stream["codec_type"] == "video")
    decoded_frames = 0
    capture = cv2.VideoCapture(str(result.output.video_path))
    try:
        if not capture.isOpened():
            raise RuntimeError("The encoded smoke output could not be opened")
        while True:
            readable, frame = capture.read()
            if not readable:
                break
            if frame.shape[:2] != (320, 320):
                raise RuntimeError("The smoke output dimensions changed unexpectedly")
            decoded_frames += 1
    finally:
        capture.release()
    metadata = json.loads(result.output.metadata_path.read_text(encoding="utf-8"))
    assert video["codec_name"] == "h264" and video["pix_fmt"] == "yuv420p"
    assert not any(stream["codec_type"] == "audio" for stream in streams)
    assert decoded_frames == expected_frames == result.statistics.total_frames_processed
    assert metadata["statistics"]["totalFramesProcessed"] == expected_frames
    assert metadata["modelKey"] == metadata["statistics"]["modelKey"] == args.model
    assert metadata["weightsFilename"] == f"{args.model}.pt"
    assert result.output.video_path.stat().st_size > 0
    report = {
        "modelKey": result.model_key,
        "modelVersion": result.model_version,
        "weightsFilename": result.weights_filename,
        "device": result.device,
        "inputDurationSeconds": expected_frames / args.fps,
        "inputFixture": "bundled/local image" if image is not None else "generated geometric pattern",
        "totalFramesProcessed": result.statistics.total_frames_processed,
        "decodedOutputFrames": decoded_frames,
        "outputVideoPath": str(result.output.video_path),
        "resultJsonPath": str(result.output.metadata_path),
        "outputCodec": video["codec_name"],
        "pixelFormat": video["pix_fmt"],
        "processingTimeMs": result.processing_time_ms,
        "totalDetections": result.statistics.total_detections,
        "detectionsByClass": result.statistics.detections_by_class,
    }
    report_path = result.output.video_path.parent / "smoke-report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
