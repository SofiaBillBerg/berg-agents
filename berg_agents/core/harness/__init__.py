"""Harness package — re-exports for backward compatibility.

New code should import from `berg_agents.core.harness.orchestrator` for
Harness, and from `berg_agents.ui.schemas` for API schema types.
"""

from berg_agents.core.harness.orchestrator import Harness
from berg_agents.ui.schemas import (
    ActiveProvider,
    HitlAckResponse,
    HitlDecision,
    ProviderInfo,
    ProviderListResponse,
    ThreadResponse,
    ThreadStatusResponse,
    HarnessRequest,
)

__all__ = [
    "ActiveProvider",
    "Harness",
    "HarnessRequest",
    "HitlAckResponse",
    "HitlDecision",
    "ProviderInfo",
    "ProviderListResponse",
    "ThreadResponse",
    "ThreadStatusResponse",
]
