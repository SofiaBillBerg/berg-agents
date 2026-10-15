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

"""Plugin contract for the plugin system."""

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


@dataclass
class SkillCapability(PluginCapability):
    """A plugin capability that provides a skill (SKILL.md manual).

    Skills stay deferred by default: the model sees the one-line
    catalog entry (id + description) and loads the full content only
    when the task calls for it — same pattern as the chat agent's
    skill capabilities.
    """

    type: str = "skill"
    id: str = ""
    name: str = ""
    description: str = ""
    content: str = ""
    deferred: bool = True


@dataclass
class MCPCapability(PluginCapability):
    """A plugin capability that fronts one MCP server.

    Live tool names need a running session, so the capability carries
    the server descriptor (not tool objects): the chat agent already
    attaches the server's toolset, and this record gives it plugin
    lifecycle, events, and UI visibility.
    """

    type: str = "mcp"
    id: str = ""  # MCP server key from .berg-agents /mcp.json
    server_type: str = ""  # "remote" or "local"
    enabled: bool = True
    sensitive: bool = False  # every tool requires human approval
    tool_prefix: str = ""  # e.g. "mcp_github_"
