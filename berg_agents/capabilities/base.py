# Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture. The system follows a harness-based execution model with multiple specialized agents working together.
#
# Copyright (C) 2026 Sofia Billger Bergström <sofia.billger.bergstrom@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
#
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://gnu.org/licenses/agpl-3.0.html>.

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
