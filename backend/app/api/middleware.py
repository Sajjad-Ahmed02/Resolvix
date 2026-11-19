"""HTTP middleware shared by every API route."""

from __future__ import annotations

import logging
import re
import time
from uuid import uuid4

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import (
    get_request_id,
    reset_request_id,
    set_request_id,
)

REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")

logger = logging.getLogger("resolvix.http")


class RequestIdMiddleware:
    """Correlate one HTTP request across every log boundary.

    A caller may supply ``X-Request-ID`` (for example from a reverse proxy),
    but only a short, log-safe value is accepted. Anything else is replaced
    with a fresh identifier so header content cannot inject log fields.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = ""
        for key, value in scope.get("headers", []):
            if key.lower() == b"x-request-id":
                incoming = value.decode("latin-1").strip()
                break

        request_id = (
            incoming if _REQUEST_ID_PATTERN.fullmatch(incoming) else uuid4().hex
        )
        token = set_request_id(request_id)
        scope.setdefault("state", {})["request_id"] = request_id

        status_code = 500
        started = time.perf_counter()

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            logger.info(
                "HTTP request completed",
                extra={
                    "event": "http_request",
                    "method": scope.get("method", ""),
                    "path": scope.get("path", ""),
                    "status_code": status_code,
                    "duration_ms": round(
                        (time.perf_counter() - started) * 1000,
                        2,
                    ),
                },
            )
            reset_request_id(token)


def current_request_id() -> str:
    """Read the request id from request context (used by exception handlers)."""
    return get_request_id()
