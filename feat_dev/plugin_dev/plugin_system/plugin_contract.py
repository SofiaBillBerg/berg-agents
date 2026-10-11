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
#

import logging
from abc import ABC
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic_ai.agent.abstract import AbstractAgent
from pydantic_ai.tools import Tool

from berg_agents import BergAgentsApp, Harness
from berg_agents.capabilities.base import RiskClass
from berg_agents.core.interface import TaskComplexity
from feat_dev.plugin_dev.plugin_system.lifecycle.bergplugin import BergPlugin
from feat_dev.plugin_dev.plugin_system.events.event_bus import EventBus

logger = logging.getLogger(__name__)


# 5. Plugin Context

# Plugins receive a context object with access to:


class PluginContext:
    """Runtime context provided to plugins."""

    # Plugin metadata
    plugin_id: str
    plugin_version: str
    plugin_dir: Path

    # Berg agents access
    app: BergAgentsApp
    harness: Harness
    config: dict[str, Any]

    # Plugin system
    plugin_manager: PluginManager
    event_bus: EventBus
    logger: logging.Logger

    # Settings
    settings: dict[str, Any]  # Plugin-specific settings

    # Methods
    def emit_event(self, event: str, data: Any) -> None:
        """

        :param event:
        :param data:
        """
        ...

    def subscribe(self, event: str, handler: Callable) -> None:
        """

        :param event:
        :param handler:
        """
        ...

    def get_plugin(self, plugin_id: str) -> BergPlugin | None:
        """

        :param plugin_id:
        """
        ...

    def register_tool(self, tool: Tool) -> None:
        """

        :param tool:
        """
        ...

    def register_agent(self, agent: AbstractAgent) -> None:
        """

        :param agent:
        """
        ...

    def get_setting(self, key: str, default: Any = None) -> Any:
        """Get a configuration setting."""
        keys = key.split(".")
        value = self.settings

        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default

            if value is None:
                return default

        return value

    def has_setting(self, key: str) -> bool:
        """Check if setting exists."""
        return self.get_setting(key) is not None


# 6. Capability Types

# Plugins expose capabilities through typed interfaces:


class PluginCapability(ABC):
    """Base for plugin-provided capabilities."""

    type: str


class ToolCapability(PluginCapability):
    type = "tool"
    tool: Tool
    risk_level: RiskClass
    deferred: bool = True


class AgentCapability(PluginCapability):
    type = "agent"
    agent_class: type[AbstractAgent]
    complexity_level: TaskComplexity


class ProviderCapability(PluginCapability):
    type = "provider"
    provider_id: str
    models: dict[str, dict[str, Any]]


class BackendCapability(PluginCapability):
    type: str = "backend"
    backend_type: str  # "search", "memory", "storage"
    backend_class: type
