from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["healthy", "degraded"]
    application: str
    version: str
    database: Literal["ok", "unavailable"]


class ErrorResponse(BaseModel):
    """Generic error envelope used by authentication and authorization errors."""

    detail: str
