from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.api.middleware import REQUEST_ID_HEADER, RequestIdMiddleware
from app.api.routes import api_router
from app.core.config import settings
from app.core.logging import configure_logging, get_request_id


configure_logging()
logger = logging.getLogger("resolvix")


def _request_id(request: Request | None = None) -> str:
    if request is not None:
        value = getattr(request.state, "request_id", None)
        if isinstance(value, str) and value:
            return value
    return get_request_id()


def _error_body(detail: str, request_id: str) -> dict[str, str]:
    return {"detail": detail, "request_id": request_id}


app = FastAPI(
    title=settings.APP_NAME,
    description=(
        "AI-powered customer-support API for Resolvix. Authenticate with "
        "POST /auth/login to receive HttpOnly access and refresh cookies, or "
        "use the returned JWT as a bearer token. Customer identity is always "
        "derived from the token."
    ),
    version=settings.APP_VERSION,
    debug=False,
    openapi_tags=[
        {
            "name": "Health",
            "description": "API liveness and PostgreSQL connectivity checks.",
        },
        {
            "name": "Authentication",
            "description": (
                "JWT login, silent refresh, current-user lookup, and logout. "
                "Browsers use HttpOnly cookies; API clients may use the "
                "returned bearer token. Public registration is disabled."
            ),
        },
        {
            "name": "Conversations",
            "description": (
                "Read-only conversation access scoped to the authenticated "
                "customer."
            ),
        },
        {
            "name": "Orders",
            "description": (
                "Read-only order access scoped to the authenticated customer."
            ),
        },
        {
            "name": "Administration",
            "description": (
                "Administrator-only endpoints. Customer tokens receive 403."
            ),
        },
    ],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[REQUEST_ID_HEADER],
)

# Added last so it wraps CORS and every error response, including the safe
# handlers below. Each response carries the same X-Request-ID that appears in
# the structured logs.
app.add_middleware(RequestIdMiddleware)


@app.exception_handler(SQLAlchemyError)
async def database_exception_handler(
    request: Request,
    exc: SQLAlchemyError,
) -> JSONResponse:
    """Reduce database failures to a safe, retryable 503.

    Connection strings, SQL text, and driver details stay in server-side logs.
    The request id lets the same failure be found in those logs.
    """
    request_id = _request_id(request)
    logger.exception(
        "Database operation failed",
        extra={
            "event": "database_error",
            "operation": "database_access",
            "request_id": request_id,
            "error_type": type(exc).__name__,
            "method": request.method,
            "path": request.url.path,
        },
    )
    return JSONResponse(
        status_code=503,
        content=_error_body(
            "A data service is temporarily unavailable. Please try again.",
            request_id,
        ),
        headers={REQUEST_ID_HEADER: request_id},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """Log unexpected errors server-side and return a sanitized response.

    Stack traces, database URLs, and secret values are never included in the
    HTTP response.
    """
    request_id = _request_id(request)
    logger.exception(
        "Unhandled exception while processing request",
        extra={
            "event": "unhandled_exception",
            "request_id": request_id,
            "error_type": type(exc).__name__,
            "method": request.method,
            "path": request.url.path,
        },
    )
    return JSONResponse(
        status_code=500,
        content=_error_body("An unexpected error occurred.", request_id),
        headers={REQUEST_ID_HEADER: request_id},
    )


app.include_router(api_router)


@app.get("/", tags=["Health"], summary="API root")
def root() -> dict[str, str]:
    return {
        "message": "Welcome to Resolvix API",
        "status": "running",
        "version": settings.APP_VERSION,
    }
