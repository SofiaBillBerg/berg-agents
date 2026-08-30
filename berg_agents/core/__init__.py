"""Berg Agents core — public re-exports.

Framework-agnostic host primitives. Nothing in this package may import
LangGraph, LangChain, DeepAgents, FastAPI, or any other framework-specific
dependency. Frameworks are adapters, not the spine.
"""

from berg_agents.core.bookkeeper import Bookkeeper
from berg_agents.core.chat_server import (
    ChatServer,
    ChatServerBase,
    ModelInfo,
    ProtocolEvent,
    ProviderConfig,
    ThreadInfo,
)
from berg_agents.core.interface import (
    AbstractAgent,
    AgentResult,
    RiskLevel,
    TaskComplexity,
    TaskContext,
)
from berg_agents.core.learning_gate import LearningGate
from berg_agents.core.model_router import ModelRouter
from berg_agents.core.orchestrator import Orchestrator

# Backends are optional — only import if available
try:
    from berg_agents.backends import (
        LangChainAdapter,
        LangGraphAgent,
        is_langchain_available,
    )

    _BACKENDS_AVAILABLE = True
except ImportError:
    _BACKENDS_AVAILABLE = False

__all__ = [
    "AbstractAgent",
    "AgentResult",
    "Bookkeeper",
    "ChatServer",
    "ChatServerBase",
    "LearningGate",
    "ModelInfo",
    "ModelRouter",
    "Orchestrator",
    "ProtocolEvent",
    "ProviderConfig",
    "RiskLevel",
    "TaskComplexity",
    "TaskContext",
    "ThreadInfo",
]

if _BACKENDS_AVAILABLE:
    __all__.extend([
        "LangChainAdapter",
        "LangGraphAgent",
        "NativeAdapter",
        "NativeAgent",
        "is_langchain_available",
    ])
