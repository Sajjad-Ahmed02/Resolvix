from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.db.session import get_db
from app.models import User
from app.schemas.auth import LoginRequest, TokenResponse
from app.schemas.common import ErrorResponse
from app.schemas.user import UserRead
from app.services import auth as auth_service


router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Authenticate a customer or administrator",
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "model": ErrorResponse,
            "description": "Invalid email or password.",
        }
    },
)
def login(
    payload: LoginRequest,
    session: Session = Depends(get_db),
) -> TokenResponse:
    """Authenticate a pre-seeded account and issue a JWT access token.

    Public registration is intentionally unavailable. Unknown accounts and
    wrong passwords return the same 401 response to prevent account discovery.
    """
    result = auth_service.authenticate_and_issue_token(
        session,
        email=str(payload.email),
        password=payload.password,
    )

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user, access_token, expires_in = result
    return TokenResponse(
        access_token=access_token,
        expires_in=expires_in,
        user=UserRead.model_validate(user),
    )


@router.get(
    "/me",
    response_model=UserRead,
    summary="Return the authenticated user and role",
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "model": ErrorResponse,
            "description": "Missing, invalid, or expired access token.",
        }
    },
)
def read_current_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """Return the user derived from the bearer token, including their role."""
    return current_user


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Log out (client discards the stateless token)",
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "model": ErrorResponse,
            "description": "Missing, invalid, or expired access token.",
        }
    },
)
def logout(_: User = Depends(get_current_user)) -> None:
    """Acknowledge logout.

    Access tokens are stateless JWTs, so the client must discard the token.
    Server-side revocation can be added when refresh tokens are introduced.
    """
    return None
