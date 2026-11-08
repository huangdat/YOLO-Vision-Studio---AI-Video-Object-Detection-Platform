"""FastAPI application; inference and queue consumers arrive in later phases."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import logging
import logging.config

from fastapi import FastAPI

from app.api.health import router as health_router
from app.config.logging import logging_config
from app.config.settings import get_settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    logging.config.dictConfig(logging_config(settings.log_level))
    logger.info("AI worker HTTP service started; no inference or queue consumers enabled")
    yield
    logger.info("AI worker HTTP service stopped")


def create_app() -> FastAPI:
    application = FastAPI(
        title="YOLO Vision Studio AI Worker",
        version="1.0.0",
        description="CPU-compatible service foundation. Inference is not enabled.",
        lifespan=lifespan,
    )
    application.include_router(health_router)
    return application


app = create_app()
