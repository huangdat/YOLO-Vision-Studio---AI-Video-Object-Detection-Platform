"""Public health response contract."""

from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    service: Literal["ai-worker"] = "ai-worker"
    status: Literal["UP"] = "UP"
