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

# Load config/.env into the process environment first: agent modules
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
