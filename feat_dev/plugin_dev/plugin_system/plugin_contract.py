"""Plugin contract for the plugin system."""

#  <one line to give the program's name and a brief idea of what it does.>
#
#  Copyright (c) 2026.
#          Copyright (C) <year>  <name of author>
#
#          This program is free software: you can redistribute it and/or modify
#          it under the terms of the GNU Affero General Public License as
#          published by the Free Software Foundation, either version 3 of the
#          License, or (at your option) any later version.
#
#          This program is distributed in the hope that it will be useful,
#          but WITHOUT ANY WARRANTY; without even the implied warranty of
#          MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#          GNU Affero General Public License for more details.
#
#          You should have received a copy of the GNU Affero General Public License
#          along with this program.  If not, see <https://www.gnu.org/licenses/>.

from dataclasses import dataclass
import logging
from typing import Any

from berg_agents.capabilities.base import RiskClass
from berg_agents.core.interface import TaskComplexity
from pydantic_ai.agent.abstract import AbstractAgent
from pydantic_ai.tools import Tool

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
