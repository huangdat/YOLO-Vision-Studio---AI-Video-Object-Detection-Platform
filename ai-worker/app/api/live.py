"""Internal Live Detection API, served only by the ai-live-worker on the Compose network.

The Spring Boot gateway is its only client; it is never published to the host. Requests are
rejected instead of queued when the worker is busy, so slow inference cannot build a backlog.
"""

from __future__ import annotations

import asyncio
import re

import anyio
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from app.services.live_inference import LiveError, LiveInferenceService

CLASSES_PATTERN = re.compile(r"^\d{1,2}(,\d{1,2}){0,79}$")


def error_response(error: LiveError) -> JSONResponse:
    return JSONResponse(status_code=error.status, content={"error": {"code": error.code, "message": error.message}})


def create_live_router(service: LiveInferenceService) -> APIRouter:
    router = APIRouter(prefix="/internal/live", tags=["live"])
    slots = asyncio.Semaphore(service.settings.live_max_concurrent_inferences)

    async def run_exclusive(function, *args):  # type: ignore[no-untyped-def]
        # Non-blocking admission: a busy worker answers 429 rather than queueing the frame.
        if slots.locked():
            raise LiveError("WORKER_BUSY", "The live worker is processing another frame.", 429)
        async with slots:
            return await anyio.to_thread.run_sync(function, *args)

    @router.post("/models/{model_key}/load")
    async def load_model(model_key: str, image_size: int = Query(default=416, alias="imageSize")) -> JSONResponse:
        try:
            if not 32 <= image_size <= service.settings.live_max_image_size or image_size % 32:
                raise LiveError("INVALID_PARAMETERS", "imageSize must be a multiple of 32 within the live limit.", 400)
            loaded = await run_exclusive(service.load_model, model_key, image_size)
        except LiveError as error:
            return error_response(error)
        return JSONResponse({"modelKey": loaded.model_key, "device": loaded.device,
                             "classes": len(loaded.names)})

    @router.post("/infer")
    async def infer(
        request: Request,
        model_key: str = Query(alias="modelKey", min_length=1, max_length=64),
        frame_id: int = Query(alias="frameId"),
        confidence: float = Query(default=0.25, allow_inf_nan=False),
        image_size: int = Query(default=416, alias="imageSize"),
        classes: str = Query(default="1,2,3,5,7", max_length=239),
    ) -> JSONResponse:
        try:
            if not CLASSES_PATTERN.match(classes):
                raise LiveError("INVALID_PARAMETERS", "classes must be comma-separated COCO class IDs.", 400)
            settings = service.validate(model_key, frame_id, confidence, image_size,
                                        [int(value) for value in classes.split(",")])
            content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
            if content_type != "image/jpeg":
                raise LiveError("INVALID_FRAME", "Frames must be sent as image/jpeg.", 400)
            frame = await _read_bounded(request, service.settings.live_max_frame_bytes)
            result = await run_exclusive(service.infer, frame, settings)
        except LiveError as error:
            return error_response(error)
        return JSONResponse(result)

    return router


async def _read_bounded(request: Request, limit: int) -> bytes:
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > limit:
        raise LiveError("FRAME_TOO_LARGE", f"The frame exceeds {limit} bytes.", 413)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > limit:
            raise LiveError("FRAME_TOO_LARGE", f"The frame exceeds {limit} bytes.", 413)
    return bytes(body)
