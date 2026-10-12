"""Risk classification vocabulary for tools and capabilities.

This is the single source of truth for risk levels - used by
:class:`~berg_agents.core.tool_spec.ToolSpec` and the harness routing
layer to decide whether a tool call requires human-in-the-loop approval.
"""

from __future__ import annotations

from typing import Literal

#: Canonical risk levels.
#: ``high`` → requires explicit approval; ``"medium"`` → context-dependent;
#: ``"low"`` → safe to run without review.
RiskClass = Literal["low", "medium", "high"]

#: Named constants for convenient comparison and assignment.
RISK_LOW: RiskClass = "low"
RISK_MEDIUM: RiskClass = "medium"
RISK_HIGH: RiskClass = "high"

__all__ = ["RISK_HIGH", "RISK_LOW", "RISK_MEDIUM", "RiskClass"]
