"""Explicit local entry point; importing this module never loads model weights."""

import argparse
import logging.config
from pathlib import Path
import sys

from pydantic import ValidationError

from app.config.logging import logging_config
from app.config.settings import get_settings
from app.core.exceptions import DetectionEngineError
from app.schemas.detection import DetectionRequest, ProcessingMode, SourceType
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
    detect.add_argument("--tracking", action="store_true",
                        help="Also run ByteTrack so detections keep persistent Track IDs")
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

    quantize = model_commands.add_parser(
        "quantize", help="Export a prepared model to OpenVINO INT8 (post-training quantization, CPU)"
    )
    quantize.add_argument("--model", required=True)
    quantize.add_argument("--imgsz", type=int, help="Calibration image size (default: AI_DEFAULT_IMAGE_SIZE)")
    calibration = quantize.add_mutually_exclusive_group(required=True)
    calibration.add_argument("--data", help="Ultralytics dataset YAML whose 'val' images are used for calibration")
    calibration.add_argument("--calibration-video", type=Path,
                             help="Local video; evenly spaced frames become an unlabeled calibration set")
    calibration.add_argument("--calibration-images", type=Path, nargs="+", metavar="DIR",
                             help="Image folders (e.g. several scenes); --calibration-frames are shared evenly")
    quantize.add_argument("--calibration-frames", type=int, default=300,
                          help="Maximum frames sampled from --calibration-video (default: 300)")
    quantize.add_argument("--calibration-start", type=int, default=0, help="First frame index to sample")
    quantize.add_argument("--calibration-end", type=int, help="Frame index to stop sampling before")
    quantize.add_argument("--fraction", type=float, default=1.0,
                          help="Fraction of the --data calibration images to use (default: 1.0)")
    int8_status = model_commands.add_parser(
        "int8-status", help="Show INT8 artifact status (never loads or exports anything)"
    )
    int8_status.add_argument("--model", help="Limit output to one approved model key")
    int8_status.add_argument("--json", action="store_true", help="Print JSON instead of a table")
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
    elif args.models_command == "int8-status":
        from app.services.model_quantization import inspect_int8_artifact

        specs = MODEL_SPECS
        if args.model is not None:
            spec = get_model_spec(args.model)
            if spec is None:
                print("Unsupported model identifier. Run 'models list' for approved keys.", file=sys.stderr)
                return 2
            specs = (spec,)
        rows = [inspect_int8_artifact(settings, spec).as_dict() for spec in specs]
        columns = ["modelKey", "format", "status", "sizeBytes", "exportImageSize", "calibrationImages", "createdAt"]
    elif args.models_command == "quantize":
        return _quantize_model(args)
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


def _quantize_model(args: argparse.Namespace) -> int:
    """Explicit INT8 export. Never downloads weights: the FP32 model must already be prepared."""
    import shutil
    import uuid

    from app.services.model_loader import ModelLoader
    from app.services.model_quantization import (
        build_calibration_dataset, build_calibration_dataset_from_images, export_int8,
    )
    from app.services.model_registry import get_model_spec

    settings = get_settings()
    spec = get_model_spec(args.model)
    if spec is None:
        print("Unsupported model identifier. Run 'models list' for approved keys.", file=sys.stderr)
        return 2
    image_size = args.imgsz or settings.default_image_size
    workspace: Path | None = None
    try:
        calibration = None
        validation_image = None
        data: str | Path = args.data or ""
        if args.calibration_images is not None:
            names = ModelLoader(settings).load(spec.model_key, "cpu", allow_download=False,
                                               record_verification=False, precision="fp32").names
            workspace = settings.temp_dir.expanduser().resolve() / f"calibration-{uuid.uuid4().hex[:8]}"
            image_set = build_calibration_dataset_from_images(
                args.calibration_images, workspace, names, max_images=args.calibration_frames)
            data, calibration = image_set.data_yaml, image_set.describe()
            validation_image = next((workspace / "images" / "val").glob("*"), None)
            print(f"Calibration set: {image_set.images} images from "
                  + ", ".join(f"{item['name']} ({item['used']})" for item in image_set.sources), file=sys.stderr)
        elif args.calibration_video is not None:
            if not args.calibration_video.is_file():
                print("The calibration video does not exist.", file=sys.stderr)
                return 2
            names = ModelLoader(settings).load(spec.model_key, "cpu", allow_download=False,
                                               record_verification=False, precision="fp32").names
            workspace = settings.temp_dir.expanduser().resolve() / f"calibration-{uuid.uuid4().hex[:8]}"
            dataset = build_calibration_dataset(
                args.calibration_video, workspace, names, max_images=args.calibration_frames,
                start_frame=args.calibration_start, end_frame=args.calibration_end,
            )
            data, calibration = dataset.data_yaml, dataset.describe()
            validation_image = next((workspace / "images" / "val").glob("*.jpg"), None)
            print(f"Calibration set: {dataset.images} frames from {dataset.source} "
                  f"(frames {dataset.frame_range[0]}-{dataset.frame_range[1]}, every {dataset.stride})",
                  file=sys.stderr)
        result = export_int8(settings, spec.model_key, data=data, image_size=image_size, fraction=args.fraction,
                             calibration=calibration, validation_image=validation_image)
    finally:
        if workspace is not None:
            shutil.rmtree(workspace, ignore_errors=True)
    ratio = result.int8_size_bytes / result.fp32_size_bytes if result.fp32_size_bytes else 0
    print(f"Exported {spec.model_key} to OpenVINO INT8: {result.status.status.value}, "
          f"{result.int8_size_bytes} bytes ({ratio:.0%} of the {result.fp32_size_bytes}-byte FP32 checkpoint), "
          f"{result.fake_quantize_nodes} quantized operations; directory: {result.status.directory}")
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
            processing_mode=ProcessingMode.DETECTION_TRACKING if args.tracking else ProcessingMode.DETECTION_ONLY,
        )
        from app.workers.detection_pipeline import DetectionPipeline

        def display(event: ProgressEvent) -> None:
            print(f"{event.stage.value:11} {event.progress:3}%  {event.message}", file=sys.stderr, flush=True)

        result = DetectionPipeline(settings).process_video(request, on_progress=display)
        print(result.statistics.model_dump_json(by_alias=True, indent=2))
        if getattr(result, "tracking", None) is not None:
            print(result.tracking.model_dump_json(by_alias=True, indent=2, exclude={"tracks"}))
        print(f"Output video: {result.output.video_path}")
        print(f"Result JSON: {result.output.metadata_path}")
        return 0
    except ValidationError:
        print("Invalid detection configuration or arguments. Check CLI help and AI_* settings.", file=sys.stderr)
        return 2
    except DetectionEngineError as error:
        operation = ("Detection" if args.command == "detect"
                     else "Quantization" if getattr(args, "models_command", None) == "quantize"
                     else "Model preparation")
        print(f"{operation} failed: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Detection interrupted; temporary resources were cleaned up.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
