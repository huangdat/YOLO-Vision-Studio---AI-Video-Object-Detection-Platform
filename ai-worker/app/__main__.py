"""Start the HTTP service using environment-based settings."""

import uvicorn

from app.config.logging import logging_config
from app.config.settings import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        log_config=logging_config(settings.log_level),
    )


if __name__ == "__main__":
    main()
