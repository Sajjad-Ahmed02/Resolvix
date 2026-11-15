from fastapi import APIRouter, Response, status

from app.core.config import settings
from app.db.session import check_database_connection
from app.schemas.common import HealthResponse


router = APIRouter(tags=["Health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Application and database health",
    responses={
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "model": HealthResponse,
            "description": "The API is running but PostgreSQL is unavailable.",
        }
    },
)
def health_check(response: Response) -> HealthResponse:
    """Return API health and verify PostgreSQL with a lightweight query.

    Connection errors are logged server-side and reduced to a generic
    ``database: unavailable`` response, so credentials and stack traces never
    reach the client.
    """
    if not check_database_connection():
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(
            status="degraded",
            application=settings.APP_NAME,
            version=settings.APP_VERSION,
            database="unavailable",
        )

    return HealthResponse(
        status="healthy",
        application=settings.APP_NAME,
        version=settings.APP_VERSION,
        database="ok",
    )
