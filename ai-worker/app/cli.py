"""Explicit local entry point; importing this module never loads model weights."""

import argparse
import logging.config
from pathlib import Path
import sys

from pydantic import ValidationError

from app.config.logging import logging_config
from app.config.settings import get_settings
from app.core.exceptions import DetectionEngineError
from app.schemas.detection import DetectionRequest, SourceType
from app.schemas.progress import ProgressEvent


def parse_classes(value: str) -> list[int]:
    try:
        values = [int(item.strip()) for item in value.split(",")]
    except ValueError as error:
        raise argparse.ArgumentTypeError("Classes must be comma-separated integer identifiers") from error
    if not values or any(item < 0 for item in values) or len(set(values)) != len(values):
        raise argparse.ArgumentTypeError("Class identifiers must be unique nonnegative integers")
    return values


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="YOLO Vision Studio standalone video detection engine")
    commands = result.add_subparsers(dest="command", required=True)
    detect = commands.add_parser("detect", help="Process a local file or an authorized YouTube video")
    detect.add_argument("--source", required=True)
    detect.add_argument("--source-type", choices=("local", "youtube"), required=True)
    detect.add_argument("--model", default="yolo26s")
    detect.add_argument("--confidence", type=float)
    detect.add_argument("--imgsz", type=int)
    detect.add_argument("--classes", type=parse_classes)
    detect.add_argument("--device", choices=("auto", "cpu", "cuda:0"))
    detect.add_argument("--output", type=Path, help="Optional MP4 path inside AI_OUTPUT_DIR; existing files are rejected")
    prepare = commands.add_parser("prepare-model", help="Explicitly download/load approved YOLO26s weights")
    prepare.add_argument("--model", default="yolo26s")
    prepare.add_argument("--device", choices=("auto", "cpu", "cuda:0"))
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        settings = get_settings()
        logging.config.dictConfig(logging_config(settings.log_level))
        if args.command == "prepare-model":
            from app.services.model_loader import ModelLoader

            loaded = ModelLoader(settings).load(args.model, args.device or settings.ai_device)
            print(f"Prepared {loaded.model_key} on {loaded.device}; cache: {settings.model_cache_dir.resolve()}")
            return 0
        request = DetectionRequest(
            source=args.source,
            source_type=SourceType.LOCAL_FILE if args.source_type == "local" else SourceType.YOUTUBE_URL,
            model_key=args.model,
            confidence=args.confidence,
            image_size=args.imgsz,
            classes=args.classes,
            device=args.device,
            output_path=args.output,
        )
        from app.workers.detection_pipeline import DetectionPipeline

        def display(event: ProgressEvent) -> None:
            print(f"{event.stage.value:11} {event.progress:3}%  {event.message}", file=sys.stderr, flush=True)

        result = DetectionPipeline(settings).process_video(request, on_progress=display)
        print(result.statistics.model_dump_json(by_alias=True, indent=2))
        print(f"Output video: {result.output.video_path}")
        print(f"Result JSON: {result.output.metadata_path}")
        return 0
    except ValidationError:
        print("Invalid detection configuration or arguments. Check CLI help and AI_* settings.", file=sys.stderr)
        return 2
    except DetectionEngineError as error:
        print(f"Detection failed: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Detection interrupted; temporary resources were cleaned up.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
