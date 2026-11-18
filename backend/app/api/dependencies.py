"""Shared FastAPI dependencies for authentication and authorization."""

from __future__ import annotations

from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyCookie, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models import User
from app.repositories import users


bearer_scheme = HTTPBearer(
    auto_error=False,
    scheme_name="Bearer JWT",
    description=(
        "Paste the access_token returned by POST /auth/login. "
        "The token identifies the customer or administrator."
    ),
)

access_cookie_scheme = APIKeyCookie(
    name=settings.ACCESS_TOKEN_COOKIE_NAME,
    auto_error=False,
    scheme_name="Access Cookie",
    description=(
        "HttpOnly cookie set by POST /auth/login or POST /auth/refresh. "
        "Browsers use this automatically; JavaScript cannot read it."
    ),
)


def _credentials_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    cookie_token: str | None = Depends(access_cookie_scheme),
    session: Session = Depends(get_db),
) -> User:
    """Resolve the authenticated user from the bearer token or access cookie.

    The token subject is the only source of user identity. Request bodies,
    query parameters, and tool arguments can never select a different user.
    The user is reloaded from PostgreSQL on every request so deleted users and
    role changes take effect immediately.
    """
    token = credentials.credentials if credentials is not None else cookie_token
    if credentials is not None and credentials.scheme.lower() != "bearer":
        token = None
    if not token:
        raise _credentials_error()

    try:
        payload = decode_access_token(token)
        user_id = UUID(payload["sub"])
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError):
        raise _credentials_error() from None

    user = users.get_by_id(session, user_id)
    if user is None:
        raise _credentials_error()

    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Allow only users whose current database role is ``admin``."""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access required",
        )
    return current_user
