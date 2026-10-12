"""Plugin health status types."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


@dataclass
class HealthStatus:
    """Plugin health status."""

    status: Literal["healthy", "degraded", "unhealthy"]
    checked_at: datetime = field(default_factory=datetime.now)
    message: str | None = None
    details: dict[str, Any] | None = None
