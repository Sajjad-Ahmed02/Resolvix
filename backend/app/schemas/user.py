from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class UserRead(BaseModel):
    """Public user representation. Password hashes are never included."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    email: str
    role: Literal["customer", "admin"]
    created_at: datetime
    updated_at: datetime
