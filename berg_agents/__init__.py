# Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture.
# The system follows a harness-based execution model with multiple specialized agents working together.
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

"""Berg Agents - framework-agnostic multi-agent system.

The main entry point is BergAgentsApp:

    from berg_agents import BergAgentsApp
    app = BergAgentsApp.create()
    app.serve()  # Start web server

Or via CLI:
    python -m berg_agents --web
    python -m berg_agents --tui
"""

from berg_agents.app import BergAgentsApp, get_app
from berg_agents.config.settings import ensure_env_loaded
from berg_agents.core import (
    AbstractAgent,
    AgentResult,
    Harness,
    LearningGate,
    RiskLevel,
    TaskComplexity,
    TaskContext,
)

# Load .berg-agents/.env into the process environment first: agent modules
# below construct their Pydantic AI models at import time, and the
# provider SDKs read endpoint configuration from the environment.
ensure_env_loaded()

__all__ = [
    "AbstractAgent",
    "AgentResult",
    "BergAgentsApp",
    "Harness",
    "LearningGate",
    "RiskLevel",
    "TaskComplexity",
    "TaskContext",
    "get_app"]
