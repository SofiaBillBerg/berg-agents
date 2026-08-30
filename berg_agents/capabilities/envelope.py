"""Invocation envelopes for the capability layer.

These Pydantic v2 models define the request/response contract used to
invoke capabilities. Every capability call is wrapped in an
:class:`InvocationRequest` and returns an :class:`InvocationResponse`,
giving a uniform, auditable interface across all capabilities.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

class InvocationRequest(BaseModel):
    """A request to invoke a capability.

    Attributes:
        request_id: Unique identifier for this invocation.
        capability_id: Stable identifier of the capability to invoke.
        params: Typed parameters for the capability.
        caller: Optional identifier of the calling entity.
        created_at: ISO-8601 timestamp of when the request was created.
    """

    request_id: str
    capability_id: str
    params: dict[str, Any] = Field(default_factory=dict)
    caller: str | None = None
    created_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )


class InvokeBody(BaseModel):
    """JSON request body for ``POST /invoke``.

    Attributes:
        capability_id: Stable identifier of the capability to invoke.
        params: JSON object of parameters for the capability.
    """

    capability_id: str
    params: dict[str, Any] = Field(default_factory=dict)


class InvocationResponse(BaseModel):
    """The result of invoking a capability.

    Attributes:
        request_id: Echoes the request_id of the originating request.
        capability_id: Stable identifier of the invoked capability.
        status: Outcome of the invocation, either "ok" or "error".
        result: Structured result payload on success.
        error: Error message when status is "error".
        duration_ms: Wall-clock duration of the invocation in milliseconds.
    """

    request_id: str
    capability_id: str
    status: Literal["ok", "error"] = "ok"
    result: dict[str, Any] | None = None
    error: str | None = None
    duration_ms: int = 0
