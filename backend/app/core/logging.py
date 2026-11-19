"""Structured logging and request/operation correlation.

The application emits one JSON object per log record by default. Every record
carries the current HTTP request id and, while an agent turn is running, an
operation id. Those identifiers make it possible to follow one request across
the API, agent, provider, tool, retrieval, embedding, and database boundaries
without building a separate tracing service.
"""

from __future__ import annotations

import json
import logging
import sys
from contextlib import contextmanager
from contextvars import ContextVar, Token
from datetime import datetime, timezone
from typing import Any, Iterator
from uuid import uuid4

from app.core.config import settings

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
operation_id_var: ContextVar[str] = ContextVar("operation_id", default="-")

_UNSET = "-"

# Attributes created by logging.LogRecord itself. Everything else in
# record.__dict__ is an application-supplied structured field.
_STANDARD_RECORD_ATTRIBUTES = frozenset(
    vars(
        logging.LogRecord(
            name="",
            level=0,
            pathname="",
            lineno=0,
            msg="",
            args=(),
            exc_info=None,
        )
    )
) | {"message", "asctime", "taskName"}


def get_request_id() -> str:
    """Return the request id for the current task, or ``-`` outside a request."""
    return request_id_var.get()


def get_operation_id() -> str:
    """Return the agent operation id for the current task, or ``-``."""
    return operation_id_var.get()


def set_request_id(request_id: str) -> Token[str]:
    """Set the request id and return the token needed to reset it."""
    return request_id_var.set(request_id)


def reset_request_id(token: Token[str]) -> None:
    request_id_var.reset(token)


@contextmanager
def operation_context(operation_id: str | None = None) -> Iterator[str]:
    """Correlate every log emitted inside one agent turn.

    Context variables are task-local, so parallel requests keep separate
    operation ids even though they share the process-wide logger.
    """
    value = operation_id or f"op_{uuid4().hex[:16]}"
    token = operation_id_var.set(value)
    try:
        yield value
    finally:
        operation_id_var.reset(token)


class RequestContextFilter(logging.Filter):
    """Attach request and operation identifiers to every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        # Exception handlers run outside the request middleware, so they set
        # the id explicitly on the record. Do not overwrite that value.
        if not getattr(record, "request_id", None):
            record.request_id = request_id_var.get()
        if not getattr(record, "operation_id", None):
            record.operation_id = operation_id_var.get()
        return True


def _json_safe(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    return str(value)


class JsonFormatter(logging.Formatter):
    """Render a log record as one line of structured JSON."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created,
                tz=timezone.utc,
            )
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", _UNSET),
            "operation_id": getattr(record, "operation_id", _UNSET),
        }

        for key, value in record.__dict__.items():
            if key in _STANDARD_RECORD_ATTRIBUTES or key == "event":
                continue
            if key in {"request_id", "operation_id"}:
                continue
            if key.startswith("_"):
                continue
            payload[key] = _json_safe(value)

        event = getattr(record, "event", None)
        if isinstance(event, str) and event:
            payload["event"] = event

        if record.exc_info:
            # Stack traces stay server-side. The HTTP layer returns only a
            # generic message and the request id.
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False, default=str)


class TextFormatter(logging.Formatter):
    """Readable local formatter that still carries correlation ids."""

    def __init__(self) -> None:
        super().__init__(
            "%(asctime)s %(levelname)s %(name)s "
            "[request_id=%(request_id)s operation_id=%(operation_id)s] "
            "%(message)s"
        )


def configure_logging(
    *,
    level: str | None = None,
    log_format: str | None = None,
) -> None:
    """Install one structured root handler.

    Idempotent so importing the app in tests or reloading uvicorn does not
    accumulate handlers. Uvicorn's default handlers are disabled so its
    records flow through the same JSON formatter.
    """
    resolved_level = (level or settings.LOG_LEVEL).upper()
    resolved_format = (log_format or settings.LOG_FORMAT).lower()

    root = logging.getLogger()
    root.setLevel(resolved_level)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RequestContextFilter())
    handler.setFormatter(
        JsonFormatter() if resolved_format == "json" else TextFormatter()
    )
    root.addHandler(handler)

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        for existing in list(uvicorn_logger.handlers):
            uvicorn_logger.removeHandler(existing)
        uvicorn_logger.propagate = True
