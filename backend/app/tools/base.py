"""Provider-neutral contracts for backend tools.

Tools are small, explicit backend capabilities. The model may request one by
name, but only the application registry decides whether it exists and only the
tool implementation validates and executes it. Tool code never accepts SQL,
shell text, or an authenticated user id from model output.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.ai.providers.base import ToolDefinition


@dataclass(frozen=True, slots=True)
class ToolContext:
    """Trusted request context supplied by the application.

    ``user_id`` always comes from the verified bearer token. It is deliberately
    kept out of model-generated tool arguments.
    """

    session: Session
    user_id: UUID
    conversation_id: UUID | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.user_id, UUID):
            raise ValueError("Tool context user_id must be a UUID")


@dataclass(frozen=True, slots=True)
class ToolOutcome:
    """A controlled success or failure returned to the model."""

    tool_name: str
    ok: bool
    data: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.tool_name, str) or not self.tool_name.strip():
            raise ValueError("Tool outcome name must not be blank")
        if self.ok:
            if self.data is None:
                raise ValueError("Successful tool outcomes require data")
            if self.error_code is not None or self.error_message is not None:
                raise ValueError(
                    "Successful tool outcomes cannot contain an error"
                )
        else:
            if not self.error_code or not self.error_message:
                raise ValueError(
                    "Failed tool outcomes require a code and safe message"
                )

    def as_payload(self) -> dict[str, Any]:
        """Build the JSON-serializable result shown to the model."""
        if self.ok:
            return {"ok": True, "data": self.data}
        return {
            "ok": False,
            "error": {
                "code": self.error_code,
                "message": self.error_message,
            },
        }

    def to_json(self) -> str:
        """Serialize the result for a provider tool-response message."""
        return json.dumps(
            self.as_payload(),
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )


class ToolArgumentError(ValueError):
    """Raised when model-generated tool arguments fail schema validation."""

    def __init__(self, message: str) -> None:
        self.safe_message = message
        super().__init__(message)


class Tool(ABC):
    """One allow-listed backend capability."""

    definition: ToolDefinition

    @abstractmethod
    def execute(
        self,
        context: ToolContext,
        arguments: dict[str, Any],
    ) -> ToolOutcome:
        """Validate arguments and run only the registered operation."""
