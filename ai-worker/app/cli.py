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
    prepare = commands.add_parser(
        "prepare-model", help="Alias of 'models prepare': download if needed, then load and verify"
    )
    prepare.add_argument("--model", default="yolo26s")
    prepare.add_argument("--device", choices=("auto", "cpu", "cuda:0"))

    models = commands.add_parser("models", help="Inspect or prepare approved detection models")
    model_commands = models.add_subparsers(dest="models_command", required=True)
    listing = model_commands.add_parser("list", help="List approved models (no cache access or downloads)")
    listing.add_argument("--json", action="store_true", help="Print JSON instead of a table")
    status = model_commands.add_parser(
        "status", help="Show cache and verification status (never loads or downloads weights)"
    )
    status.add_argument("--model", help="Limit output to one approved model key")
    status.add_argument("--json", action="store_true", help="Print JSON instead of a table")
    explicit = model_commands.add_parser(
        "prepare", help="Explicitly download (if missing), load, and verify one approved model"
    )
    explicit.add_argument("--model", required=True)
    explicit.add_argument("--device", choices=("auto", "cpu", "cuda:0"))
    return result


def _model_rows(rows: list[dict[str, object]], columns: list[str]) -> str:
    widths = {column: max(len(column), *(len(str(row[column] if row[column] is not None else "-"))
                                         for row in rows)) for column in columns}
    lines = ["  ".join(column.ljust(widths[column]) for column in columns)]
    lines += ["  ".join(str(row[column] if row[column] is not None else "-").ljust(widths[column])
                        for column in columns) for row in rows]
    return "\n".join(lines)


def _models_command(args: argparse.Namespace) -> int:
    """Registry and cache inspection import no AI packages and never download."""
    import json

    from app.services.model_registry import MODEL_SPECS, get_model_spec, inspect_models

    settings = get_settings()
    if args.models_command == "list":
        rows: list[dict[str, object]] = [{
            "modelKey": spec.model_key, "version": spec.version, "modelSize": spec.model_size,
            "sizeName": spec.size_name, "taskType": spec.task_type, "weightsFilename": spec.weights_filename,
        } for spec in MODEL_SPECS]
        columns = ["modelKey", "version", "modelSize", "sizeName", "taskType", "weightsFilename"]
    elif args.models_command == "status":
        specs = MODEL_SPECS
        if args.model is not None:
            spec = get_model_spec(args.model)
            if spec is None:
                print("Unsupported model identifier. Run 'models list' for approved keys.", file=sys.stderr)
                return 2
            specs = (spec,)
        rows = [status.as_dict() for status in inspect_models(settings.model_cache_dir, specs)]
        columns = ["modelKey", "version", "modelSize", "status", "sizeBytes", "verifiedDevice", "verifiedAt"]
    else:
        return _prepare_model(args.model, args.device)
    print(json.dumps(rows, indent=2) if args.json else _model_rows(rows, columns))
    return 0


def _prepare_model(model_key: str, device: str | None) -> int:
    from app.services.model_loader import ModelLoader
    from app.services.model_registry import get_model_spec, inspect_model

    settings = get_settings()
    spec = get_model_spec(model_key)
    if spec is None:
        print("Unsupported model identifier. Run 'models list' for approved keys.", file=sys.stderr)
        return 2
    before = inspect_model(settings.model_cache_dir, spec)
    if not before.cached:
        print(f"Downloading official checkpoint {spec.weights_filename} into the model cache...", file=sys.stderr)
    loaded = ModelLoader(settings).load(spec.model_key, device or settings.ai_device, allow_download=True)
    after = inspect_model(settings.model_cache_dir, spec)
    if after.status.value != "VERIFIED":
        print(f"{spec.model_key} loaded, but its verification could not be recorded ({after.status.value}).",
              file=sys.stderr)
        return 1
    print(f"Prepared {loaded.model_key} ({spec.weights_filename}) on {loaded.device}: "
          f"{after.status.value}, {after.size_bytes} bytes; cache: {settings.model_cache_dir.resolve()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        settings = get_settings()
        logging.config.dictConfig(logging_config(settings.log_level))
        if args.command == "prepare-model":
            return _prepare_model(args.model, args.device)
        if args.command == "models":
            return _models_command(args)
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
        operation = "Detection" if args.command == "detect" else "Model preparation"
        print(f"{operation} failed: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Detection interrupted; temporary resources were cleaned up.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
