from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import api_router
from app.core.config import settings


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("resolvix")


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
    logger.exception(
        "Unhandled exception while processing %s %s",
        request.method,
        request.url.path,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "An unexpected error occurred."},
    )


app.include_router(api_router)


@app.get("/", tags=["Health"], summary="API root")
def root() -> dict[str, str]:
    return {
        "message": "Welcome to Resolvix API",
        "status": "running",
        "version": settings.APP_VERSION,
    }
