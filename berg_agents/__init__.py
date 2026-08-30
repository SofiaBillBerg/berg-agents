"""Berg Agents — framework-agnostic multi-agent system.

The main entry point is BergAgentsApp:

    from berg_agents import BergAgentsApp
    app = BergAgentsApp.create()
    app.serve()  # Start web server

Or via CLI:
    berg-agents serve --web
    berg-agents chat
"""

from berg_agents.app import BergAgentsApp, get_app
from berg_agents.core import (
    AbstractAgent,
    AgentResult,
    LearningGate,
    ModelRouter,
    Orchestrator,
    RiskLevel,
    TaskComplexity,
    TaskContext,
)

__all__ = [
    "AbstractAgent",
    "AgentResult",
    "BergAgentsApp",
    "LearningGate",
    "ModelRouter",
    "Orchestrator",
    "RiskLevel",
    "TaskComplexity",
    "TaskContext",
    "get_app",
]
