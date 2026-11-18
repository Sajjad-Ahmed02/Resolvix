from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.models import User
from app.schemas.auth import LoginRequest, TokenResponse
from app.schemas.common import ErrorResponse
from app.schemas.user import UserRead
from app.services import auth as auth_service
from app.services.auth import AuthTokens


router = APIRouter(prefix="/auth", tags=["Authentication"])

REFRESH_COOKIE_PATH = "/auth"


def _cookie_settings() -> dict:
    return {
        "httponly": True,
        "secure": settings.COOKIE_SECURE,
        "samesite": settings.COOKIE_SAMESITE,
        "domain": settings.COOKIE_DOMAIN,
    }


def _set_session_cookies(response: Response, tokens: AuthTokens) -> None:
    """Write HttpOnly access and refresh cookies for the browser session."""
    response.set_cookie(
        key=settings.ACCESS_TOKEN_COOKIE_NAME,
        value=tokens.access_token,
        max_age=tokens.expires_in,
        path="/",
        **_cookie_settings(),
    )
    response.set_cookie(
        key=settings.REFRESH_TOKEN_COOKIE_NAME,
        value=tokens.refresh_token,
        max_age=tokens.refresh_expires_in,
        path=REFRESH_COOKIE_PATH,
        **_cookie_settings(),
    )


def _clear_session_cookies(response: Response) -> None:
    response.delete_cookie(
        key=settings.ACCESS_TOKEN_COOKIE_NAME,
        path="/",
        domain=settings.COOKIE_DOMAIN,
        secure=settings.COOKIE_SECURE,
        httponly=True,
        samesite=settings.COOKIE_SAMESITE,
    )
    response.delete_cookie(
        key=settings.REFRESH_TOKEN_COOKIE_NAME,
        path=REFRESH_COOKIE_PATH,
        domain=settings.COOKIE_DOMAIN,
        secure=settings.COOKIE_SECURE,
        httponly=True,
        samesite=settings.COOKIE_SAMESITE,
    )


def _token_response(user: User, tokens: AuthTokens) -> TokenResponse:
    return TokenResponse(
        access_token=tokens.access_token,
        expires_in=tokens.expires_in,
        refresh_expires_in=tokens.refresh_expires_in,
        user=UserRead.model_validate(user),
    )


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
    response: Response,
    session: Session = Depends(get_db),
) -> TokenResponse:
    """Authenticate a pre-seeded account and start a cookie session.

    A short-lived access token and a long-lived, revocable refresh token are
    written as HttpOnly cookies. The web client never stores tokens in
    JavaScript-accessible storage, and the refresh cookie keeps the user signed
    in after the access token expires.
    """
    user = auth_service.authenticate_user(
        session,
        email=str(payload.email),
        password=payload.password,
    )

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    tokens = auth_service.issue_session_tokens(session, user)
    _set_session_cookies(response, tokens)
    return _token_response(user, tokens)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Rotate the access cookie using the refresh cookie",
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "model": ErrorResponse,
            "description": "Missing, revoked, or expired refresh token.",
        }
    },
)
def refresh(
    request: Request,
    response: Response,
    session: Session = Depends(get_db),
) -> TokenResponse:
    """Issue a new access cookie without requiring an interactive login.

    The refresh token slides forward on every successful use, so a user who
    returns within the configured refresh window stays signed in indefinitely.
    """
    raw_refresh = request.cookies.get(settings.REFRESH_TOKEN_COOKIE_NAME)
    result = auth_service.refresh_session(session, raw_refresh)
    if result is None:
        _clear_session_cookies(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired. Please sign in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user, tokens = result
    _set_session_cookies(response, tokens)
    return _token_response(user, tokens)


@router.get(
    "/me",
    response_model=UserRead,
    summary="Return the authenticated user and role",
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "model": ErrorResponse,
            "description": "Missing, invalid, or expired credentials.",
        }
    },
)
def read_current_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """Return the user derived from the access cookie or bearer token."""
    return current_user


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke the browser session and clear cookies",
)
def logout(
    request: Request,
    response: Response,
    session: Session = Depends(get_db),
) -> None:
    """Revoke the presented refresh token and delete both auth cookies.

    Logout deliberately does not require a valid access token: the access
    token may already have expired while the refresh cookie is still usable.
    """
    auth_service.revoke_session(
        session,
        request.cookies.get(settings.REFRESH_TOKEN_COOKIE_NAME),
    )
    _clear_session_cookies(response)
    return None
