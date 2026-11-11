"""Entrypoint of the dedicated ai-live-worker: the health route plus the internal Live API.

Run with ``python -m app.live_server``. The regular ai-worker HTTP service (``python -m app``)
and the RabbitMQ consumer do not expose these routes.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import logging
import logging.config

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
import uvicorn

from app.api.health import router as health_router
from app.api.live import create_live_router
from app.config.logging import logging_config
from app.config.settings import Settings, get_settings
from app.services.live_inference import LiveInferenceService

logger = logging.getLogger(__name__)


def create_live_app(service: LiveInferenceService | None = None, settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    service = service or LiveInferenceService(settings)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        logging.config.dictConfig(logging_config(settings.log_level))
        # No per-request access log: a session sends up to five frames per second. Loads,
        # evictions, and failures are logged by the service; session totals by Spring Boot.
        logging.getLogger("uvicorn.access").disabled = True
        logger.info(
            "Live worker started (max %d loaded model(s), %d concurrent inference(s), sizes %s, "
            "max frame %d bytes); models load on first use from the prepared cache only",
            settings.live_max_loaded_models, settings.live_max_concurrent_inferences,
            settings.live_model_sizes, settings.live_max_frame_bytes)
        yield
        logger.info("Live worker stopped")

    application = FastAPI(title="YOLO Vision Studio Live Worker", version="1.0.0", lifespan=lifespan,
                          docs_url=None, redoc_url=None, openapi_url=None)

    @application.exception_handler(RequestValidationError)
    async def invalid_parameters(request: Request, error: RequestValidationError) -> JSONResponse:
        # Do not echo input values back; report only which parameters are wrong.
        names = sorted({str(item.get("loc", ["", "?"])[-1]) for item in error.errors()})
        return JSONResponse(status_code=400, content={"error": {
            "code": "INVALID_PARAMETERS", "message": "Invalid or missing parameters: " + ", ".join(names) + "."}})

    application.include_router(health_router)
    application.include_router(create_live_router(service))
    return application


def main() -> None:
    settings = get_settings()
    uvicorn.run(create_live_app(settings=settings), host=settings.host, port=settings.port,
                log_config=logging_config(settings.log_level), access_log=False)


if __name__ == "__main__":
    main()
