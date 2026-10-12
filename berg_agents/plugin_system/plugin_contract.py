"""Plugin contract for the plugin system."""

import logging
from dataclasses import dataclass
from typing import Any

from pydantic_ai.agent.abstract import AbstractAgent
from pydantic_ai.tools import Tool

from berg_agents.capabilities.base import RiskClass
from berg_agents.core.interface import TaskComplexity

logger = logging.getLogger(__name__)


# 6. Capability Types

# Plugins expose capabilities through typed interfaces:


@dataclass
class PluginCapability:
    """Base class for plugin capabilities."""

    type: str


@dataclass
class ToolCapability(PluginCapability):
    """A plugin capability that provides a tool."""

    type: str = "tool"
    tool: Tool = None
    risk_level: RiskClass = "medium"
    deferred: bool = True


@dataclass
class AgentCapability(PluginCapability):
    """A plugin capability that provides an agent."""

    type: str = "agent"
    agent_class: type[AbstractAgent] = None
    complexity_level: TaskComplexity = "medium"


@dataclass
class ProviderCapability(PluginCapability):
    """A plugin capability that provides a provider."""

    type: str = "provider"
    provider_id: str = ""
    models: dict[str, dict[str, Any]] = None


@dataclass
class BackendCapability(PluginCapability):
    """A plugin capability that provides a backend."""

    type: str = "backend"
    backend_type: str = ""  # "search", "memory", "storage"
    backend_class: type[Any] = None
