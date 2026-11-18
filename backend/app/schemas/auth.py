from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.user import UserRead


# Pydantic's EmailStr rejects special-use domains such as the synthetic
# `resolvix.local` demo address. This project validates the basic mailbox shape
# without requiring a deliverable public domain.
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class LoginRequest(BaseModel):
    """Credentials for a pre-seeded customer or administrator account."""

    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if len(normalized) > 255 or not _EMAIL_PATTERN.fullmatch(normalized):
            raise ValueError("Enter a valid email address")
        return normalized


class TokenResponse(BaseModel):
    """JWT access token plus the authenticated user.

    Browsers receive the tokens in HttpOnly cookies. The access token is also
    returned for non-browser API clients and documented tooling; the web client
    never reads or stores it.
    """

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    refresh_expires_in: int
    user: UserRead
