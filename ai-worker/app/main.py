"""Lightweight health API; video inference is invoked explicitly through the library or CLI."""

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
    logger.info("AI worker HTTP service started; no models loaded or queue consumers enabled")
    yield
    logger.info("AI worker HTTP service stopped")


def create_app() -> FastAPI:
    application = FastAPI(
        title="YOLO Vision Studio AI Worker",
        version="1.0.0",
        description="Health API. Standalone detection is available through the library and CLI.",
        lifespan=lifespan,
    )
    application.include_router(health_router)
    return application


app = create_app()
